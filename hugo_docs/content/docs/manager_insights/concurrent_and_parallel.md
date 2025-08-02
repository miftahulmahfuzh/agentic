---
title: "Concurrent & Parallel"
date: 2025-08-02
draft: false
---

# Concurrency & Parallelism: The Ops Center of `manager.go`

Welcome to the mission briefing. Our `manager.go` file is the central nervous system of our chatbot operation, much like The Continental from *John Wick* or the IMF headquarters from *Mission: Impossible*. It needs to handle a flood of incoming requests from agents (users) all over the world. To do this without melting down, it masterfully employs the arts of **concurrency** and **parallelism**.

## Concurrency: Managing Multiple Missions (like Ethan Hunt)

Concurrency is about structuring our code to handle many things at once, even if we only have one CPU core doing the work. It's about switching between tasks efficiently so that no single task blocks the entire system.

In `manager.go`, concurrency is achieved primarily through **Goroutines** and **Channels**.

### The Tools of Concurrency:

1.  **Goroutines (`go func(...)`)**: Every time you see `go ...`, we're essentially telling one of our agents to start a new, independent task. It could be preparing a request, streaming a response, or the janitor cleaning up old files. They can all run without waiting for each other to finish.

2.  **Channels (`chan`)**: This is our secure communication line. How does Ethan Hunt get new intel from Benji? Through his earpiece. In Go, channels are those earpieces.
    *   `requestQueue`: This is the "mission assignment" desk. New requests arrive here and wait to be picked up.
    *   `preparedQueue`: This is the hand-off. The intel team (`prepareWorker`) has assembled the "briefcase" (`PreparedRequestData`) and passes it to the field team (`streamWorker`) for the main operation.
    *   This prevents goroutines from stepping on each other's toes, avoiding the chaos you'd get if the entire *Suicide Squad* tried to use one gun. It's orderly and safe.

3.  **The `select` Statement**: This is the system's "situational awareness." A `select` block allows a goroutine to listen to multiple channels at once. It's like Batman in *The Dark Knight* watching dozens of monitors in his sonar-vision room, waiting for a signal.
    *   The `janitor` uses `select` to wait for either its next cleaning interval (`ticker.C`) or a shutdown signal (`ctx.Done()`).
    *   The worker managers use `select` to wait for a new request *or* a shutdown signal.

4.  **The `for...range` Loop on a Channel: The Assembly Line**: This is how we process a stream of work. Unlike a `for` loop over a static list, a `for...range` on a channel will **block and wait** for the next item to arrive. It's the assembly line in *Breaking Bad*: one goroutine (Walter) is "cooking" and putting items on the belt (`internalStreamChan <- event`), and the `for` loop (Jesse) is on the other end, picking each item off the belt as it arrives. The loop only ends when the producer closes the channel, signaling the end of the production run. This is the core mechanism that makes real-time streaming possible.

5.  **`sync.RWMutex`: The Consigliere**: The `activeRequests` map is our "family business" ledger. Multiple goroutines need to read from it, and some need to write to it. An uncoordinated mob would lead to disaster. The `sync.RWMutex` is our Tom Hagen from *The Godfather*.
    *   `m.requestsLock.RLock()`: Many people can go to Tom at once to **ask** what the plan is (a read lock). This is fast and efficient.
    *   `m.requestsLock.Lock()`: But only **one** person can go into the room with the Don to **change** the plan (a write lock). All others must wait until the meeting is over.
    *   This primitive protects our shared data from being corrupted by simultaneous writes, ensuring the integrity of our operation.

6.  **`context.Context` and `cancel()`: The Kill Switch**: Every operation that might take time (API calls, LLM streams) is given a `context`. This context is our kill switch, like the neck bombs from *Suicide Squad*. When a request is cancelled or times out, we call its `cancel()` function. This sends a signal down through the `ctx.Done()` channel to every goroutine working on that request. They see the signal, stop what they're doing, and clean up. It's how we tell an agent, "Mission aborted. Get out now." No hesitation, no wasted resources.

