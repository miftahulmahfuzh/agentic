---
title: "Design Patterns"
date: 2025-08-14
draft: false
---

Tuntun Go Chatbot effectively uses a combination of creational, structural, behavioral, and concurrency patterns.

*   **Concurrency Patterns:**
```bash
    1)  Single Flight (Thundering Herd Protection): To prevent redundant processing of identical concurrent requests.
    2)  Worker Pool: To manage and limit the concurrency of incoming requests.
    3)  Publish-Subscribe (Observer): To broadcast a single result stream to multiple identical requests.
    4)  Context Propagation: For cancellation, timeouts, and managing request lifecycles.
```
*   **Behavioral Patterns:**
```bash
    5)  Strategy Pattern: To define a family of tool algorithms and make them interchangeable.
    6)  State Pattern: To manage the complex lifecycle of a request (Queued, Processing, Cancelled).
```
*   **Structural Patterns:**
```bash
    7)  Facade Pattern: To provide a simple, unified interface to a complex subsystem.
```
*   **Creational & Architectural Patterns:**
```bash
    8)  Dependency Injection (DI): To decouple components and improve testability.
    9)  Factory Method: To centralize and abstract the creation of tools.
```

---

### 1. Single Flight (Thundering Herd Protection)

*   **What it is:** The Single Flight pattern is a concurrency control mechanism that ensures for a given key (e.g., a specific user query), only one function execution (e.g., an LLM call) is in progress at a time. If other identical requests arrive while the first one is running, they will wait for the first one to complete and will all share its result, rather than starting their own redundant executions. This prevents the "thundering herd" problem, where a sudden burst of identical requests overwhelms a downstream service.

*   **Where it's implemented:**
    *   **`chatbot/manager.go`:** The core implementation is in the `Manager` struct and its `processAndRouteRequest` method.
    *   `sfGroup *singleflight.Group`: The `Manager` holds a `singleflight.Group`.
    *   `m.sfGroup.Do(cacheKey, func() (any, error) { ... })`: This is the key line. The `cacheKey` is generated from the conversation history and the new question.
        *   The **first** goroutine to call `Do` with a new `cacheKey` becomes the **"leader"**. It executes the anonymous function, which prepares the request, creates a `broadcastInfo` struct, and starts the streaming process.
        *   **Subsequent** goroutines calling `Do` with the same `cacheKey` become **"followers"**. They block until the leader's function completes, and they receive the *same* `broadcastInfo` struct and error that the leader produced.

*   **Why it was used:** This pattern is critical for efficiency and cost-saving.
    *   **Cost Reduction:** LLM API calls can be expensive. If multiple users ask the exact same question (e.g., "What's the price of BBCA?"), this pattern ensures only one LLM call is made.
    *   **Performance:** It prevents redundant, CPU-intensive work and unnecessary load on external APIs (like financial data sources).
    *   **System Stability:** It protects the system from being overloaded by a sudden spike in identical requests, which is a common scenario in public-facing applications.

---

### 2. Worker Pool

*   **What it is:** A worker pool is a concurrency pattern consisting of a queue of tasks and a fixed number of "worker" goroutines. Instead of spawning a new goroutine for every single task (which can be inefficient and lead to resource exhaustion), tasks are placed on a queue, and the pre-existing workers pick them up for execution. This provides a clean way to control the maximum level of concurrency.

*   **Where it's implemented:**
    *   **`chatbot/manager.go`:**
    *   `requestQueue chan types.SubmitRequestArgs`: This is the task queue. New requests are pushed here.
    *   `prepareSemaphore chan struct{}`: This semaphore controls the number of *active* workers processing requests from the queue. Its capacity is set by `cfg.MaxConcurrentRequests`.
    *   `llmStreamSemaphore chan struct{}`: A second, more specific worker pool limiter just for the most expensive part: concurrent LLM streams.
    *   `requestWorkerPool(ctx context.Context)`: This function is the "dispatcher." It runs in a loop, reads from `requestQueue`, acquires a semaphore slot, and then spins up a goroutine to actually process the request.

*   **Why it was used:**
    *   **Resource Management:** It prevents the application from creating an unbounded number of goroutines, which could consume all available memory and CPU, leading to a crash. The `MaxConcurrentRequests` configuration acts as a throttle.
    *   **Load Balancing:** It provides back-pressure. If the system is at capacity, new requests will wait in the `requestQueue` (up to a timeout) instead of immediately trying to run and failing.
    *   **Decoupling:** The submission of a request (`SubmitRequest`) is decoupled from its execution. The `SubmitRequest` function can return immediately after enqueuing the task, making the API feel responsive.

---

### 3. Publish-Subscribe (Observer) Pattern

