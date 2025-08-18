---
title: "Adapter Pattern"
date: 2025-08-18
draft: false
---

The `chatbot` package is an excellent example of the Adapter pattern used to achieve high levels of decoupling. Let's break it down in detail, package by package, to see how this "beautiful symphony" is composed.

### The Core Concept: The Adapter Pattern

Think of a real-world power adapter. You have a laptop with a US plug (the `*chatbot.Manager`), but you're in Europe with a European wall socket (the `cache.FastLane` component). Your laptop can't plug directly into the wall.

The **Adapter** is the small block you plug in between.
*   It has a female side that **accepts** the US plug (`*chatbot.Manager`).
*   It has a male side that **conforms to the interface** of the European wall socket (`cache.FastLaneManagerInterface`).

The `cache.FastLane` component doesn't know or care about the `*chatbot.Manager`. It only knows it needs something that provides power in a specific shape—its `FastLaneManagerInterface`. The adapter makes the `*chatbot.Manager`'s functionality "fit" that shape.

In this codebase, the file `chatbot/interfaces.go` is your factory for these adapters. It creates the bridges between the all-knowing `Manager` and the specialized, "ignorant" components.

---

### How Each Package Achieves Decoupling (The Soloists)

Each of the following packages is like a world-class soloist. It is hyper-specialized and brilliant at its one job. It doesn't need to know how the rest of the orchestra works; it only needs its sheet music (the interface).

#### 1. `cache` Package (`fastlane.go` & `keygen.go`)

*   **Its Worldview:** "My job is to check Redis for a cache key. If I find a match, I stream the response and I'm done. If not, I do nothing. To do this, I need a way to get a request's stream holder, set its state, get configuration, access Redis, and log to a database. I have absolutely **no idea** what a semaphore, a queue, a 'leader', or a 'follower' is, and I don't care."

*   **The Contract (Its Sheet Music):** It defines its needs in `fastlane.go` with the `FastLaneManagerInterface`.

    ```go
    // FastLaneManagerInterface defines what the cache fast-lane needs
    type FastLaneManagerInterface interface {
        GetActiveRequest(requestID string) (*types.RequestStream, bool)
        SetRequestState(requestID string, state types.RequestState)
        CleanupRequest(requestID string, logCtx any, cancelContext bool)
        GetConfig() FastLaneConfig
        GetRedisClient() RedisInterface
        CreateChatLog(ctx context.Context, logData types.LogDataForDB) (string, error)
    }
    ```

*   **The Decoupling:** The `cache` package can be developed and tested in complete isolation. It has zero `import` statements pointing to the `processing`, `cancellation`, or `queue` packages. It is entirely self-contained.

*   **The Unit Testing Advantage:** Look at `fastlane_test.go`. It doesn't need to spin up a full chatbot `Manager`. Instead, it creates a `mockFastLaneManager` (`mock_adapter.go`) which implements the `FastLaneManagerInterface`. The test can now precisely control the "world" as the `FastLane` sees it.
    *   `mockManager.On("GetRedisClient").Return(mockRedis)`: We can simulate Redis being down.
    *   `mockRedis.On("Get", ...).Return("cached response", nil)`: We can simulate a perfect cache hit.
    *   `mockManager.On("GetActiveRequest", ...).Return(nil, false)`: We can simulate the request having already been cancelled.

    This makes testing fast, reliable, and focused *only* on the `FastLane`'s logic.

#### 2. `processing` Package (`executor.go`, `preparer.go`, `streamer.go`)

*   **Its Worldview:** "I am the engine room. My job is to execute the main logic. I deal with 'leader' and 'follower' tasks, which means I need access to semaphores. I need to run expensive 'preparation' logic (like fetching history and selecting tools) and then 'stream' the final result. I need access to single-flight groups to prevent thundering herds. I have **no idea** how requests get *into* the system or how they are queued. I don't handle user-facing cancellation requests."

*   **The Contract (Its Sheet Music):** It defines its needs in `executor.go` with the `ExecutorManagerInterface`.

    ```go
    // ExecutorManagerInterface defines what the executor needs
    type ExecutorManagerInterface interface {
        // ... methods for getting requests, state, config ...
        GetSingleflightGroup() SingleflightGroup
        GetCancellableStreams() map[string]context.CancelFunc
        SetCancellableStream(requestID string, cancelFunc context.CancelFunc)
        GetLeaderSemaphore() chan struct{}
        GetFollowerSemaphore() chan struct{}
        GetStreamer() StreamerInterface
    }
    ```

*   **The Decoupling:** The entire, complex logic of preparing a request, dealing with single-flight, acquiring semaphores, and executing leader/follower tasks is self-contained. It doesn't import `queue` or `cancellation`. It can be reasoned about and modified without touching any other part of the system.

*   **The Unit Testing Advantage:** Although no test file is provided for the `executor`, one could easily be written. You would create a `mockExecutorManager` that implements the interface above. You could then test scenarios like:
    *   What happens when `GetLeaderSemaphore()` blocks?
    *   Does `ExecuteFollowerTask` correctly call `info.AddFollower()`?
    *   Does `ExecuteLeaderTask` correctly use the `singleflight.Group`?
    All without needing a real queue or a real cancellation handler.

