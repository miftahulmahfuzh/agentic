---
title: "Concurrent & Parallel"
date: 2025-08-13
draft: false
---

# Concurrency & Parallelism: The Ops Center of `manager.go`

Welcome to the mission briefing. Our `manager.go` file is the central nervous system of our chatbot operation, much like an MI6 Ops Center. It needs to handle a flood of incoming requests from agents (users) all over the world. To do this without melting down, it masterfully employs the arts of **concurrency** and **parallelism**.

## Concurrency: Juggling Multiple Missions at Once

Concurrency is about structuring our code to handle many things at once, even if we only have one CPU core doing the work. It's about switching between tasks efficiently so that no single task blocks the entire system.

In `manager.go`, concurrency is achieved primarily through **Goroutines** and **Channels**.

### The Tools of Concurrency:

1.  **Goroutines (`go func(...)`)**: Every time you see `go ...`, we're launching a new, independent task. It could be processing a new request, the janitor cleaning up old files, or a "leader" generating a response stream for multiple listeners. They all run without waiting for each other to finish.

2.  **Channels (`chan`)**: This is our secure communication line.
    *   `requestQueue`: This is the "mission assignment" desk. New requests arrive here and wait to be picked up by a worker from the pool.
    *   **The `StreamBroadcaster`**: This is the real star of the show. Think of it as a secure, open-frequency radio broadcast. One agent (the "leader") starts broadcasting intel (the LLM response stream), and any other agents on the same mission (the "followers") can simply tune in and receive the same live feed. It's how we efficiently share the results of one expensive operation with many clients.

3.  **The `select` Statement**: This is the system's "situational awareness." A `select` block allows a goroutine to listen to multiple channels at once. It's like Batman in *The Dark Knight* watching dozens of monitors, waiting for a signal.
    *   The `janitor` uses `select` to wait for either its next cleaning interval (`ticker.C`) or a shutdown signal (`ctx.Done()`).
    *   The `requestWorkerPool` uses `select` to wait for a new mission from the `requestQueue` or a shutdown signal.

4.  **`sync.RWMutex`: The Consigliere**: The `activeRequests` map is our "family business" ledger. Multiple goroutines need to read from it, and some need to write to it. The `sync.RWMutex` is our Tom Hagen from *The Godfather*.
    *   `m.requestsLock.RLock()`: Many agents can **ask** what the plan is (a read lock). This is fast.
    *   `m.requestsLock.Lock()`: But only **one** agent can go into the room to **change** the plan (a write lock). All others must wait.
    *   This primitive protects our shared data from being corrupted, ensuring the integrity of our operation.

5.  **`context.Context` and `cancel()`: The Kill Switch**: Every operation that might take time (API calls, LLM streams) is given a `context`. This context is our kill switch, like the neck bombs from *Suicide Squad*.
    *   When a request is cancelled or times out, we call its `cancel()` function. This sends a signal down through `ctx.Done()` to every goroutine working on that request. They see the signal, stop what they're doing, and clean up. "Mission aborted. Get out now."
    *   This gets even more interesting with the broadcast model. If a **follower** cancels, they are simply unsubscribed from the broadcast. If the **leader** cancels, we perform a clever deception: we send a fake cancellation message to *their* stream and unsubscribe them, but the underlying broadcast continues for any other followers. The mission must go on!

6.  **`sync.WaitGroup`: The Rendezvous Point**: In `streamer.go`, when a tool that streams its own output is called, it runs in its own goroutine. The main goroutine needs to wait for the tool to finish completely. A `sync.WaitGroup` is the rendezvous point, like in *Ocean's Eleven*. Danny Ocean tells the team (`wg.Add(1)`), and he waits at the exit (`wg.Wait()`) until every member has done their job and signaled they're clear (`defer wg.Done()`). This ensures perfect synchronization.

### The "Janitor": The Cleaner

