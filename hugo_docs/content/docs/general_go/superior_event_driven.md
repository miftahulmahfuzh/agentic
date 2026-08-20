---
title: "Superior Event-Driven"
date: 2025-07-12
lastmod: 2026-07-09
draft: false
---

You might look at the chatbot system and wonder why it's structured with a channel inside a struct (`RequestStream.Stream` at `types/models.go:144`) which itself is passed between functions before finally being used. It might seem complex.

The reason is simple: this architecture is fundamentally more intelligent, efficient, and scalable than the common alternative—a polling loop. The alternative is the architectural equivalent of a security guard repeatedly running to the front gate every 10 seconds to see if a package has arrived. Our way is letting the guard sleep soundly at their desk until the delivery driver rings the bell.

### The Old Way: Inefficient Polling ("Are We There Yet?")

Let's imagine for a moment we had designed `GetRequestResultStream` using a naive polling strategy. It would be a disaster. The client would call the function, and to get the result, it would have to constantly check if the workers were done yet.

It would look something like this **(this is a hypothetical bad example, not our actual code)**:

```go
// A HYPOTHETICAL, INEFFICIENT POLLING IMPLEMENTATION
func GetRequestResultStream_BAD(ctx context.Context, requestID string) (<-chan types.StreamEvent, error) {
	ticker := time.NewTicker(100 * time.Millisecond) // Check every 100ms
	defer ticker.Stop()
	timeout := time.After(config.AppSettings.ProcessingTimeout)

	for { // <-- THIS IS THE PROBLEM
		requestsLock.RLock()
		streamHolder, ok := activeRequests[requestID]
		requestsLock.RUnlock()

		if ok {
            // How do we know it's ready? We can't peek into a channel.
            // So we'd have to check the State. Let's pretend we update
            // the state to 'Ready' right before we start the stream.
			if streamHolder.State == types.StateReadyToStream { // A FAKE STATE
				// Now we can try to grab the stream...
                return streamHolder.Stream, nil // Hope it's there!
			}
		}
		// ... error handling for not found ...

		select {
		case <-ticker.C:
			continue // WAKE UP, LOCK, CHECK, UNLOCK, SLEEP. REPEAT.
		case <-timeout:
			return nil, fmt.Errorf("timed out waiting for stream")
		case <-ctx.Done():
			return nil, ctx.Err()
		}
	}
}
```

This is fundamentally wasteful. For the entire duration that the request is being processed (cache lookup, preparation, or LLM streaming), this goroutine would be in a frantic cycle of:
1.  Waking up.
2.  Acquiring a global read lock.
3.  Checking a map for a value.
4.  Releasing the lock.
5.  Going back to sleep.

This burns CPU cycles for no reason, creates unnecessary lock contention on the critical `activeRequests` map, and adds latency. It's a headless chicken running around a barn, hoping to stumble upon some corn.

### The New Way: Event-Driven ("The Rendezvous")

Our code is intelligent. It doesn't ask "is it ready?". It says, "I am going to wait right here. Notify me when it's ready," and then goes to sleep. It's a rendezvous. The goroutine arrives at the meeting point and waits, consuming zero resources until the other party arrives with the goods.

Look at the current flow:

1.  **`submitRequest` (`chatbot/manager.go:194`, holder built at `:298`):** Creates a `RequestStream` holder. Think of this as a briefcase or secure drop-box. It contains channels for the result stream (`Stream`), errors (`Err`), and a client-connection signal (`ClientConnected`), plus state and progress bookkeeping. This drop-box is immediately placed in the global `activeRequests` map (`:314`). (The public entry point is `SubmitRequest` in `chatbot/main_handlers.go:90`, which delegates here.)
    ```go
    // chatbot/manager.go:298
    streamHolder := &types.RequestStream{
        Stream:          make(chan (<-chan types.StreamEvent), internal.SingleItemBuffer),
        Err:             make(chan error, internal.SingleItemBuffer),
        ClientConnected: make(chan struct{}),
        State:           types.StateQueued, // Initialize with submitted state
        LastStateChange: time.Now(),
        UserID:          userID,
        RequestContext:  requestCtx,
        Progress: &types.ProgressInfo{
            Stage:           internal.ProgressStageSubmitted,
            StageStartTime:  time.Now(),
            CompletionRatio: internal.InitialProgressRatio, // 10% - just started
        },
    }
    ```

    The struct itself is defined at `types/models.go:143`:
    ```go
    // types/models.go:143
    type RequestStream struct {
        Stream          chan (<-chan StreamEvent) // The client gets the event stream from this channel.
        Err             chan error                // Errors are sent here.
        ClientConnected chan struct{}             // Closed when the client connects to the stream endpoint.
        State           RequestState              // The current state of the request.
        LastStateChange time.Time                 // Timestamp of the last state change.
        UserID          string
        RequestContext  context.Context           // Individual request context
        PersistChannel  chan StreamEvent          // RESUME FEATURE: mirrors events for later resume access
        Progress        *ProgressInfo
        Sources         map[string]SourceInfo
    }
    ```