7.  **`sync.WaitGroup`: The Rendezvous Point**: In `streamResponse`, when a tool that streams its own output is called (like `frequently_asked`), it runs in its own goroutine. The main goroutine needs to wait for the tool to finish its work completely before it can proceed with cleanup. A `sync.WaitGroup` is the rendezvous point, like in *Ocean's Eleven*. Danny Ocean tells the team (`wg.Add(1)`), and he waits at the exit (`wg.Wait()`) until every member has done their job and signaled they're clear (`defer wg.Done()`). This ensures perfect synchronization.

The entire system is *concurrently* handling queuing, preparation, streaming, cancellation, and cleanup using these specialized tools.

### The "Janitor": The Cleaner

The `janitor` goroutine is our Mike Ehrmantraut from *Breaking Bad* or Winston from *John Wick*. It's a background process that runs periodically (`time.NewTicker`) to clean up messes. It finds requests that have been stuck in the queue too long ("timed out in queue") or are taking too long to process ("timed out during processing"). It then triggers their kill switch (`cancelFunc()`) and removes them from the active list. No loose ends. No witnesses.

---

## Parallelism: Assembling the Crew (like The Avengers)

Parallelism is when we take our concurrent design and run it on a machine with multiple CPU cores. Now, multiple tasks aren't just being *managed* at once; they are *executing* at the exact same time.

In `manager.go`, this is controlled by our **Worker Pools, Semaphores, and the Single-Flight Group**. We don't want to unleash an infinite number of Hulks on our system; that would be chaos. We need to control our resources.

### The Tools of Parallelism:

1.  **Worker Pools (`prepareWorkerManager`, `streamWorkerManager`)**: Instead of one agent doing everything, we have a team. These managers listen to their respective queues and dispatch workers to handle tasks *in parallel*, up to a certain limit.

2.  **Semaphores (`chan struct{}`)**: This is our resource management, our "Nick Fury" deciding who gets deployed. A semaphore is a channel used to limit the number of goroutines that can access a resource simultaneously.
    *   `prepareSemaphore`: Its size (`config.MaxConcurrentRequests`) determines how many requests can be in the "preparation" stage at the same time. This is like having the *Fast & Furious* family's tech crew (Tej, Ramsey) all working on different hacks at once.
    *   `llmStreamSemaphore`: This one is critical. LLM streaming is expensive. This semaphore has a smaller limit (`config.MaxConcurrentLLMStreams`) to prevent us from overwhelming the LLM service or our own server. It ensures only a few "heavy hitters" (like Thor or The Terminator) are active at any given moment.

When a request arrives in `prepareWorkerManager`, it must first acquire a "slot" from `prepareSemaphore`. This is how we achieve true parallelism.
```go
// This line blocks until a "slot" is free.
m.prepareSemaphore <- struct{}{}
go func(...) {
    // This defer ensures the "slot" is released when the worker is done.
    defer func() { <-m.prepareSemaphore }()
    ...
}()
```

### The Cache Stampede Defense: `singleflight`

This is our ace in the hole. The `prepareRequest` function uses a `singleflight.Group` to prevent a "thundering herd" scenario.

*   **The Problem**: Multiple, identical requests arrive simultaneously for data that isn't in the cache. Without `singleflight`, we'd launch parallel operations for every single request, all doing the same redundant, expensive work.
*   **The Solution**: The `singleflight.Group` is our gatekeeper. When the first request for a specific `cacheKey` arrives, it's allowed through to execute the expensive `doExpensivePreparation` function. Any other requests for the *same key* that arrive while the first is still running are put on hold. They don't start their own work; they simply wait. Once the first request completes, its result is shared with all the waiting requests.

It's like in *Mission: Impossible*—the first agent through the laser grid (`doExpensivePreparation`) disables the trap, and the rest of the team (`the waiting goroutines`) can just walk right through.

This is implemented with `m.sfGroup.Do(cacheKey, ...)` and is the reason the core logic was moved into the `doExpensivePreparation` function. Furthermore, the `cachingRequestsMap` (protected by its own `RWMutex`) and the `ShouldCache` flag in `PreparedRequestData` ensure that only the *first* agent—the one who did the work—is responsible for writing the result to the Redis cache. The others get the data but don't create unnecessary writes.

In short: `manager.go` uses concurrency to **structure** the work and parallelism to **execute** it, just like a master strategist planning a mission and then deploying the perfect team to get it done.