*   **What it is:** A messaging pattern where "publishers" (producers of events) do not send messages directly to "subscribers" (consumers of events). Instead, they publish events to a central "broker" or "channel," and all interested subscribers receive the event. This decouples publishers from subscribers.

*   **Where it's implemented:**
    *   **`chatbot/manager.go`:** The `StreamBroadcaster` struct is a custom implementation of this pattern.
    *   `StreamBroadcaster`: This is the broker.
        *   `subscribers []chan tooltypes.StreamEvent`: A list of all subscribers' channels.
        *   `Subscribe(...)`: A method for a client to register its interest and receive events.
        *   `Broadcast(...)`: The publisher (the leader's streaming goroutine) calls this to send an event to all subscribers.
        *   `history []tooltypes.StreamEvent`: An intelligent addition. It records all past events so that a subscriber who joins late can immediately receive the full history up to that point.
    *   The **"leader"** request in the `singleflight` group is the **publisher**. It generates the stream events.
    *   Both the **leader** and all **follower** requests are **subscribers**. They each call `info.broadcaster.Subscribe(clientChan)` to start listening.

*   **Why it was used:**
    *   **Fan-Out:** It's the perfect solution for the `singleflight` pattern's output. One execution (the leader) produces a stream of data, and this pattern efficiently "fans out" that single stream to multiple waiting clients (the leader and all followers) without duplicating the stream generation work.
    *   **Decoupling:** The goroutine generating the stream (`initiateAndManageBroadcast`) doesn't need to know how many clients are listening or who they are. It just broadcasts to the `StreamBroadcaster`. This simplifies the logic significantly.

---

### 4. Context Propagation

*   **What it is:** Context Propagation is a standard and idiomatic Go **concurrency pattern** for carrying request-scoped deadlines, cancellation signals, and other values across API boundaries and between goroutines. A `context.Context` is an object that is threaded through a call chain, typically as the first argument to a function.

*   **Where it's implemented:** This pattern is used pervasively and correctly throughout the entire project.
    *   **Creation and Cancellation:**
        *   In `processAndRouteRequest`: `requestCtx, cancelRequest := context.WithCancel(ctx)`. This creates a new, specific context for a single user request. The `cancelRequest` function is stored in `m.cancellableStreams` so it can be called later from anywhere.
        *   In `CancelStream`: It retrieves the `cancelFunc` and calls it. This is the trigger.
    *   **Propagation (The "Flow"):** The `requestCtx` is passed down the entire call stack. Notice the function signatures:
        *   `m.preparer.Prepare(requestCtx, ...)`
        *   `toolcore.SelectAndPrepareTools(ctx, ...)`
        *   `llm.GenerateContent(ctx, ...)`
        *   `toolutils.ExecuteToolsInParallel(ctx, ...)`
        *   `executeToolAsync(ctx, ...)`
        *   `toolToRun.Call(toolCtx, ...)`
        This creates a "tree" of contexts, and cancelling the root context in `Manager` will cancel all downstream operations that are listening.
    *   **Listening for Cancellation:** The `select` statement with a `case <-ctx.Done()` is how goroutines listen for the cancellation signal.
        *   `GetRequestResultStream`: `case <-ctx.Done(): return nil, ctx.Err()`
        *   `initiateAndManageBroadcast`: `case <-broadcastCtx.Done(): ... return`
    *   **Advanced Usage (Immortalization):** The logic in `initiateAndManageBroadcast` is a brilliant, advanced use of the pattern. The broadcast starts with a cancellable context derived from the leader. However, if a follower joins (`<-info.immortalizeSignal`), the code executes `broadcastCtx = context.Background()`. This **replaces** the cancellable context with the "empty" context that never gets cancelled. This "immortalizes" the broadcast, ensuring that even if the original leader client disconnects, the LLM stream will continue to completion for the benefit of the followers.

*   **Why it was used:**
    *   **Resource Leak Prevention:** This is the most critical reason. Without context propagation, if a user cancelled a request, the goroutines performing the LLM call or executing tools would continue running, wasting CPU, memory, and money. They would become "orphaned" and would only die when their work was done. `context` ensures they are terminated promptly.
    *   **Timeouts and Deadlines:** It provides a unified mechanism for enforcing timeouts. In `executeToolAsync`, `context.WithTimeout` is used to ensure that a single misbehaving tool cannot hang an entire request indefinitely.
    *   **Graceful Shutdown:** When the application receives a shutdown signal, the root `context` can be cancelled, which will propagate through all active requests, allowing them to terminate cleanly. It's the foundation of a reliable, resilient service.

---

### 5. Strategy Pattern

*   **What it is:** The Strategy pattern defines a family of algorithms, encapsulates each one, and makes them interchangeable. It lets the algorithm vary independently from the clients that use it. This is typically achieved with an interface and multiple concrete implementations.

*   **Where it's implemented:** This is the foundation of your entire tool system.
    *   **`tooltypes/interfaces.go`:** `LoggableTool` is the **Strategy Interface**. It defines the contract that all tools must follow (`Name`, `Description`, `Call`, `Stream`, `ToLLMSchema`).
    *   **`toolcore/dynamic.go`:** `DynamicTool` is the **Context** that uses a strategy. It's a generic, concrete implementation of the `LoggableTool` interface. It doesn't contain the tool logic itself.
    *   `ExecutorFunc` and `StreamExecutorFunc`: These function types are the **Concrete Strategies**.
    *   **`toolcore/definitions.go`:** In `BuildAllTools`, you create instances of `DynamicTool` and assign specific anonymous functions (the concrete strategies) to their `Executor` or `StreamExecutor` fields. For example:
        ```go
        {
            NameStr:        "get_current_time",
            // ...
            Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
                return time.Now().Format(time.RFC3339), nil
            },
        },
        ```
        Here, the anonymous function is the "strategy" for getting the current time.

*   **Why it was used:**
    *   **Flexibility and Extensibility:** To add a new tool, you simply create a new `DynamicTool` struct in the `BuildAllTools` list with its own executor function. You don't have to change any of the core logic that *calls* the tools (`SelectAndPrepareTools`, `ExecuteToolsInParallel`).
    *   **Decoupling:** The tool-calling logic is completely decoupled from the tool-implementation logic. The `caller.go` package knows nothing about how `news_summary` or `frequently_asked` actually works; it just knows how to `Call()` any `LoggableTool`.
    *   **Clarity:** It separates the "what" (the interface) from the "how" (the implementation), making the system easier to understand and maintain.

---

### 6. State Pattern

*   **What it is:** The State pattern is a **behavioral pattern** that allows an object to alter its behavior when its internal state changes. The object appears to change its class. The core idea is to represent the states of an object with separate objects or, more simply (as done here), with a state variable. Logic that would otherwise live in large, hard-to-maintain conditional statements (`if/else` or `switch`) is organized around the states.

*   **Where it's implemented:**
    *   **The Context Object:** `types.RequestStream` is the object whose behavior changes.
    *   **The State Variable:** It contains the `State types.RequestState` field.
    *   **The Concrete States:** These are the constants defined in the `types` package:
        *   `StateQueued`
        *   `StateProcessing`
        *   `StateCancelled`
    *   **State-Dependent Behavior:** The `Manager`'s methods behave differently based on the `State` of a `RequestStream`:
        *   **`CancelStream`:** This is the most prominent example. At the start, it checks `if streamHolder.State == types.StateCancelled`. If so, it immediately returns, avoiding redundant work. The rest of the cancellation logic is inherently state-dependent.
        *   **`janitor`:** The janitor's timeout logic is different for each state. A request in `StateQueued` has a `QueueTimeout`, while one in `StateProcessing` has a much longer `ProcessingTimeout`. This prevents requests from getting stuck in a specific phase of their lifecycle for too long.
        *   **`processAndRouteRequest`:** Before starting any work, it checks `if streamHolder.State == types.StateCancelled`. This prevents the system from wasting resources on a request that a user has already abandoned.
        *   **`GetRequestResultStream`:** It handles a request in the `StateCancelled` differently by immediately returning a pre-canned "cancelled" stream.

*   **Why it was used:**
    *   **Clarity and Readability:** The request lifecycle is made explicit. At any point, you can inspect a request and know exactly what stage it's in. This is far clearer than inferring the state from a combination of other conditions (e.g., "is the request in the queue? is its context cancelled?").
    *   **Robustness:** It helps prevent illegal operations. By checking the state at the beginning of methods, the system ensures it doesn't try to, for example, process a request that has already been cancelled and is pending cleanup. It makes the control flow more predictable.
    *   **Maintainability:** It organizes the complex logic of a request's lifecycle. If you needed to add a new state like `StatePaused`, you would add the constant and then you could methodically review each place that checks the state (`janitor`, `CancelStream`, etc.) to add the behavior for this new state. This is much cleaner than modifying a single, monolithic function with deeply nested conditionals.

---

### 7. Facade Pattern

*   **What it is:** The Facade pattern is a **structural pattern** that provides a single, simplified, and unified interface to a larger and more complex body of code, such as a library or an entire subsystem. The goal is to hide the system's internal complexity from the client. The client interacts with the simple facade, which then delegates the calls to the appropriate components within the complex subsystem.

    Think of the ignition system in a car. You, the client, have a very simple interface: a keyhole or a "Start" button (the Facade). When you use it, a complex chain of events happens behind the scenes: the battery is engaged, the starter motor turns, the fuel pump activates, spark plugs fire, etc. (the Subsystem). You don't need to know or manage any of that complexity; you just interact with the simple facade.

*   **Where it's implemented:**
    *   **The Facade:** The `chatbot/Manager` struct in `chatbot/manager.go` is a perfect example of a Facade.
    *   **The Simplified Interface:** The public methods of the `Manager` are the simple interface exposed to the rest of the application (e.g., the HTTP handlers):
        *   `SubmitRequest(question, userID, prevContext)`: The entry point to start a new conversation turn.
        *   `GetRequestResultStream(ctx, requestID)`: The way a client retrieves the streaming results.
        *   `CancelStream(requestID)`: The way to terminate a running request.
    *   **The Complex Subsystem:** The `Manager` facade hides all of the following complex components and interactions, which are implemented as its private fields and unexported methods:
        *   **Request Queuing:** `requestQueue chan types.SubmitRequestArgs`.
        *   **Concurrency Management:** `prepareSemaphore`, `llmStreamSemaphore`, and the `requestWorkerPool`.
        *   **Thundering Herd Protection:** The `sfGroup *singleflight.Group`.
        *   **State Management:** The `activeRequests` map and `cancellableStreams` map.
        *   **Pub/Sub Broadcasting:** The `broadcasters` map and `StreamBroadcaster` logic.
        *   **Resource Cleanup:** The `janitor` goroutine.
        *   **Core Logic Components:** The `preparer` and `streamer` structs which contain the detailed logic for each phase.

*   **Why it was used:**
    *   **Simplicity and Decoupling:** The primary reason is to abstract away the immense complexity of the concurrent processing pipeline. The part of your application that handles API requests doesn't need to know about worker pools, single-flight groups, or broadcasters. It just needs to call `manager.SubmitRequest()` and get back a `requestID`. This is a massive simplification.
    *   **Centralized Control:** All the complex interactions between the queue, workers, state, and broadcaster are orchestrated *within* the `Manager`. This makes the system easier to reason about, as the control logic is not scattered across multiple packages.
    *   **Maintainability:** You can completely refactor the internal workings of the `Manager`—for example, by replacing the `singleflight` library with a custom Redis-based cache—and as long as the public Facade methods (`SubmitRequest`, etc.) keep the same signature, no other part of the application needs to be changed.

---

### 8. Dependency Injection (DI)

*   **What it is:** A design principle where a component receives its dependencies from an external source rather than creating them itself. This inverts the control of dependency management.

*   **Where it's implemented:**
    *   **Tool Creation:** `BuildAllTools(services *core.Services, arangoStore *db.ArangoStore)` receives the `services` and `arangoStore` dependencies and "injects" them into the tool executor closures that need them (e.g., `analyze_stock`).
    *   **Function Arguments:** `SelectAndPrepareTools` receives `availableTools` and `llmTools` as arguments. The comment `// This function accepts tools as arguments, making it a pure function.` explicitly calls this out as a good practice. It doesn't rely on a global tool registry.
    *   **Contextual Logging:** The `logCtx zerolog.Logger` is consistently passed down through the call stack (e.g., `toolToRun.Call(toolCtx, toolArgsJSON, toolLogCtx)`). The logger is a dependency that is injected into every function that needs to produce logs, ensuring all logs have the proper request-scoped context.

*   **Why it was used:**
    *   **Testability:** This is the primary benefit. When testing a tool's executor, you can inject mock `services` or a mock `arangoStore`. When testing `SelectAndPrepareTools`, you can inject a small, controlled set of mock tools.
    *   **Decoupling:** Components are not tightly coupled to their dependencies' creation logic. The `Manager` doesn't know how to build tools; it just receives them.
    *   **Flexibility:** It's easy to swap out implementations. For example, you could have a different `ArangoStore` implementation for local development vs. production and inject the correct one at startup.

---

### 9. Factory Method

*   **What it is:** A creational pattern that provides an interface for creating objects in a superclass but lets subclasses alter the type of objects that will be created. In a more general sense, it centralizes the creation logic for a complex object or a family of objects into a single function or method.

*   **Where it's implemented:**
    *   **`toolcore/definitions.go`:** `BuildAllTools` is a classic example of a Factory function. It encapsulates all the complex logic, schemas, and details of creating the entire list of `DynamicTool` objects.
    *   **`toolcore/definitions.go`:** `GetFormattedTools` is a related helper function that takes the output of the factory and transforms it into the specific formats needed by different parts of the application (`map[string]tooltypes.LoggableTool` and `[]llms.Tool`).

*   **Why it was used:**
    *   **Centralization:** All tool definitions are in one place. If you need to add, remove, or modify a tool, you know exactly where to go.
    *   **Abstraction:** The `Manager` doesn't need to know the details of tool construction. It just calls `BuildAllTools` and gets the finished product, simplifying the `Manager`'s `NewManager` constructor.