The `janitor` goroutine is our Mike Ehrmantraut from *Breaking Bad* or Winston from *John Wick*. It's a background process that runs periodically (`time.NewTicker`) to clean up messes. It finds requests that have been stuck in the queue too long ("timed out in queue") or are taking too long to process ("timed out during processing"). It then purges their records, ensuring the system stays clean. No loose ends.

---

## Parallelism: Executing with the Full Crew

Parallelism is when we take our concurrent design and run it on a machine with multiple CPU cores. Now, multiple tasks aren't just being *managed* at once; they are *executing* at the exact same time.

In `manager.go`, this is controlled by our **Worker Pool, Semaphores, and the Single-Flight Group**. We don't want to unleash an infinite number of Hulks on our system; we need to control our resources.

### The Tools of Parallelism:

1.  **Worker Pool (`requestWorkerPool`)**: Instead of a multi-stage assembly line, we now have a unified team of elite agents. The `requestWorkerPool` listens to the `requestQueue` and dispatches workers to handle missions *in parallel*, from start to finish.

2.  **Semaphores (`chan struct{}`)**: This is our resource management, our "Nick Fury" deciding who gets deployed. A semaphore is a channel used to limit how many goroutines can access a resource simultaneously.
    *   `prepareSemaphore`: Its size (`config.MaxConcurrentRequests`) determines how many requests can be processed at the same time. This is like having the *Fast & Furious* family's tech crew (Tej, Ramsey) all working on different hacks at once.
    *   `llmStreamSemaphore`: This one is critical. LLM streaming is expensive. This semaphore has a smaller limit (`config.MaxConcurrentLLMStreams`) to prevent us from overwhelming the LLM service. It ensures only a few "heavy hitters" (like Thor or The Hulk) are active at any given moment.

A worker from the pool must first acquire a "slot" from `prepareSemaphore` before it begins processing.
```go
// This line blocks until a "slot" is free.
m.prepareSemaphore <- struct{}{}
go func(...) {
    // This defer ensures the "slot" is released when the worker is done.
    defer func() { <-m.prepareSemaphore }()
    ...
}()
```
Only the leader of a broadcast mission will attempt to acquire a slot from the `llmStreamSemaphore`.

### The De-Duplication Strategy: `singleflight` and the `StreamBroadcaster`

This is our ace in the hole, the core of our new efficiency model. It's how we handle identical, simultaneous requests.

*   **The Problem**: A "thundering herd." Multiple, identical requests arrive at once for data that isn't in the cache. Without a de-duplication strategy, we'd launch parallel operations for every single request, all doing the same redundant, expensive work.

*   **The Solution**: We combine `singleflight.Group` with our `StreamBroadcaster`. Think of it as setting up a secure press conference.

    1.  **The First Request (The Leader)**: When the first request for a specific topic (`cacheKey`) arrives, `m.sfGroup.Do()` allows it through. This request is now the **Leader**. Its job is to set up the press conference: it does the expensive preparation, creates a `StreamBroadcaster`, and starts the live feed (`initiateAndManageBroadcast`).

    2.  **Subsequent Requests (The Followers)**: Any other requests for the *same topic* that arrive while the Leader is working are put on hold by `singleflight.Group`. They don't do any work themselves. They simply wait for the Leader to establish the broadcast.

    3.  **Tuning In**: Once the Leader has set up the `StreamBroadcaster`, its `broadcastInfo` is shared with all the waiting Followers. Now, both the Leader and all the Followers call `broadcaster.Subscribe()` to get their own personal earpiece and "tune in" to the live feed. The `StreamBroadcaster` even has a `history` so that late-joiners get all the intel from the beginning.

This is a massive improvement. Instead of ten agents all trying to breach the same wall, one agent (the Leader) breaches it and then holds the door open for everyone else. The result of one expensive operation is shared live with many. Only the Leader is responsible for writing the final result to the cache, preventing redundant writes.

In short: `manager.go` uses concurrency to **structure** the work and parallelism to **execute** it, but its true genius lies in the `singleflight` and `StreamBroadcaster` combo, which ensures we do expensive work exactly once and share the results with ruthless efficiency.