2.  **`GetRequestResultStream` (`chatbot/main_handlers.go:23`, core logic in `getRequestResultStream` at `chatbot/manager.go:954`):** The client calls this function. It finds the drop-box for its `requestID` and immediately does this:
    ```go
    // chatbot/manager.go:1024 - Found active request, wait for result
    select {
    case stream := <-streamHolder.Stream: // <-- WAITING HERE
        // ...wrap with bowl-based persistence, then return stream...
    case err := <-streamHolder.Err:       // <-- OR WAITING HERE FOR AN ERROR (:1081)
        return nil, err
    case <-time.After(m.config.ProcessingTimeout): // Timeout protection (:1088)
        // cleanup + timeout error
    case <-ctx.Done(): // Client disconnection (:1091)
        // cleanup + ctx error
    }
    ```
    The key is `<-streamHolder.Stream`. This is a **blocking read on a channel**. The goroutine stops dead. It is descheduled by the Go runtime. It consumes **ZERO CPU**. It is completely asleep, waiting for something to be put into that channel.

3.  **The Activation Signal:** Meanwhile, in a completely separate part of the application, a worker creates the *actual* channel that events will flow through (`clientChan`) and places it inside `streamHolder.Stream`. There are two real paths that do this, and both perform the identical rendezvous:

    **Path 1: Cache Fast-Lane (`chatbot/cache/fastlane.go:147`, in `handleCachedRequest`)** — instant cache hit, streaming starts immediately:
    ```go
    clientChan := make(chan types.StreamEvent, config.GetStreamTokenBuffer())
    select {
    case streamHolder.Stream <- clientChan: // <-- ACTIVATION: cache streaming
        logCtx.Debug().Msg("Stream channel sent to client")
    case <-time.After(internal.CacheVerifyTimeout):
        close(clientChan)
        return false
    case <-ctx.Done():
        close(clientChan)
        return false
    }
    ```

    **Path 2: Normal Processing** — after preparation, run the streamer and hand off the channel. This is the same shape in both the queued path `executeTask` (`chatbot/manager.go:531`, handoff at `:638`) and the priority path `executeTaskImmediate` (`chatbot/manager.go:645`, handoff at `:758`):
    ```go
    clientChan := getStreamEventChannel(config.GetStreamTokenBuffer())
    streamHolder.Stream <- clientChan          // <-- ACTIVATION: LLM streaming
    go m.GetStreamer().Stream(clientChan, preparedData, logCtx)
    ```

    This single send operation (`streamHolder.Stream <- clientChan`) is the "event". It's the delivery driver ringing the bell.

4.  **The Payoff:** The moment `streamHolder.Stream <- clientChan` executes (from either path), the sleeping `getRequestResultStream` goroutine, which has been patiently and efficiently waiting on `<-streamHolder.Stream`, **instantly wakes up**. It receives the `clientChan`, optionally wraps it with bowl-based persistence for resume capability, and returns it to the client. The streaming of data begins.

### Conclusion

This architecture is superior because it replaces an active, wasteful polling loop with a passive, efficient, channel-based waiting mechanism.

*   **Flawed Way:** CPU is busy checking a condition repeatedly. Wastes energy, causes lock contention, doesn't scale.
*   **Superior Way:** CPU is free. The goroutine sleeps until the Go runtime, notified by a channel event, wakes it up to perform work. It's efficient, clean, and highly scalable.

This is the essence of modern concurrent design. You don't look for work; the work comes to you.

### Why Multiple Activation Paths Don't Complicate the Pattern

The event-driven design remains simple despite having more than one activation source:

1. **Same Contract**: Every path creates a `chan types.StreamEvent` and sends it to `streamHolder.Stream`.
2. **Same Waiting Mechanism**: `getRequestResultStream` doesn't care which path activates it—cache fast-lane or normal LLM streaming.
3. **Zero Coupling**: The waiting goroutine is completely decoupled from the activation mechanism.
4. **Single Responsibility**: Each path handles its own streaming logic, but all use the same rendezvous pattern.

The beauty is that `getRequestResultStream` sleeps efficiently regardless of whether it will be awakened by:
- Cache fast-lane (near-instant)
- Preparation + LLM streaming (seconds)

**The pattern is identical. The timing varies. The efficiency is constant.**

This is the difference between being a mindless drone and a trained assassin.
