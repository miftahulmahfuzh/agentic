---
title: "Request Lock"
date: 2025-08-02
draft: false
---

# Concurrency and Lock Strategy

## 1. Overview: The Need for Speed and Safety

The chatbot manager is a highly concurrent system. Multiple requests are processed in parallel across different stages (preparation, streaming), while background tasks like the `janitor` perform system-wide maintenance. This is not *12 Angry Men* where everyone waits their turn to speak; this is the trading floor from *The Wolf of Wall Street*—chaotic, fast, and every action must be precise.

To prevent race conditions where multiple goroutines corrupt shared data (like maps, which are not intrinsically thread-safe), we use locks. However, using a single, global lock would create a massive performance bottleneck. Instead, the manager employs a **fine-grained locking strategy** with two distinct mutexes, each with a specific responsibility. This minimizes lock contention and maximizes throughput.

## 2. The Two-Lock Strategy: Why Not Just One?

Using a single lock for all shared resources is a critical design flaw. It creates a single point of contention where unrelated operations block each other. For example, a fast check on cache coordination should not be blocked by a slow, system-wide cleanup task.

Our strategy is based on the principle of **lock granularity**: separate, unrelated resources are protected by separate locks. Think of it like a heist crew: you have one lock on the main vault (`requestsLock`) and a separate, simpler lock on the communications equipment (`cachingRequestsLock`). Cracking one doesn't require waiting for the other.

This separation ensures that locks are held for the shortest possible duration and only block other operations that truly conflict.

---

## 3. Lock #1: `requestsLock`

### Purpose and Scope

*   **Type**: `sync.RWMutex`
*   **Responsibility**: The "Vault Lock." It guards the core state and lifecycle of every active request in the system.
*   **Protected Data**:
    *   `activeRequests (map[string]*types.RequestStream)`: The central registry of all requests currently being processed or queued.
    *   `cancellableStreams (map[string]context.CancelFunc)`: The map of cancellation functions for stopping active requests.

This lock is the primary guardian of a request's journey through the system, from submission to cleanup.

### Usage Breakdown

| Function / Goroutine | Operation | Lock Type Used | Rationale |
| :--- | :--- | :--- | :--- |
| **`SubmitRequest`** | Adds a new request to `activeRequests`. | **Write Lock (`.Lock()`)** | Modifies the map. Exclusive access is required. |
| **`prepareWorker`** | Updates a request's state and adds its `cancelFunc`. | **Write Lock (`.Lock()`)** | Modifies data in both maps. Exclusive access is mandatory. |
| **`streamWorker`** | Reads `activeRequests` to see if the request still exists. | **Read Lock (`.RLock()`)** | Read-only check. Allows multiple stream workers to proceed concurrently. |
| **`cleanupRequest`** | Deletes a request from `activeRequests` and `cancellableStreams`. | **Write Lock (`.Lock()`)** | Modifies both maps. This is the final write operation in a request's lifecycle. |
| **`janitor`** | Reads `activeRequests` to find timed-out requests. | **Read Lock (`.RLock()`)** | Iterating over the map is a read operation. |
| **`janitor` (Cleanup Phase)**| Calls `cleanupRequest` which acquires a write lock. | **Write Lock (`.Lock()`)** | The cleanup itself is a write operation requiring an exclusive lock. |
| **`GetRequestResultStream`** | Reads `activeRequests` to find the request's stream channels. | **Read Lock (`.RLock()`)** | Read-only check. Allows multiple clients to poll for their results simultaneously. |
| **`CancelStream`** | Reads `cancellableStreams` to find the cancel function. | **Read Lock (`.RLock()`)** | A read-only lookup. After retrieval, the function is called outside the lock. |

---

## 4. Lock #2: `cachingRequestsLock`

### Purpose and Scope

*   **Type**: `sync.RWMutex`
*   **Responsibility**: The "Coordinator Lock." Its sole purpose is to manage cache-write coordination.
*   **Protected Data**:
    *   `cachingRequestsMap (map[string]string)`: A map that assigns one specific request ID the responsibility of writing to the Redis cache when multiple identical requests are processed simultaneously.

This lock prevents a "cache stampede" where dozens of identical requests all try to write the same key-value pair to Redis. It ensures only the designated "primary worker" performs the cache write.

### Usage Breakdown

| Function / Goroutine | Operation | Lock Type Used | Rationale |
| :--- | :--- | :--- | :--- |
| **`prepareRequest`** | Checks `cachingRequestsMap` and potentially adds an entry. | **Write Lock (`.Lock()`)** | A short, atomic check-and-set operation to determine if the current worker is the primary for a given cache key. A write lock guarantees atomicity. |
| **`cleanupRequest`** | Removes the entry from `cachingRequestsMap` if this request was the primary worker. | **Write Lock (`.Lock()`)** | A short, surgical write operation to release the caching responsibility. |

## 5. Summary and Guidelines

| Lock Name | Analogy | Protected Data | Scope / Contention |
| :--- | :--- | :--- | :--- |
| **`requestsLock`** | The Bank Vault | Request lifecycle state (`activeRequests`, `cancellableStreams`) | High-traffic, broader scope. Protects the core existence of requests. |
| **`cachingRequestsLock`**| The Getaway Car Keys | Cache write coordination (`cachingRequestsMap`) | Low-traffic, surgical scope. Protects a specific, short-lived coordination task. |

### Rules for Development

1.  **Know Which Lock to Use**: Understand if you are interacting with the request lifecycle (`requestsLock`) or cache coordination (`cachingRequestsLock`).
2.  **Use the Correct Lock Type**: Use `RLock` for reads, `Lock` for writes.
3.  **Keep Lock Duration Minimal**: Never perform slow operations (I/O, database calls, LLM calls) while holding a lock. Acquire the lock, access the map, and release it.
4.  **Use `defer`**: Always `defer` the `Unlock()` call immediately after acquiring a lock to prevent deadlocks.
