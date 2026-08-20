---
title: "Goroutines"
date: 2025-07-09
lastmod: 2026-07-09
draft: false
---

Goroutines get to the very heart of what makes Go so powerful for concurrent programming. As a Python programmer, you're used to concepts like threads, `asyncio`, and `multiprocessing`, and understanding how goroutines relate to them is key.

### What are Goroutines? (An Analogy for Python Programmers)

Imagine you're managing an office.

*   **Python `threading`:** You hire a few very qualified (but heavyweight) employees (OS Threads). However, a strict office rule (the Global Interpreter Lock or GIL) says only one employee can use the main office equipment (the Python interpreter) at a time for CPU-intensive tasks. They can wait for phone calls (I/O) simultaneously, but they can't do two calculations at once.
*   **Python `multiprocessing`:** To get around the GIL, you build entirely separate, identical office buildings (Processes). Each has its own equipment and staff. They can all work in parallel, but they are very expensive to build (high memory usage), and getting them to talk to each other requires a formal, slow courier service (inter-process communication).
*   **Python `asyncio`:** You have one, extremely disciplined employee (a single thread). You give them a long list of tasks. They work on one task until they have to wait for something (like a file to download). Instead of just waiting, they *immediately* put that task aside and pick up the next one on the list. They only come back to the first task when the file is ready. It's very efficient, but the employee has to be explicitly told when to switch tasks (using `await`).
*   **Go Goroutines:** You hire a huge team of incredibly cheap, lightweight interns (**goroutines**). They each only need a tiny desk and a notepad (a few KB of stack memory). You also have a brilliant office manager (**Go's Runtime Scheduler**) who supervises a small number of your best employees (OS Threads). The manager is constantly and automatically assigning interns to the employees. If an intern has to wait for a phone call (I/O), the manager instantly pulls them off the employee's desk and assigns a different intern who is ready to work. The manager can have multiple employees working on different interns in parallel on different CPU cores.

**In summary, Goroutines are:**

1.  **Lightweight:** They start with a tiny amount of memory and can grow if needed, unlike OS threads which have a large, fixed stack size. You can easily have hundreds of thousands or even millions of goroutines running.
2.  **Managed by Go, Not the OS:** The Go runtime scheduler multiplexes (schedules) many goroutines onto a small number of OS threads. This is much more efficient than having a 1:1 mapping of goroutines to OS threads.
3.  **Concurrent AND Parallel:** Because the scheduler can assign goroutines to different OS threads running on different CPU cores, your Go program can achieve true parallelism, unlike Python's GIL-limited threads.

They are **NOT** the same as Python workers. They are a much more fundamental, efficient, and integrated concurrency primitive. They feel a bit like `asyncio` tasks in their lightness but behave more like true threads in their ability to run in parallel, without the developer needing to manually `await` everywhere.

---

# Goroutines in This Codebase (`chatbot.Manager`)

The chatbot `Manager` is where all the long-lived goroutines are spawned. They are created once, in `NewManager()` (`chatbot/manager_core.go:100-338`), and run for the lifetime of the process (until `Shutdown()` at `chatbot/manager_core.go:342` tears them down).

Think of the Manager as the "office manager" from the analogy: it hires several distinct **pools** of interns, each pool specialised for a different kind of work, and it hands each incoming request to the right pool.

The pools and background goroutines that actually exist today are:

1.  **Cache worker pool** — serve cache hits instantly, bypassing the processing semaphore.
2.  **Normal request worker pool** — FIFO processing of full requests, bounded by a single `processingSemaphore`.
3.  **Priority request worker pool** — a fast-lane for cache-promoted requests.
4.  **Cache re-evaluation worker** — exactly one; promotes queued requests when their cache key gets populated.
5.  **Janitor** — periodic cleanup of timed-out / stale requests.
6.  **Async log writer** — non-blocking database log writes.
7.  **Bowl system** — replays/fans-out streamed events to attached pipes (and enables resume).

On top of these long-lived goroutines, individual requests spawn short-lived goroutines while they are processed (LLM streaming, parallel language detection, parallel tool execution). Those are covered at the end.

Everything the Manager owns is declared on the struct in `chatbot/manager_core.go:42-97`.

---

## 1. Cache Worker Pool (The Express Lane Team)

**Spawned:** `NewManager()` — `chatbot/manager_core.go:294-302`

**Run loop:** `func (cw *cacheWorker) run(ctx context.Context)` — `chatbot/manager.go:432`

**How many:** `cfg.TotalCacheWorkers`

**Lifespan:** Application lifetime.

```go
// chatbot/manager_core.go:294
for i := range cacheWorkerCount {
    worker := &cacheWorker{
        id:       i,
        manager:  m,
        stopChan: make(chan struct{}),
    }
    m.cacheWorkerPool[i] = worker
    go worker.run(ctx)
}
```

Each worker blocks on the buffered channel `cacheRequestChan chan types.SubmitRequestArgs` (`manager_core.go:80`). When a request arrives it:

1.  Skips it if it is the health-check probe or already cancelled.
2.  Calls `cw.manager.cacheFastLane.HandleCachedRequest(...)` (`manager.go:465`).
3.  On a **cache hit**, streams the cached answer directly.
4.  On a **cache miss**, calls `cw.manager.routeToNormalProcessing(request)` (`manager.go:475`) to hand it off to the normal path.

**Why this matters:** cache workers never touch the `processingSemaphore`. That is what keeps cache hits cheap and instant — they are a completely independent lane.

---

## 2. Normal Request Worker Pool (Full Processing, FIFO)

**Spawned:** `NewManager()` — `chatbot/manager_core.go:306-309`

**Run loop:** `func (m *Manager) normalRequestWorker(ctx context.Context)` — `chatbot/manager.go:841`

**How many:** `cfg.MaxConcurrentRequests`

**Lifespan:** Application lifetime.

```go
// chatbot/manager_core.go:306
normalWorkerCount := cfg.MaxConcurrentRequests
for range normalWorkerCount {
    go m.normalRequestWorker(ctx)
}
```

Each worker waits on the queue's "normal" signal channel and then dequeues in FIFO order:

```go
// chatbot/manager.go:841
func (m *Manager) normalRequestWorker(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():
            return
        case <-m.queueManager.GetNormalChannel():
            request, found := m.queueManager.DequeueRequestNormal()
            if found {
                if m.isRequestValid(request.RequestID) {
                    m.processRequest(ctx, *request)
                }
            }
        }
    }
}
```

`DequeueRequestNormal()` is an alias for `DequeueRequest()` (`chatbot/queue/manager.go:247` / `:285`), which pops the next FIFO request.

### The single processing semaphore

The key concurrency control lives in `processRequest` (`chatbot/manager.go:482`). Before doing any real work, the worker acquires **one** shared semaphore:

```go
// chatbot/manager.go:514
m.processingSemaphore <- struct{}{}                 // acquire (blocks if full)
request.SemaphoreWaitDurationSec = time.Since(semaphoreStart).Seconds()
...
m.executeTask(ctx, request, request.CacheKeyData)   // prepare, then hand off streaming
<-m.processingSemaphore                              // release
```

`processingSemaphore` is a buffered channel of capacity `cfg.MaxConcurrentRequests` (`manager_core.go:127`). This is a classic Go semaphore: sending into the channel is "acquire" and it blocks once the buffer is full; receiving is "release".

**What it actually bounds is the preparer stage, not the whole request.** The slot is released the moment `executeTask` returns — and `executeTask` returns as soon as it hands streaming off to a **detached goroutine** (`go m.runBoundedStream(...)`, `manager.go:642`), *not* when the stream finishes. So one slot covers *prepare + hand-off*, then is freed while the answer is still streaming on its own goroutine. Concretely, the preparer (`PrepareWithCacheKeyData`, `manager.go:609`) runs inline under the slot; streaming does not.

This makes the two stages **decoupled**, each with its own gate:

*   **Preparer stage** — bounded by `processingSemaphore` (cap `cfg.MaxConcurrentRequests`). At most this many requests are *preparing* at once.
*   **Streaming stage** — bounded separately by `llmStreamSemaphore` (cap `cfg.MaxConcurrentLLMStreams`), acquired inside the detached goroutine (see §8). A slow stream ties up an LLM-stream slot but **not** a preparer slot.

There is no separate leader/follower stage and no queue-jumping among normal requests — just these two independent gates.

There are two other semaphore-like fields on the Manager:

*   `llmStreamSemaphore chan struct{}` (cap `cfg.MaxConcurrentLLMStreams`, `manager_core.go:128`) — bounds concurrent **LLM** streaming. Every stream that calls the LLM is dispatched through `runBoundedStream` (`manager.go:780`), which acquires a slot before streaming and releases it when the stream ends. Both LLM dispatch sites go through it: the normal path (`executeTask`, `manager.go:642`) and the priority worker's regeneration fallback (`executeTaskImmediate`, `manager.go:767`). `HealthCheck()` also probes it (`manager.go:1471`) as a liveness check. It is a **separate gate from `processingSemaphore`**: `processingSemaphore` bounds the *preparer* stage (and is released once streaming is handed off to a detached goroutine — see §2 above), while `llmStreamSemaphore` bounds the concurrent LLM *streams* so a burst cannot stampede the provider into rate-limit errors. Cache fast-lane serving (`streamCachedResponse`) does **not** pass through it — replaying an answer from Redis does no LLM work and lives in its own resource slot.
*   `priorityRateLimiter chan struct{}` (cap 100, `manager_core.go:130`) — used by the priority fast-lane below, not by normal processing.

---

## 3. Priority Request Worker Pool (Cache-Promotion Fast-Lane)

**Spawned:** `NewManager()` — `chatbot/manager_core.go:316-319`

**Run loop:** `func (m *Manager) priorityRequestWorker(ctx context.Context)` — `chatbot/manager.go:895`

**How many:** `cfg.PriorityWorkerCount`

**Lifespan:** Application lifetime.

These workers listen on the queue's priority channel and handle requests that were **promoted** because a matching cache entry appeared while they were waiting (see the re-evaluation worker next). A promoted request is served **straight from the cache fast-lane** — the answer is already in Redis — and only regenerates via the LLM if the cache entry is somehow gone by the time the worker gets to it:

```go
// chatbot/manager.go:902
case requestID := <-m.queueManager.GetPriorityChannel():
    request := m.queueManager.DequeueRequestPromoted(requestID)
    if request != nil && m.isRequestValid(request.RequestID) {
        if m.cacheFastLane != nil &&
            m.cacheFastLane.HandleCachedRequestViaReevaluation(ctx, *request, request.CacheKeyData.CacheKey, logger) {
            // served from cache — no LLM
        } else {
            m.executeTaskImmediate(ctx, *request)   // cache miss → regenerate
        }
    }
```

`HandleCachedRequestViaReevaluation` streams the cached answer with no LLM call and no `processingSemaphore` — the common case for a promotion. The regeneration fallback, `executeTaskImmediate` (`chatbot/manager.go:648`), also deliberately does **not** take `processingSemaphore`; it uses the lightweight `priorityRateLimiter` (cap 100) to protect Redis from a stampede, and its LLM stream is bounded by `llmStreamSemaphore` (via `runBoundedStream`) like any other LLM stream:

```go
// chatbot/manager.go:652
m.priorityRateLimiter <- struct{}{}
defer func() { <-m.priorityRateLimiter }()
```

So a cache-promoted request skips the normal FIFO gate entirely — that is what "fast-lane" means here.

> **Why this path matters:** `PromoteForCache` used to remove a promoted request from its index maps *before* `DequeueRequestPromoted` looked it up by ID, so the lookup returned `nil` and the request was silently dropped in production. The fix (`chatbot/queue/manager.go`) hands the request off atomically — send to the priority channel first, then remove and stash it in a `promotedItems` map that `DequeueRequestPromoted` pops from — so a promoted request is never lost or orphaned.

---

## 4. Cache Re-evaluation Worker (The Background Optimizer)

**Spawned:** `NewManager()` — `chatbot/manager_core.go:285-286`

**Run loop:** `func (crw *ReevaluationWorker) Run(...)` — `chatbot/cache/worker.go:47`

**How many:** Exactly **1**.

**Lifespan:** Application lifetime.

```go
// chatbot/manager_core.go:285
m.cacheReevalWorker = cache.NewReevaluationWorker(m)
go m.cacheReevalWorker.Run(ctx, m.cacheNotificationChan)
```

It blocks on `cacheNotificationChan chan string` (`manager_core.go:85`). When some request finishes and writes a cache key, that key is sent down this channel. The worker then calls `ProcessCacheNotification` (`chatbot/cache/worker.go:73`), whose main job is:

```go
// chatbot/cache/worker.go:79
promotedCount := crw.manager.PromoteFromQueueForCache(cacheKey)
```

`PromoteFromQueueForCache` finds every request still sitting in the queue that maps to this cache key and pushes it onto the priority channel — where the **priority worker pool** (section 3) picks it up and serves it from cache. Net effect: a request that was queued behind slow work suddenly gets an instant cached answer the moment that answer becomes available.

This worker shuts down cleanly on `ctx.Done()` or via `Stop()`, which is made idempotent with a `sync.Once` (`chatbot/cache/worker.go:66`).

---

## 5. Janitor (Periodic Cleanup)

**Spawned:** `NewManager()` — `chatbot/manager_core.go:325` (`go m.janitor(ctx)`)

**Run loop:** `func (m *Manager) janitor(ctx context.Context)` — `chatbot/manager.go:1162`

**How many:** Exactly **1**.

**Lifespan:** Application lifetime.

A simple ticker loop driven by `cfg.JanitorInterval`:

```go
// chatbot/manager.go:1162
ticker := time.NewTicker(m.config.JanitorInterval)
for {
    select {
    case <-ticker.C:
        m.cleanupTimedOutRequests()
        m.cleanupOldQueuedRequests()
    case <-ctx.Done():
        return
    }
}
```

`cleanupTimedOutRequests` (`manager.go:1181`) sweeps `activeRequests` for entries that have overstayed their timeouts (cancelled-but-not-picked-up, stuck-in-queue, etc.) and reaps them. This is the housekeeping goroutine that keeps the in-memory maps from growing without bound.

---

## 6. Async Log Writer (Non-Blocking DB Writes)

**Spawned:** `NewManager()` — `chatbot/manager_core.go:332-333`

**Run loop:** `func (m *Manager) asyncLogWorker(ctx context.Context)` — `chatbot/manager_core.go:384`

**How many:** Exactly **1** (tracked by a `sync.WaitGroup` for clean shutdown).

**Lifespan:** Until `logQueue` is closed during `Shutdown()`.

```go
// chatbot/manager_core.go:332
m.logWg.Add(1)
go m.asyncLogWorker(ctx)
```

The worker drains `logQueue chan types.LogDataForDB` (`manager_core.go:95`, buffered to 100) and writes chat logs to ArangoDB off the hot path, so `submitRequest` never blocks on a database round-trip:

```go
// chatbot/manager.go:387
for logData := range m.logQueue {
    // skip if the row already reached a terminal cancelled/errored state,
    // otherwise write the log with a background context
    m.arangoStore.CreateOrUpdateChatLog(context.Background(), logData)
}
```

Shutdown is graceful: `Shutdown()` (`manager_core.go:342`) closes `logQueue`, then waits on `logWg` (with a 10s timeout) so pending logs get flushed before exit.

---

## 7. The Bowl System (Event Replay & Fan-Out)

**Owner:** `bowlManager *bowl.Manager` — package `chatbot/bowl` (constructed at `manager_core.go:264-267` when `cfg.UseBowl` is true).

The "bowl" is a per-request buffer (`ResponseBowl`, `chatbot/bowl/bowl.go:36`) that accumulates every streamed event. It is what lets a client disconnect and later **resume** a response, and lets more than one consumer read the same response.

> Note on terminology: the bowl code uses the word **broadcast** for its *own* replay / fan-out concept (duplicating events to attached pipes). That is legitimate and current — it is unrelated to any older dispatch design.

Two kinds of goroutines live here:

*   **Bowl janitor** — `Manager.Start()` (`chatbot/bowl/manager.go:131`) launches one background goroutine that ticks on a cleanup interval and calls `m.cleanup()` to expire old bowls (TTL-based).
*   **Per-pipe replay goroutine** — every time a consumer attaches via `CreatePipe` (`chatbot/bowl/bowl.go:194`), the bowl spawns `go bowl.replayEvents()` (`bowl.go:217`). That goroutine copies the bowl's accumulated events into the new pipe (catching a late/reconnecting client up), then keeps forwarding live events until the response completes.

The Manager creates pipes through `CreateStreamPipe` / `CreateResumePipe` (`chatbot/bowl/manager.go:244` / `:280`), so a fresh stream and a resume both flow through this same replay machinery.

---

## 8. Per-Request Goroutines (Short-Lived)

While a single request is being processed inside `executeTask` / `executeTaskImmediate`, a few extra goroutines are spawned and then torn down:

*   **LLM streaming** — `go m.runBoundedStream(func() { m.GetStreamer().Stream(clientChan, preparedData, logCtx) })` (`chatbot/manager.go:642`). The streamer runs on its own goroutine and pushes tokens/events to the client channel (and, when bowls are enabled, into the bowl). `runBoundedStream` holds an `llmStreamSemaphore` slot for the stream's lifetime, so no more than `cfg.MaxConcurrentLLMStreams` LLM streams run at once.
*   **Parallel language detection** — `executeTask` kicks off language detection in a parallel goroutine (`chatbot/manager.go:548`) when no explicit language was supplied, so it overlaps with other preparation instead of adding a sequential 2-3s delay.
*   **Parallel tool execution** — when a plan calls multiple tools, `ExecuteToolsParallel` (`tools/toolcore/pipeline/execution/parallel.go:14`) fans them out: one `go func(...)` per tool spec, coordinated with a `sync.WaitGroup`, results collected over a channel. This is the classic Go fan-out/fan-in pattern applied to tool calls.

These are the goroutines that make a *single* request fast; the pools in sections 1-3 are what let *many* requests run at once.

---

## Goroutine Lifecycle & Concurrency Summary

| Goroutine | Count | Lifespan | Gate | Purpose |
|-----------|-------|----------|------|---------|
| Cache worker | `cfg.TotalCacheWorkers` | Application | none | Instant cache hits |
| Normal request worker | `cfg.MaxConcurrentRequests` | Application | `processingSemaphore` (single, shared) | Full FIFO processing |
| Priority request worker | `cfg.PriorityWorkerCount` | Application | `priorityRateLimiter` (cap 100) | Serve cache-promoted requests |
| Cache re-eval worker | 1 | Application | none | Promote queued requests on cache fill |
| Janitor | 1 | Application | none | Reap timed-out / stale requests |
| Async log writer | 1 | Until `logQueue` closed | none | Non-blocking DB log writes |
| Bowl janitor | 1 (if `UseBowl`) | Application | none | Expire old bowls |
| Bowl replay | 1 per attached pipe | Until response completes | none | Replay + live fan-out to a consumer |
| LLM stream | 1 per active request | Until stream ends | `llmStreamSemaphore` (cap `cfg.MaxConcurrentLLMStreams`) | Stream the answer |
| Parallel tool exec | 1 per tool in a plan | Until tool returns | none | Fan-out tool calls |

**The one number that governs backpressure for the preparer stage is `cfg.MaxConcurrentRequests`.** It sizes both the normal worker pool *and* the `processingSemaphore` buffer, so no more than that many requests are *preparing* at once. Once a request finishes preparing it hands streaming off to a detached goroutine and frees its slot — so the streaming stage runs independently, bounded separately by `cfg.MaxConcurrentLLMStreams` (`llmStreamSemaphore`). Cache hits (cache workers) and cache-promoted requests (priority workers) deliberately sidestep the preparer gate, which is why they feel instant.

### Key takeaways for a Python programmer

*   A buffered `chan struct{}` used as a **semaphore** (`processingSemaphore`, `priorityRateLimiter`) is Go's idiomatic equivalent of `threading.Semaphore` / `asyncio.Semaphore` — "acquire" is a send, "release" is a receive.
*   Workers are just goroutines looping on a `select` over channels; `<-ctx.Done()` is how they are told to stop — the equivalent of a cancellation token.
*   Fan-out/fan-in (`ExecuteToolsParallel`) — launch N goroutines, wait on a `sync.WaitGroup`, collect over a channel — is the Go way to do what you might reach for `concurrent.futures` or `asyncio.gather` to do in Python.
*   Graceful shutdown is explicit: closing a channel (`logQueue`) and `WaitGroup.Wait()` drains in-flight work before the process exits.
