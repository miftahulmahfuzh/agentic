---
title: "Streamer Q&A Part 1"
date: 2025-08-06
draft: false
---

**Question:** We've observed a critical stability issue where our server's memory usage continuously increases over time, eventually leading to a crash. The problem seems to be linked to clients disconnecting while a response is being streamed. How can a client simply closing their browser tab cause a "zombie goroutine" that leaks memory, and how does the new `streamer.go` architecture definitively solve this?

**Answer:** This is an excellent and critical question. The phenomenon you're describing is a classic and dangerous concurrency problem in Go, often leading to "zombie" or "leaked" goroutines.

Here's a detailed breakdown of the problem and the solution.

---

### Part 1: The Root Cause - The "Stuck Writer" Flaw in the Old `streamer.go`

The leak occurs because of a fundamental property of Go channels: writing to an unbuffered channel is a **blocking operation**. The goroutine attempting to write will pause until another goroutine is ready to read.

Let's trace the failure sequence in the old architecture:

1.  **Request Starts:** A client connects to the `/chat/stream/:request_id` endpoint. The `handleStreamRequest` handler receives a channel (`streamChan`) to read from and starts listening. A worker goroutine is spawned to handle the request and will eventually write to this channel.

2.  **Work Begins:** The worker goroutine (`Streamer.Stream`) starts generating the AI response, producing events to send to the client.

3.  **The Blocking Write:** The goroutine attempts to send an event to the client: `streamChan <- event`. At this exact moment, it pauses, waiting for the `handleStreamRequest` handler to read the event from the channel.

4.  **Client Disconnects:** The user closes their browser tab or their network connection drops.

5.  **The Handler Exits:** In `main.go`, the `c.Writer.CloseNotify()` signal fires, indicating the client is gone. The `handleStreamRequest` handler logs the disconnect and, crucially, `return`s. **The only code that was reading from `streamChan` is now gone.**

6.  **The Goroutine is Leaked:** The worker goroutine is still alive, but it's permanently frozen at the `streamChan <- event` line. It is waiting for a reader that will *never* come. This goroutine is now a **zombie**:
    *   It will never complete its work.
    *   It will never be garbage collected.
    *   It continues to hold all its allocated memory (its stack, local variables, etc.) forever.

With every disconnected client, another zombie goroutine is created, and the server's memory usage climbs relentlessly until it crashes.

The specific flaw in `OLD STREAMER.GO` is every direct, unguarded channel write:

```go
// OLD STREAMER.GO - The source of the leak
llms.GenerateFromSinglePrompt(ctx, s.services.LLM, logData.FinalInput,
    llms.WithStreamingFunc(func(ctx context.Context, chunk []byte) error {
        // ...
        // THIS IS THE BLOCKING POINT. If the handler is gone,
        // the goroutine freezes here forever, leaking memory.
        streamChan <- tooltypes.StreamEvent{Type: tooltypes.StreamEventToken, Payload: string(chunk)}
        // ...
        return nil
    }),
)
```

---

### Part 2: The Solution - Robust, Context-Aware Writes in the New `streamer.go`

The new architecture solves this by making the write operation "cancellation-aware." The worker goroutine no longer just blindly tries to write; it simultaneously listens for a signal that the request has been cancelled. This is achieved using a `select` statement with the request's `context`.

#### A. The Core Mechanism: The `sendEvent` Helper

The heart of the fix is this new helper function:

```go
// NEW STREAMER.GO - The solution
func (s *ResponseStreamer) sendEvent(ctx context.Context, streamChan chan<- tooltypes.StreamEvent, event tooltypes.StreamEvent) error {
	select {
	case <-ctx.Done():
		// ESCAPE HATCH: The context was cancelled. Stop trying to write.
		return ctx.Err() // Return an error (e.g., context.Canceled)
	case streamChan <- event:
		// HAPPY PATH: The write succeeded because the client is still listening.
		return nil
	}
}
```

This `select` statement attempts two operations at once and proceeds with whichever one becomes ready first:

*   **If the client is connected:** The `streamChan <- event` case will succeed, the event is sent, and the function returns `nil`.
*   **If the client has disconnected:** The `streamChan <- event` case will block. However, the system now sends a cancellation signal. This closes the `ctx.Done()` channel, making the `<-ctx.Done()` case immediately ready. The function returns an error, **unblocking the goroutine**.

#### B. The Full Cancellation Flow

Here is how the scenario plays out correctly in the new architecture:

1.  **Client Disconnects:** Same as before.
2.  **Manager Cancels Request:** The `handleStreamRequest` handler now calls `app.chatManager.CancelStream(requestID)`. This is a critical new step.
3.  **Context is Cancelled:** Inside the `Chatbot Manager`, the `context.CancelFunc` associated with this specific request is called. This sends a cancellation signal down the `context` that was passed to the worker goroutine.
4.  **The Escape Hatch Fires:** The worker goroutine, in the middle of its work, calls `s.sendEvent(...)`. Inside this function, the `select` statement sees that `<-ctx.Done()` is ready. It immediately chooses that case and returns a `context.Canceled` error.
5.  **Graceful Shutdown:** The main body of the `Stream` function receives this error, knows it has been cancelled, stops its processing (e.g., breaks out of its loop), and returns. The goroutine exits cleanly, and all its resources are released.

**The leak is prevented.** The goroutine cleans itself up as soon as it's notified that its work is no longer needed.

### Summary: Old vs. New

| Aspect | `OLD STREAMER.GO` (Flawed) | `NEW STREAMER.GO` (Robust) |
| :--- | :--- | :--- |
| **Write Operation** | `streamChan <- event` | A `select` block that tries to write **OR** checks for cancellation. |
| **Logic** | "Fire and Block." Writes and will wait forever if there's no reader. | "Write or Abort." Tries to write but will immediately abort if the request is cancelled. |
| **Cancellation** | The goroutine is oblivious to cancellation and becomes an orphan. | The goroutine is explicitly linked to the request's `context` and respects its cancellation. |
| **Outcome** | **Goroutine Leak.** A "zombie" goroutine is created on every premature client disconnect, consuming resources until the server crashes. | **Graceful Termination.** The goroutine detects cancellation, stops its work, and exits, releasing all its resources back to the system. |