#### 3. `cancellation` Package (`handler.go`)

*   **Its Worldview:** "My one and only job is to handle a user's request to cancel a stream. This is complicated. I need to know if the request is a 'leader' or a 'follower' and act accordingly. I need to find the request's state, change it to 'cancelled', and potentially trigger a context cancellation. I have **no idea** how a stream is generated, what Redis is, or how requests are queued. I am the cleanup crew."

*   **The Contract (Its Sheet Music):** It defines its needs in `handler.go` with the `CancellationManagerInterface`.

    ```go
    // CancellationManagerInterface defines what the cancellation handler needs
    type CancellationManagerInterface interface {
        GetActiveRequest(requestID string) (*types.RequestStream, bool)
        SetRequestState(requestID string, state types.RequestState)
        GetCancellableStream(requestID string) (func(), bool)
        CleanupRequest(requestID string, logCtx any, cancelContext bool)
        // ...
    }
    ```

*   **The Decoupling:** The intricate logic of "deceptive cancellation" (a leader is cancelled but followers remain) vs. "lone leader cancellation" is perfectly isolated here. This logic is arguably some of the most complex in the system, and it can be perfected without ever thinking about how an LLM is called.

*   **The Unit Testing Advantage:** You can write tests that create a mock manager and a mock broadcast manager. You can then simulate every possible cancellation scenario to ensure correctness:
    *   Test cancelling a follower when it's the *last* follower (should terminate the leader).
    *   Test cancelling a leader that has active followers (should *not* terminate the broadcast).
    *   Test cancelling a request that doesn't exist.
    Each test is lightweight and targets a specific, complex state-management path.

#### 4. `queue` Package (`manager.go`)

*   **Its Worldview:** "I am a glorified list. I hold requests. I must preserve First-In-First-Out (FIFO) order, even when items are re-queued. When I'm full and an old request needs to be re-queued, I have to evict the newest one. To do that, I need to tell someone to clean up the evicted request. I know **nothing** else."

*   **The Contract (Its Sheet Music):** It defines its needs in `manager.go` with `ManagerDependencies`.

    ```go
    // ManagerDependencies defines what QueueManager needs
    type ManagerDependencies interface {
        CleanupRequest(requestID string, logCtx any, cancelContext bool)
        GetRequestLock() *sync.RWMutex
        GetActiveRequests() map[string]*types.RequestStream
    }
    ```
*   **The Decoupling:** This is the most decoupled component of all. It's almost a pure data structure. Its logic for FIFO-preserving eviction is completely isolated and has no dependencies on any other major component.

*   **The Unit Testing Advantage:** `manager_test.go` perfectly demonstrates this. The `setupTestQueueManager` function creates a `queue.Manager` and a tiny `internal.MockManager` that satisfies the `ManagerDependencies` interface. The tests for `TestFIFOEvictionOnFullQueue` and `TestComplexEvictionScenario` are focused solely on the queue's internal logic, which is exactly what you want.

---

### The Conductor: `chatbot/manager.go` (The Symphony)

The (inferred) `chatbot/Manager` is the conductor. It holds the concrete instances of everything: the real Redis client, the real database connection, the real semaphores, the active request map, etc.

Its role is to **compose the symphony** by:

1.  **Instantiating the Soloists:** In its constructor (`NewManager`), it creates instances of `cache.FastLane`, `processing.Executor`, `cancellation.Handler`, and `queue.Manager`.

2.  **Providing the Adapters:** When it creates these components, it doesn't pass a raw `*Manager` pointer. Instead, it passes the special adapters defined in `chatbot/interfaces.go`.

    ```go
    // Inside the (inferred) chatbot.NewManager() function:

    // Create the cache component, giving it an adapter that makes the Manager
    // look like what the cache expects.
    m.cacheHandler = cache.NewFastLane(&cacheFastLaneAdapter{manager: m})

    // Create the executor, giving it adapters that make the Manager
    // look like what the executor expects.
    m.executor = processing.NewExecutor(m, ...) // 'm' itself implements ExecutorManagerInterface

    // Create the cancellation handler...
    m.canceller = cancellation.NewHandler(m, ...) // 'm' implements CancellationManagerInterface

    // ...and so on for all other components.
    ```

3.  **Directing the Flow:** The `Manager` handles the entry points. When a new request arrives, it directs the flow:
    *   "First, I'll ask the `cache.FastLane` to try and process this."
    *   "If the cache misses, I'll give the request to the `queue.Manager`."
    *   "My worker pool will pull from the `queue.Manager` and pass the request to the `processing.Executor`."
    *   "If a cancellation request comes in, I'll pass it to the `cancellation.Handler` to deal with it."

The adapters are the glue that allows the Conductor (`Manager`) to speak the specific language of each Soloist (component package). The result is a system where each part is simple, focused, and independently testable, yet they combine to perform a highly complex and robust task. This is the essence of beautifully decoupled architecture.
