---
title: "Request Lock"
date: 2025-07-04
lastmod: 2026-07-09
draft: false
---

## 1. Overview: The Need for Speed and Safety

The chatbot manager is a highly concurrent system. Multiple requests are processed in parallel across different stages (cache fast-lane, normal worker pool, priority promotion, streaming), while background tasks like the `janitor` and the `cache re-evaluation worker` perform system-wide maintenance. This is not *12 Angry Men* where everyone waits their turn to speak; this is the trading floor from *The Wolf of Wall Street*—chaotic, fast, and every action must be precise.

To prevent race conditions where multiple goroutines corrupt shared data (like maps, which are not intrinsically thread-safe), we use locks. However, using a single, global lock would create a massive performance bottleneck. Instead, the manager employs a **fine-grained locking strategy** with **two distinct mutexes**, each with a specific responsibility. This minimizes lock contention and maximizes throughput.

## 2. The Two-Lock Strategy: Separation of Concerns

Using a single lock for all shared resources is a critical design flaw. It creates a single point of contention where unrelated operations block each other. For example, a hot poll on the active-request registry should not be blocked by a slow janitor sweep over the cache re-evaluation tracking map.

Our strategy is based on the principle of **lock granularity**: separate, unrelated resources are protected by separate locks. Think of it like a heist crew with two independent vaults:

1. **`requestsLock`** - The main vault (active request lifecycle)
2. **`queuedRequestsLock`** - The intelligence archive (cache re-evaluation tracking)

Cracking one doesn't require waiting for the other. This separation ensures that locks are held for the shortest possible duration and only block operations that truly conflict.

---

## 3. Lock #1: `requestsLock`

**File:** `chatbot/manager_core.go:63`

### Purpose and Scope

*   **Type**: `sync.RWMutex`
*   **Responsibility**: The "Main Vault Lock." Guards the core state and lifecycle of every active request. This is the heavily-used lock—it is acquired on nearly every hot-path operation.
*   **Protected Data**:
    *   `activeRequests (map[string]*types.RequestStream)` (`manager_core.go:61`): Central registry of all requests (queued, processing, streaming, or waiting for client pickup), and the mutable per-request state fields inside each `RequestStream` (e.g. `State`, `LastStateChange`, `Progress`, `PersistChannel`).
    *   `cancellableStreams (map[string]*CancellableStreamItem)` (`manager_core.go:62`): Per-request cancellation functions, keyed by request ID. Note that `RequestStream.RequestContext` (`types/models.go:156`) also carries an individual request context; the `cancellableStreams` map holds the paired `CancelFunc` plus the owning `UserID`.

### The Common Locking Helpers

Most write-side state mutations funnel through **`withRequestStateLock`** (`manager.go:31`), a helper that takes the write lock, looks up the holder in `activeRequests`, and applies an update closure. This centralizes the "lock → mutate one holder → unlock" pattern so callers like `UpdateRequestProgress`, `SetToolsInformation`, and `SetSources` don't each re-implement it.

Two accessors expose the raw mutex for components that live outside the `chatbot` package (e.g. the cache re-evaluation worker): **`GetRequestsLock`** (`wrappers.go:81`) and **`GetRequestLock`** (`adapters_manager.go:212`). Both return `&m.requestsLock`. Direct use is discouraged—prefer the thread-safe methods below—but the worker needs it to read `activeRequests` under the same lock.

### Usage Breakdown

| Function / Location | Operation | Lock Type | Rationale |
| :--- | :--- | :--- | :--- |
| **`submitRequest`** (manager.go:313) | Register new `RequestStream` in `activeRequests` + `cancellableStreams` | **Write** | Map insertion |
| **`withRequestStateLock`** (manager.go:31) | Mutate one holder's state fields (used by `UpdateRequestProgress`, `SetToolsInformation`, `SetSources`) | **Write** | Modifies holder state |
| **`SetRequestState`** (adapters_manager.go:83) | Update `State` + `LastStateChange` | **Write** | Modifies holder state |
| **`SetCancellableStream`** (adapters_manager.go:101) | Store/refresh cancel func in `cancellableStreams` | **Write** | Map modification |
| **`CleanupRequest`** (adapters_manager.go:158) | Fire cancel, close persist channel, delete from both maps | **Write** | Final lifecycle operation |
| **`PurgeActiveRequest`** (manager.go:1250) | Delete from both maps for pre-connection cancel/resubmit | **Write** | Map deletion |
| **`ResumeRequest` placeholder insert** (main_handlers.go:858) | Insert status-only placeholder when no live entry exists | **Write** | Map insertion |
| **`GetActiveRequest`** (adapters_manager.go:34) | Look up a holder by ID | **Read** | Read-only lookup, concurrent safe |
| **`GetActiveRequestOwner`** (adapters_manager.go:59) | Zero-DB owner lookup for `/chat/status` | **Read** | Read-only lookup |
| **`IsRequestCancelled`** (adapters_manager.go:71) | Check holder `State == StateCancelled` | **Read** | Read-only check |
| **`GetCancellableStream`** (adapters_manager.go:135) | Fetch cancel func | **Read** | Read-only lookup |
| **`GetActiveRequests`** (adapters_manager.go:193) | Copy the map for monitoring | **Read** | Snapshot copy |
| **`getRequestResultStream`** (manager.go:958) | Find stream channels for client pickup | **Read** | Concurrent client polls |
| **`isRequestValid`** (manager.go:893) / **`IsRequestProcessing`** (manager.go:918) | State validation | **Read** | Read-only check |
| **`cleanupTimedOutRequests`** (janitor) (manager.go:1182) | Scan for timed-out requests, collect under lock, then `CleanupRequest` | **Read** (then Write via `CleanupRequest`) | Map iteration under lock |
| **`IsRequestStillQueued`** (cache re-eval worker) (cache/worker.go:121) | Check holder still in queued/early state before promotion | **Read** (via `GetRequestsLock`) | State validation |

