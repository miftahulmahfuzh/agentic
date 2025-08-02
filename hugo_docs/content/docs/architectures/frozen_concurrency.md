---
title: "Static Concurrency"
date: 2025-08-02
draft: false
---

# Architectural Note: On the Deliberate Enforcement of Static Concurrency Limits

This document addresses the suggestion that the service's concurrency limits (`MaxConcurrentRequests`, `MaxConcurrentLLMStreams`) should be dynamically configurable at runtime, perhaps via an API endpoint. The argument is that this would provide operational flexibility to adjust the system's capacity in response to changing load without requiring a restart.

This document asserts that such a feature would be a critical design flaw. It sacrifices stability, predictability, and safety for an illusory and dangerous form of flexibility.

## The Question: Why Are Our Capacity Limits 'Frozen' at Startup?

The core argument for dynamic limits is one of adaptability. Why not have a lever we can pull to instantly increase the chatbot's processing power when traffic spikes? Why must we be constrained by static values set in a configuration file or environment variable?

This line of thinking fundamentally misunderstands how robust, scalable systems are built. It treats a service instance like a video game character that can instantly chug a potion for a temporary strength boost. Real-world systems are not games. They are engines that require precise, predictable calibration. You don't adjust the timing on a Formula 1 car's engine in the middle of a race.

## Analysis of the Two Approaches

### The Current Static Limits Approach

-   **Mechanism:** Limits are read once from configuration on application startup and used to create fixed-capacity semaphore channels.
-   **Execution:** A worker goroutine attempts to acquire a token from the semaphore (`semaphore <- struct{}{} `). If the pool is full, the goroutine blocks until a token is available. Simple, fast, and deterministic.
-   **Complexity:** Zero. The Go runtime handles the semaphore logic. It is bulletproof.
-   **Stability:** Absolute. The capacity of the instance is a known, predictable constant. It will not behave erratically or overwhelm its dependencies (LLM APIs, database) due to a sudden, operator-induced change. The system's performance profile is stable and easy to reason about.
-   **Scalability Model:** Horizontal. If more capacity is needed, you deploy more identical, predictable instances. This is the foundation of cloud-native architecture. The system scales by adding more soldiers to the army, not by trying to turn one soldier into The Hulk.

### The Proposed Dynamic Limits Approach

-   **Mechanism:** An API endpoint to receive new limit values. Internal logic to resize or replace the existing semaphore channels on the fly.
-   **Execution:**
    1.  An operator makes an API call to change a limit.
    2.  The application must acquire a global lock to prevent race conditions while it modifies the concurrency settings.
    3.  **Shrinking the pool:** How do you safely reduce capacity? Do you kill the excess in-flight workers? Do you wait for them to finish, defeating the purpose of an "instant" change? This is a minefield of potential deadlocks and data corruption.
    4.  **Growing the pool:** This is safer, but still requires re-allocating the semaphore channel, a complex and risky operation in a live, multi-threaded environment.
    5.  Every worker would have to constantly check the current limit value, adding overhead and complexity.
-   **Complexity:** A nest of vipers. You've introduced distributed systems problems (coordination, consensus) *inside* a single process. The logic required is brittle, hard to test, and an open invitation for subtle, catastrophic bugs.
-   **Stability:** Destroyed. You've given operators a loaded gun. A typo in an API call (`1000` instead of `100`) could instantly DoS your own dependencies, leading to massive bills and a total system outage. The system is no longer a predictable unit.
-   **Scalability Model:** Vertical, and dangerously so. It encourages the anti-pattern of creating a single, monolithic "pet" instance that you constantly tinker with, rather than treating instances as disposable "cattle."

## Conclusion: We Build With Granite Blocks, Not Jenga Towers

The primary duty of this architecture is to be stable and predictable. A single service instance is a building block. We know its dimensions, its weight, and its breaking strain. We achieve scale by deploying more of these identical blocks.

Dynamic limits violate this principle at a fundamental level. It's an attempt to make one block able to change its shape and size at will. This is not flexibility; it is chaos.

| Feature              | Static Limits (Current)                             | Dynamic Limits (Proposed)                                     | Verdict                                                                           |
| -------------------- | --------------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Complexity**       | Zero. Handled by Go runtime.                        | Massive. A complex, stateful, and bug-prone internal system.  | The current approach is orders of magnitude safer and simpler.                    |
| **Stability**        | Absolute and predictable.                           | Fragile. Prone to operator error and race conditions.         | Static limits are the foundation of a reliable service.                           |
| **Scalability Model**| **Horizontal.** Add more predictable instances.      | **Vertical.** Create a single, dangerously powerful instance. | The current model is the proven, industry-standard way to build scalable services. |
| **Operational Risk** | Low. Configuration is version-controlled and tested. | High. A "fat-finger" API call can cause a system-wide outage. | Dynamic limits are an unacceptable operational hazard.                              |
| **Pragmatism**       | High. Solves the real need (capacity) correctly.    | Low. A theoretical "nice-to-have" that is practically a nightmare. | This is engineering, not wishful thinking.                                         |

A system must have discipline. It must operate within known boundaries. John Wick doesn't decide to change his pistol's caliber in the middle of a fight. He carries a set of tools he has mastered and uses them with brutal, predictable efficiency. Our service instances are his tools.

**Therefore, static concurrency limits are a deliberate and non-negotiable feature of this architecture.** They enforce the stability and predictability that are paramount for a resilient, scalable system.
