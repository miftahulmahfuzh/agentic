---
title: "A War Against Race Conditions"
date: 2025-08-02
draft: false
---

**Next Episode:** [For The Greater Good](https://miftahulmahfuzh.github.io/agentic/docs/architectures/bigger_picture)

The goal was simple: a stable, high-concurrency streaming chatbot. The reality was a series of cascading failures rooted in the subtle complexities of Go's concurrency model. This document details the problems we faced, from the obvious memory leaks to the treacherous race conditions that followed, and the specific architectural changes in `manager.go` and `streamer.go` that were required to achieve true stability.

---

### Problem #1 - The Zombie Apocalypse (The Original Goroutine Leak)

**Symptom:** The server's memory usage would climb relentlessly over time, especially under load, leading to an inevitable crash.

**Root Cause: The "Stuck Writer" Flaw.**
The original `streamer.go` had a fatal flaw. Writing to a Go channel (`streamChan <- event`) is a **blocking operation**. The writer goroutine will freeze until a reader is ready. When a client disconnected, the reading part of the code in `handleStreamRequest` would terminate. However, the worker goroutine was left frozen mid-write, waiting for a reader that would never come.

This created a **zombie goroutine**: a process that was still alive, holding memory, but would never complete. Every disconnected client created another zombie, leading to a slow, inevitable memory leak.

```go
// OLD STREAMER.GO - The source of the leak
// If the client disconnects, the goroutine running this code
// freezes here forever, leaking its memory and resources.
streamChan <- tooltypes.StreamEvent{Type: tooltypes.StreamEventToken, Payload: string(chunk)}
```

**Solution: The Context-Aware Escape Hatch (`sendEvent`).**
The fix was to make the write operation "cancellation-aware" by using the request's `context`. We introduced a helper function, `sendEvent`, that uses a `select` statement.

```go
// NEW STREAMER.GO - The initial fix
func (s *ResponseStreamer) sendEvent(ctx context.Context, streamChan chan<- tooltypes.StreamEvent, event tooltypes.StreamEvent) error {
	select {
	case <-ctx.Done(): // If the context is cancelled...
		return ctx.Err() // ...abort the write and return an error.
	case streamChan <- event: // Otherwise, proceed with the write.
		return nil
	}
}
```
Now, when a client disconnects, the manager cancels the request's context. The `sendEvent` function sees `<-ctx.Done()` become ready, aborts the write, and allows the goroutine to shut down gracefully, releasing its memory.

**This solved the memory leak but, like a Faustian bargain, created two new, more insidious race conditions.**

---

### Problem #2 - The Pre-emptive Cleanup (The Keyser Söze Problem)

**Symptom:** A client calls `/cancel` on a request and *then* calls `/stream` to get the final cancellation confirmation. Instead of the expected `{"status":"cancelled"}` message, they receive a "request not found" error. The request had vanished.

**Root Cause: Overly Aggressive Cleanup.**
Our new cancellation mechanism was too effective. Here's the race:
1.  `CancelStream` is called. It correctly marks the request as `StateCancelled` and triggers the context cancellation.
2.  The worker goroutine, which has a `defer m.cleanupRequest(...)` statement, immediately sees the cancelled context and exits.
3.  The deferred `cleanupRequest` runs, completely wiping all trace of the request from the `activeRequests` map. It's a ghost.
4.  The client, a moment later, calls `/stream` to get the final status, but the request record is already gone.

**Solution: Conditional, Responsible Cleanup in `manager.go`.**
The worker goroutine needed to be taught some discretion. It cannot clean up a request that was explicitly cancelled by the user, because that request is waiting to deliver a "pre-canned" cancellation message.

The fix was to make the worker's deferred cleanup conditional. It now checks the state of the request before acting.

```go
// chatbot/manager.go - The fix in streamWorkerManager's defer block
defer func() {
    m.requestsLock.RLock()
    h, h_ok := m.activeRequests[reqID]
    m.requestsLock.RUnlock()

    // If the request was explicitly cancelled, it's not our job to clean up.
    // We yield responsibility to the newCancelledStream flow.
    if h_ok && h.State == types.StateCancelled {
        logCtx.Info().Msg("Request was cancelled. Worker is yielding cleanup responsibility.")
        return
    }

    // Otherwise, proceed with normal timeout-based cleanup.
    m.cleanupRequest(reqID, logCtx)
}()
```
The worker now yields cleanup duty for `StateCancelled` requests, ensuring the record stays alive long enough for `GetRequestResultStream` to find it and serve the proper confirmation.

---

### Problem #3 - The Muted Messenger (The "Hasta la Vista" Paradox)

**Symptom:** A client calls `/cancel` *during* an active stream. The stream stops, but the connection simply closes. The final, crucial `{"status":"cancelled"}` message is never received.

**Root Cause: A Logical Paradox.**
This was the most subtle problem.
1.  `/cancel` is called mid-stream, and the context is cancelled.
2.  The `streamer`, using our robust `sendEvent` function, detects the cancelled context on its next token-send attempt and correctly returns a `context.Canceled` error.
3.  The error handling logic (`handleLLMStreamError`) catches this error and attempts to send the final cancellation message to the client.
4.  **The Paradox:** To send this final message, it uses a function that relies on `sendEvent`. But `sendEvent` is designed to *immediately fail* if the context is cancelled. It was doing its job perfectly, which prevented it from delivering the final word. The system was trying to shout a message through a phone line it had just proudly cut.

**Solution: The "Last Gasp" Write in `streamer.go`.**
For this one specific scenario, we needed a function that would attempt one final, non-blocking, fire-and-forget write that *ignores* the context.

```go
// chatbot/streamer.go - The "Last Gasp" helper
func (s *ResponseStreamer) sendLastGaspTerminalInfo(streamChan chan<- tooltypes.StreamEvent, message string, status types.CompletionStatus) {
    // ... create event ...
	select {
	case streamChan <- event:
		// We tried, and it worked. Good.
	default:
		// The client is already gone. The channel is blocked. We don't care. Abort.
	}
}
```
This function is called *only* when a `context.Canceled` error is detected in the streaming logic. It makes one best-effort attempt to send the final status. If the client is still connected for that microsecond, they get the message. If not, the function returns instantly without blocking, preventing any new leaks.

### Summary: The War Report

| Problem | Symptom | Root Cause | Solution |
| :--- | :--- | :--- | :--- |
| **#1: The Zombie Apocalypse** | Steadily increasing memory usage, leading to server crashes. | **"Stuck Writer":** A goroutine blocks forever on a channel write to a disconnected client. | **Context-Aware Writes:** Use `select` with `<-ctx.Done()` in a `sendEvent` helper to provide an escape hatch, allowing the goroutine to terminate gracefully. |
| **#2: The Pre-emptive Cleanup** | Calling `/cancel` then `/stream` results in a "not found" error, not a cancellation message. | **"Overly Aggressive Cleanup":** The worker's `defer` statement cleans up the request record before the client can poll for the final status. | **Conditional Cleanup (`manager.go`):** The worker's `defer` now checks the request state. If `StateCancelled`, it yields cleanup responsibility, keeping the record alive. |
| **#3: The Muted Messenger** | Calling `/cancel` mid-stream closes the connection without a final confirmation message. | **"The Cancellation Paradox":** The mechanism to detect cancellation (`sendEvent`) also prevents sending the final cancellation message. | **"Last Gasp" Write (`streamer.go`):** A special, non-blocking, fire-and-forget send function is used *only* for this case, making one final attempt to deliver the message. |