---

## 4. Lock #2: `queuedRequestsLock`

**File:** `chatbot/manager_core.go:87`

### Purpose and Scope

*   **Type**: `sync.RWMutex`
*   **Responsibility**: The "Intelligence Archive Lock." Manages cache re-evaluation tracking. Low-traffic compared to `requestsLock`—it is touched only when a request is queued, when the janitor sweeps stale entries, and when the cache re-evaluation worker looks for promotion candidates.
*   **Protected Data**:
    *   `queuedRequests (map[string]types.SubmitRequestArgs)` (`manager_core.go:86`): Maps request IDs to full request args for cache pattern matching.

This lock enables the cache re-evaluation system. When a cache key is populated, the re-evaluation worker scans this map to find queued requests matching the key, then promotes them to the cache fast-lane. The map's helper functions live outside the `chatbot` package and receive the map and `&m.queuedRequestsLock` as parameters (see `cache/notifications.go` and `helpers/cleanup.go`); the manager wraps them in `wrappers.go`.

### Usage Breakdown

| Function / Location | Operation | Lock Type | Rationale |
| :--- | :--- | :--- | :--- |
| **`AddToQueuedRequests`** (cache/notifications.go:29) | Add request args to tracking map (wrapped by `m.addToQueuedRequests`, wrappers.go:30; called from submit path, manager.go:404) | **Write** | Map insertion |
| **`CleanupOldQueuedRequests`** (helpers/cleanup.go:21) | Remove stale entries past `QueueTimeout` (wrapped by `m.cleanupOldQueuedRequests`, wrappers.go:62; called by the janitor, manager.go:1171) | **Write** | Cleanup / map deletion |
| **`GetQueuedRequestsWithCacheKey`** (cache/notifications.go:38) | Scan for requests matching a cache key (wrapped by wrappers.go:74; called by the cache re-eval worker, cache/worker.go:89) | **Read** | Pattern-matching scan, concurrent safe |
| **`GetIncompleteRequestsByConversationFromBowl`** (manager.go:1317) | Fallback lookup of a queued request during resume | **Read** | Read-only lookup |

**Key insight:** This map is independent from the priority queue (`chatbot/queue/manager.go`). The queue handles dispatch ordering, while this map enables cache-based promotion opportunities.

## 5. Summary and Guidelines

| Lock Name | Analogy | Protected Data | Scope / Contention |
| :--- | :--- | :--- | :--- |
| **`requestsLock`** | The Main Vault | Request lifecycle state (`activeRequests`, `cancellableStreams`) | High-traffic, broad scope. Protects the core existence and state of all active requests. |
| **`queuedRequestsLock`** | The Intelligence Archive | Cache re-evaluation tracking (`queuedRequests`) | Low-traffic, background scope. Enables cache-based promotion opportunities. |

### Rules for Development

1.  **Know Which Lock to Use**: Understand which resource you're accessing:
    - Request lifecycle operations (registry, state, cancellation) → `requestsLock`
    - Cache re-evaluation tracking → `queuedRequestsLock`

2.  **Use the Correct Lock Type**: Use `RLock` for reads, `Lock` for writes.

3.  **Keep Lock Duration Minimal**: Never perform slow operations (I/O, database calls, LLM calls) while holding a lock. Acquire the lock, access the map, and release it immediately. The janitor demonstrates this: it collects timed-out holders under `RLock`, releases, then performs cleanup (which re-locks) outside the scan.

4.  **Use `defer`**: Prefer `defer` on the `Unlock()`/`RUnlock()` call to prevent deadlocks. Where a function must release early (e.g. `getRequestResultStream` branching on a status placeholder), unlock explicitly on every path.

5.  **Avoid Lock Ordering Issues**: If you must acquire both locks, always use the same order: `requestsLock` → `queuedRequestsLock`. The current design avoids this by ensuring operations rarely need both locks simultaneously.
