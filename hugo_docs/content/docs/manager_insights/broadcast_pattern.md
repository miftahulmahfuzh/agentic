---
title: "Broadcast Pattern"
date: 2025-08-13
draft: false
---

# Architecture Analysis: From Dual Worker Pools to a Broadcast Pattern

[The Age of Sauron](https://miftahulmahfuzh.github.io/agentic/docs/manager_insights/sauron/) | [Implicit Decoupling](https://miftahulmahfuzh.github.io/agentic/docs/manager_insights/implicit_decoupling/)

This document details the architectural evolution of the chatbot system, moving from a sequential, dual-pool pipeline to a highly efficient, single-pool model that leverages a broadcast pattern for end-to-end request deduplication.

### Executive Summary

The initial question was: **"Is it true that we don't have a separate worker pool anymore?"**

The answer is nuanced but trends towards **yes**. The old architecture featured two distinct, sequential worker pools, each managed by its own semaphore (`prepareSemaphore` and `llmStreamSemaphore`). The new architecture consolidates this into a **single, unified request worker pool** controlled by the `prepareSemaphore`.

However, the critical `llmStreamSemaphore` **still exists and functions as a crucial concurrency gate**. The key difference is that it's no longer tied to a separate pool of workers. Instead, it's a resource that only "leader" requests (the first unique request) will acquire from within the main worker pool. This change from a rigid pipeline to a dynamic, on-demand resource acquisition model is the core of the new architecture's efficiency.

The new design successfully implements end-to-end deduplication, ensuring that identical, concurrent user queries result in only one expensive LLM operation, whose result is then broadcast to all interested clients.

---

## 1. The Old Architecture: Sequential Dual-Pool Pipeline

The original architecture was a classic multi-stage producer-consumer pattern. It was designed to separate the lighter preparation work from the heavier, more expensive LLM streaming work.

### Concept & Flow

The lifecycle of a request was strictly sequential, passing through two distinct queues and two corresponding worker pools.

**Flow:** `Submit -> Request Queue -> Preparation Pool -> Prepared Queue -> Streaming Pool -> Client`

1.  **Submission**: `SubmitRequest` places a new request into the `requestQueue`.
2.  **Preparation Pool**:
    *   The `prepareWorkerManager` loop pulls requests from the `requestQueue`.
    *   It acquires a slot from `prepareSemaphore` (limited by `MaxConcurrentRequests`).
    *   It spins up a goroutine to execute `preparer.Prepare`. This step included fetching history, running tool selection, and formatting the final prompt.
    *   The `Preparer` itself used a `singleflight.Group` to prevent re-doing the *expensive preparation work* for identical requests that were already in-flight.
    *   Upon completion, the `PreparedRequestData` is pushed into the `preparedQueue`.
3.  **Streaming Pool**:
    *   The `streamWorkerManager` loop pulls prepared data from the `preparedQueue`.
    *   It acquires a slot from the much more restrictive `llmStreamSemaphore` (limited by `MaxConcurrentLLMStreams`).
    *   It spins up a goroutine to execute `streamer.Stream`, which handles the actual LLM call and streams the response back.



### Limitations and Inefficiencies

While this design correctly isolated expensive and cheap tasks, it had a significant flaw in handling duplicate requests:

*   **Resource Inefficiency**: Imagine 10 identical requests arrive simultaneously. All 10 would try to acquire a slot from the `prepareSemaphore`. Even though the internal `singleflight` in the `Preparer` would ensure the work was only done once, **10 preparation worker slots were still occupied**. The 9 "follower" requests would simply block, waiting for the leader to finish, before moving on.
*   **No End-to-End Deduplication**: After the leader finished preparation, all 10 requests (one with data, nine with shared data) would be placed in the `preparedQueue`. They would then **each have to wait their turn to acquire a slot from the `llmStreamSemaphore`**. The system would perform the exact same LLM call 10 times, wasting significant time, compute resources, and API costs.
*   **Rigid Pipeline**: The separation was rigid. A request could not bypass the preparation queue, and every request had to compete for a streaming slot, even if its result was identical to another's.

---

## 2. The New Architecture: Single-Pool with Broadcast Pattern

The new architecture dismantles the sequential pipeline in favor of a more dynamic and intelligent system. It uses a single entry-point worker pool and leverages `singleflight` at the highest level to manage a broadcast pattern.

### Concept & Flow

The new model determines if a request is a "Leader" or a "Follower" at the earliest possible moment. Only the leader performs the expensive work.

**Flow:** `Submit -> Request Queue -> Request Pool -> Singleflight Gate`
*   **If Leader:** `Prepare -> Acquire LLM Slot -> Stream -> Broadcast to all Subscribers`
*   **If Follower:** `(Instantly) Subscribe to Leader's Existing Broadcast -> Receive Stream`

1.  **Consolidated Worker Pool**:
    *   The `NewManager` now only starts one primary worker manager: `requestWorkerPool`. This pool pulls from the `requestQueue` and is limited by `prepareSemaphore` (`MaxConcurrentRequests`).
    *   The intermediate `preparedQueue` and the `streamWorkerManager` are completely removed.
2.  **The Singleflight Gatekeeper**:
    *   Inside the `requestWorkerPool`, the `processAndRouteRequest` function is the new brain.
    *   It generates a `cacheKey` based on the conversational context.
    *   It immediately calls `m.sfGroup.Do(cacheKey, ...)`. This is the critical gate.
3.  **The Leader's Journey**:
    *   The *first* request for a given `cacheKey` becomes the **Leader**.
    *   It enters the `singleflight` function block.
    *   It creates a new `StreamBroadcaster`.
    *   It launches a single goroutine, `initiateAndManageBroadcast`, to handle the entire streaming lifecycle.
    *   **Crucially, inside `initiateAndManageBroadcast`, the leader must acquire a slot from `llmStreamSemaphore` before calling the LLM.** This preserves the vital concurrency limit on the most expensive resource.
    *   As the leader receives tokens from the `Streamer`, it broadcasts them to all its subscribers.
4.  **The Follower's Shortcut**:
    *   Any subsequent request with the same `cacheKey` that arrives while the leader is active becomes a **Follower**.
    *   `sfGroup.Do` ensures they do *not* execute the function block. Instead, they receive the `broadcastInfo` created by the leader.
    *   The follower's job is trivial: create a client channel and subscribe to the leader's `StreamBroadcaster`. This is nearly instantaneous and consumes no significant resources.



### Advantages of the New Architecture

*   **True End-to-End Deduplication**: A single LLM/Tool-streaming operation now serves an unlimited number of identical concurrent requests.
*   **Massive Resource Efficiency**: Follower requests consume negligible CPU and memory. They never touch the `llmStreamSemaphore`, leaving it free for genuinely unique requests. This drastically reduces API costs and prevents "thundering herd" problems.
*   **Improved Latency for Followers**: Followers start receiving tokens as soon as the leader does, without waiting in any secondary queue.
*   **Simplified Logic**: The code is more focused. The `Manager` handles all orchestration, and the `Preparer` is simplified to its core task without needing its own `singleflight` logic.
*   **Complex Cancellation Handled**: The new design correctly handles a complex scenario: if a leader request is cancelled by its original client, the underlying broadcast continues for the sake of the followers, while the cancelling client is gracefully disconnected.

---

## 3. Summary of Key Differences

| Feature | Old Architecture | New Architecture | Impact |
| :--- | :--- | :--- | :--- |
| **Worker Pools** | Two distinct, sequential pools (`prepare` & `stream`). | One unified pool (`request`) that orchestrates leaders and followers. | Simplifies logic, removes the intermediate `preparedQueue`, improves resource flow. |
| **Concurrency Model** | Rigid pipeline. Every request must pass through both limited pools. | Flexible & dynamic. Followers are handled instantly; only leaders consume expensive LLM slots. | Dramatically improved throughput and responsiveness for identical/popular requests. |
| **Deduplication** | Partial, within the `Preparer`. Did not prevent duplicate requests from consuming slots in both pools and making duplicate LLM calls. | End-to-end, at the `Manager` level using `singleflight`. Followers don't consume any expensive resources. | Massive efficiency gain. Prevents "thundering herd" problems. |
| **Resource Usage** | Inefficient. Every request, even duplicates, consumed a "preparation" slot and waited in line for its own "streaming" slot. | Highly efficient. One leader does the work for many followers. Reduces CPU, memory, and LLM API costs. | Lower operational costs and greater scalability. |
| **Cancellation Logic** | Simple. Cancel the context for the specific request's process. | More complex. Must differentiate between cancelling a follower (easy) and a leader (must not affect other followers). | A necessary trade-off for the immense performance gain. |

## Conclusion

The architectural transformation from a dual-pool system to a **single-pool, broadcast-driven model** is a significant leap forward. It addresses the core inefficiencies of the previous design, providing a far more scalable, resilient, and cost-effective solution for handling concurrent chat requests, especially in high-traffic scenarios where many users may ask similar questions.
