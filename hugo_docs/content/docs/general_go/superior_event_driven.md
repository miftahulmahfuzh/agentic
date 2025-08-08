---
title: "Superior Event-Driven"
date: 2025-08-02
draft: false
---

**Previously On:** [Busy-Wait Loops](https://miftahulmahfuzh.github.io/agentic/docs/general_go/busy_wait_loops)

# The Flaw of Polling vs. The Power of Event-Driven Design

You might look at the new `manager.go` and wonder why it’s structured with a channel inside a struct (`RequestStream.Stream`) which itself is passed between functions before finally being used. It might seem complex.

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

This is fundamentally wasteful. For the entire duration that the request is being prepared by the `prepareWorker` and waiting in the `preparedQueue`, this goroutine would be in a frantic cycle of:
1.  Waking up.
2.  Acquiring a global read lock.
3.  Checking a map for a value.
4.  Releasing the lock.
5.  Going back to sleep.

This burns CPU cycles for no reason, creates unnecessary lock contention on the critical `activeRequests` map, and adds latency. It's a headless chicken running around a barn, hoping to stumble upon some corn.

### The New Way: Event-Driven ("The Rendezvous")

Our new code is intelligent. It doesn't ask "is it ready?". It says, "I am going to wait right here. Notify me when it's ready," and then goes to sleep. It’s a rendezvous. The goroutine arrives at the meeting point and waits, consuming zero resources until the other party arrives with the goods.

Look at the new flow:

1.  **`SubmitRequest`:** It creates a `RequestStream` holder. Think of this as a briefcase or a secure drop-box. It contains two channels: one for the eventual result stream (`Stream`) and one for an error (`Err`). This drop-box is immediately placed in the global `activeRequests` map.
    ```go
	streamHolder := &types.RequestStream{
		Stream:          make(chan (<-chan types.StreamEvent), 1),
		Err:             make(chan error, 1),
		ClientConnected: make(chan struct{}),
		State:           types.StateQueued,
		LastStateChange: time.Now(),
	}
    ```

2.  **`GetRequestResultStream`:** The client calls this function. It finds the drop-box for its `requestID` and immediately does this:
    ```go
    select {
	case stream := <-streamHolder.Stream: // <-- WAITING HERE
		log.Printf("[GetStream - %s] Stream is ready. Returning to client.", requestID)
		return stream, nil
	case err := <-streamHolder.Err:      // <-- OR WAITING HERE FOR AN ERROR
		log.Printf("[GetStream - %s] An error occurred: %v", requestID, err)
		return nil, err
    // ... timeout cases ...
    }
    ```
    The key is `<-streamHolder.Stream`. This is a **blocking read on a channel**. The goroutine stops dead. It is descheduled by the Go runtime. It consumes **ZERO CPU**. It is completely asleep, waiting for something to be put into that channel.

3.  **`streamWorkerManager`:** Meanwhile, in a completely separate part of the application, a worker has picked the request from the `preparedQueue`. It's ready to start the expensive LLM call. It gets the same `streamHolder` drop-box and performs the rendezvous:
    ```go
    streamChan := make(chan types.StreamEvent, config.AppSettings.StreamTokenBuffer)
    holder.Stream <- streamChan // <-- THE ACTIVATION SIGNAL. THE PACKAGE IS DROPPED.
    ```
    This single line is the "event". The worker creates the *actual* channel that the LLM tokens will flow through (`streamChan`) and places it inside the `holder.Stream` channel.

4.  **The Payoff:** The moment `holder.Stream <- streamChan` executes, the sleeping `GetRequestResultStream` goroutine, which has been patiently and efficiently waiting on `<-streamHolder.Stream`, instantly wakes up. It receives the `streamChan`, returns it to the client, and the streaming of data begins.

### Conclusion

The new architecture is superior because it replaces an active, wasteful polling loop with a passive, efficient, channel-based waiting mechanism.

*   **Flawed Way:** CPU is busy checking a condition repeatedly. Wastes energy, causes lock contention, doesn't scale.
*   **Superior Way:** CPU is free. The goroutine sleeps until the Go runtime, notified by a channel event, wakes it up to perform work. It's efficient, clean, and highly scalable.

This is the essence of modern concurrent design. You don't look for work; the work comes to you. It's the difference between being a mindless drone and a trained assassin.
