---
title: "StreamBroadcaster"
date: 2025-08-13
draft: false
---

Let's break down the `StreamBroadcaster` in detail. It's a crucial component for implementing the "shared broadcast" or "fan-out" pattern, which is at the heart of the new request de-duplication strategy.

### 1. The Core Problem it Solves

Imagine two or more users ask the exact same complex question at nearly the same time.

*   **The Inefficient Way:** The system processes each request independently. It runs the expensive tool selection, calls the LLM, and generates a response stream for User A. Then, it does the *exact same work* all over again for User B. This is a waste of resources (LLM tokens, CPU, API calls).
*   **The Efficient Way (with `StreamBroadcaster`):** The system recognizes the requests are identical (via a `cacheKey`). The first request (the "leader") initiates the expensive work. A `StreamBroadcaster` is created for this work. When the second request (the "follower") arrives, it doesn't do the work again. Instead, it simply "tunes in" to the broadcast already being generated for the leader.

The `StreamBroadcaster` is the mechanism that allows one source of events (the LLM or tool stream) to be distributed to multiple listeners (the HTTP response streams for each user).

### 2. The `StreamBroadcaster` Struct: Anatomy

Let's look at its fields. Each one serves a specific and important purpose.

```go
type StreamBroadcaster struct {
	lock        sync.Mutex                // For thread safety
	subscribers []chan tooltypes.StreamEvent // The list of all current listeners
	isDone      bool                      // A flag to indicate the broadcast is over
	history     []tooltypes.StreamEvent   // A recording of all past events
}
```

*   `lock sync.Mutex`: This is the most critical field for correctness. The `StreamBroadcaster` will be accessed by multiple goroutines simultaneously:
    *   One goroutine (the leader's) will be calling `Broadcast()` and `Close()`.
    *   Multiple other goroutines (for each follower client) will be calling `Subscribe()`.
    *   A cancellation goroutine might call `Unsubscribe()`.
    The `lock` ensures that operations that modify the shared state (`subscribers`, `isDone`, `history`) don't happen at the same time, preventing race conditions.

*   `subscribers []chan tooltypes.StreamEvent`: This is the list of "listeners". Each subscriber provides its own channel. The broadcaster's job is to put a copy of every event into each of these channels. This design decouples the broadcaster from the subscribers; the broadcaster doesn't care what the subscriber does with the event after it's sent.

*   `isDone bool`: This is a simple but vital state flag. Once the broadcast is finished (the LLM stream has ended), `isDone` is set to `true`. This prevents new subscribers from joining a completed stream and stops the `Broadcast` method from doing any more work. It's the "The Show Is Over" sign on the door.

*   `history []tooltypes.StreamEvent`: This is the secret sauce that makes "join-in-progress" possible. As each event is broadcast, it's also saved to this `history` slice. When a *new* subscriber joins midway through the broadcast, they don't miss the beginning. The `Subscribe` method will first "catch them up" by sending them every event from the `history` before adding them to the live broadcast.

---

### 3. How the Methods Work: A Step-by-Step Guide

#### `NewStreamBroadcaster()`
This is a simple constructor. It creates an instance of the struct, initializing the slices so they are not `nil`.

#### `Subscribe(sub chan tooltypes.StreamEvent)`
This is what a follower (or the initial leader) calls to start listening.

1.  **Lock:** It immediately acquires the mutex lock to ensure no other goroutine can change the broadcaster's state.
2.  **Replay History:** It iterates through the `b.history` slice and sends every past event to the new subscriber's channel (`sub`). This ensures the follower gets the full picture from the beginning.
3.  **Check if Done:** It checks the `b.isDone` flag. If the broadcast is already over, there's no point in subscribing. It simply closes the new subscriber's channel (`close(sub)`) to signal that there will be no more events, and returns.
4.  **Add to Subscribers:** If the broadcast is still live, it appends the new subscriber's channel to the `b.subscribers` slice.
5.  **Unlock:** The lock is released (via `defer`).

#### `Broadcast(event tooltypes.StreamEvent)`
This is called by the single goroutine that is producing the events (e.g., receiving chunks from the LLM).

1.  **Lock:** It acquires the lock.
2.  **Check if Done:** If `b.isDone` is true, it does nothing and returns immediately.
3.  **Record to History:** It appends the new `event` to the `b.history` slice. This is crucial for future subscribers.
4.  **Fan-out:** It loops through every channel in the `b.subscribers` slice.
5.  **Non-Blocking Send:** For each subscriber, it uses a `select` statement for a *non-blocking send*:
    ```go
    select {
    case sub <- event:
    default:
    }
    ```
    This is a key design choice for robustness. If a subscriber's channel is full (because the client is slow or disconnected and not reading from its HTTP stream), a normal send (`sub <- event`) would block the *entire broadcast*. All other healthy clients would be stuck waiting for the one slow client. The non-blocking send prevents this. If the channel is full, the `default` case is executed, the event is dropped *for that one slow client*, and the broadcaster moves on to the next subscriber. This prioritizes the health of the broadcast over guaranteed delivery to a misbehaving client.

#### `Close()`
This is called once the source stream has ended.

1.  **Lock:** It acquires the lock.
2.  **Idempotency Check:** It checks `if b.isDone`. If it's already closed, it does nothing. This makes it safe to call `Close()` multiple times.
3.  **Set Done Flag:** It sets `b.isDone = true`. This is the point of no return.
4.  **Notify Subscribers:** It loops through all remaining subscribers in the `b.subscribers` list and calls `close(sub)` on each of their channels. In Go, reading from a closed channel immediately returns the zero value, and a `for range` loop over a channel will terminate when the channel is closed. This is the standard, clean way to signal "end of stream" to all listeners.
5.  **Cleanup:** It sets `b.subscribers = nil` to release the memory held by the slice.

#### `Unsubscribe(subToUnsubscribe chan tooltypes.StreamEvent)`
This is used if a client disconnects or cancels but the main broadcast should continue for others.

1.  **Lock:** It acquires the lock.
2.  **Check if Done:** If the broadcast is over, there's nothing to do.
3.  **Find and Remove:** It iterates through the subscribers to find the channel that needs to be removed. To remove it efficiently without preserving order, it uses this common Go slice trick: it overwrites the element to be removed with the *last* element in the slice, and then truncates the slice by one. This is much faster than re-slicing and creating a new slice, as it avoids memory allocation and shifting all subsequent elements.

---

### 4. Lifecycle in the Application

1.  **Request 1 (Leader):**
    *   `Manager` sees a new `cacheKey`.
    *   It uses `singleflight.Do` to become the "leader".
    *   Inside the singleflight function, it creates a `NewStreamBroadcaster`.
    *   It starts the actual work (`initiateAndManageBroadcast`), which will call `Broadcast()` for each event.
    *   It calls `broadcaster.Subscribe()` for itself.

2.  **Request 2 (Follower):**
    *   `Manager` sees the same `cacheKey`.
    *   `singleflight.Do` ensures this request *waits* for the leader's function to return the `broadcastInfo`. It receives the *same* `StreamBroadcaster` instance that the leader created.
    *   It calls `broadcaster.Subscribe()` for its own client channel.
    *   `Subscribe` immediately replays the `history` so the follower's stream catches up to the leader's.
    *   The follower is now in the `subscribers` list and receives live events alongside the leader.

3.  **Broadcast Ends:**
    *   The LLM/tool stream finishes.
    *   The `initiateAndManageBroadcast` goroutine calls `broadcaster.Close()`.
    *   `Close()` sets `isDone = true` and closes the channels of both the leader and the follower. Their `for range` loops over the stream terminate, and their HTTP connections are closed cleanly.
