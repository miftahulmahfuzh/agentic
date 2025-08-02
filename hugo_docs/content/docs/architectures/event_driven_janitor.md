---
title: "Polling Janitor"
date: 2025-08-02
draft: false
---

# Architectural Note: Why We Use a Polling Janitor

This document addresses a design choice in the `manager.go` lifecycle management: the use of a periodic, polling "janitor" to clean up timed-out requests, rather than a purely event-driven timeout mechanism for each request. This choice is deliberate and grounded in engineering pragmatism.

## The Question: Can the Janitor Be Event-Driven?

The core system architecture strongly favors non-blocking, event-driven designs over polling to maximize CPU efficiency. A valid question arises: Why doesn't the resource janitor follow this pattern? The current implementation uses a single goroutine that wakes up periodically (`JanitorInterval`), iterates through all active requests, and checks if any have exceeded their state-specific timeout (`QueueTimeout` or `ProcessingTimeout`).

An alternative "event-driven" approach might involve spawning a dedicated timer-goroutine for each individual request. This goroutine would sleep until the request's specific timeout is reached and then trigger a cleanup.

This document argues that the current polling approach is superior for this specific use case.

## Analysis of the Two Approaches

### The Current Polling Janitor

-   **Mechanism:** A single, long-lived goroutine.
-   **Execution:** Wakes up once per `JanitorInterval` (e.g., 2 minutes).
-   **Work Done:** Acquires a lock, iterates a map, performs a cheap `time.Since()` check for each entry.
-   **Resource Cost:**
    -   **CPU:** Effectively zero. The work is measured in microseconds and occurs infrequently. For the vast majority of its life, the goroutine is asleep and consumes no CPU.
    -   **Memory:** The cost of one goroutine stack. Minimal.
-   **Complexity:** Low. All cleanup logic is centralized in a single, simple, easy-to-debug loop.

### The Proposed Event-Driven Janitor

-   **Mechanism:** One new goroutine and one `time.Timer` object are created *for every active request*.
-   **Execution:**
    1.  When a request is submitted, a goroutine is launched with a `time.NewTimer` set to `QueueTimeout`.
    2.  If the request is dequeued, the first timer/goroutine must be cancelled, and a *new* one launched with a timer for `ProcessingTimeout`.
    3.  If the request completes successfully, its associated timer/goroutine must be found and terminated.
-   **Resource Cost:**
    -   **CPU:** While each individual goroutine is sleeping, the Go runtime's internal scheduler must now manage a heap of potentially thousands of `time.Timer` objects. This pushes the polling work down into the runtime, which is more complex and has more overhead than a simple map iteration.
    -   **Memory:** N goroutine stacks and N `time.Timer` objects, where N is the number of concurrent active requests. This scales linearly with load and is significantly higher than the single-goroutine approach.
-   **Complexity:** High.
    -   The cleanup logic is now distributed across thousands of ephemeral goroutines.
    -   It requires a complex system of timer cancellation and synchronization to prevent leaking goroutines when requests complete normally or are cancelled by the user.
    -   This massively increases the surface area for subtle race conditions.

## Conclusion: Pragmatism Over Dogma

The goal of event-driven design is to avoid wasting resources on unproductive work, like a CPU spinning in a busy-wait loop. The current janitor does not do this. It is a highly efficient, low-frequency task whose performance impact is negligible, even at massive scale.

| Feature               | Polling Janitor (Current)                                | Event-Driven Janitor (Proposed)                                     | Verdict                                                                           |
| --------------------- | -------------------------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **CPU Usage**         | Microscopic spikes every few minutes.                    | Constant low-level scheduler overhead managing N timers.            | Polling is demonstrably cheaper in this scenario.                                 |
| **Memory Usage**      | Constant (1 goroutine).                                  | Linear (`O(N)` goroutines + timers).                                | Polling is vastly more memory-efficient under load.                               |
| **Code Complexity**   | Low. Centralized, simple, robust.                        | High. Distributed, complex state management, prone to races.        | Polling leads to more maintainable and reliable code.                             |
| **Philosophical Purity** | Appears to violate the "no polling" rule.              | Appears to be purely "event-driven."                                | This is a red herring. The goal is efficiency, not blind adherence to a pattern. |

The proposed event-driven janitor is a solution in search of a problem. It represents a form of **premature optimization** that would trade a simple, robust, and performant system for a complex, fragile one that offers no tangible benefits.

**Therefore, the single-goroutine, periodic polling janitor is the correct and final design choice.** It is a pragmatic engineering decision that prioritizes simplicity, reliability, and real-world performance over dogmatic adherence to a design pattern in a context where it is inappropriate.

