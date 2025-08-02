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

# Goroutines in the Assembly Line Architecture (`manager.go`)

Goroutines are the heart of Go's concurrency model. They are extremely lightweight threads managed by the Go runtime, not the OS. This allows you to run hundreds of thousands of them concurrently, making them perfect for I/O-bound and parallel tasks.

Your `manager.go` has evolved from a simple worker pool into a more sophisticated, two-stage **assembly line pipeline**. This design explicitly recognizes that request processing has two phases with different resource requirements: a fast, cheap "preparation" phase and a slow, expensive "streaming" phase. The architecture uses distinct goroutine pools for each, preventing the slow phase from blocking the fast one. This maximizes throughput and resource utilization.

Let's break down the roles of the goroutines in this superior architecture.

### 1. The Singleton "Manager" Goroutines (The Foremen)

*   **Where they are started:** In `Init()`, with `go prepareWorkerManager(ctx)` and `go streamWorkerManager(ctx)`.
*   **How many:** Exactly **two** manager goroutines for the entire application lifetime.
    1.  `prepareWorkerManager`: The "Prep Foreman."
    2.  `streamWorkerManager`: The "Baking Foreman."
*   **Purpose:** These are the master coordinators for each stage of the assembly line. They are simple, non-blocking loops.
    *   The **Prep Foreman**'s only job is to listen on the initial `requestQueue`. When a request arrives, it acquires a "prep station" slot from `prepareSemaphore` and immediately spawns a "Preparation Worker" goroutine to handle that task.
    *   The **Streaming Foreman**'s only job is to listen on the `preparedQueue`. When a "prepared" request arrives, it acquires an expensive "oven" slot from `llmStreamSemaphore` and immediately spawns a "Streaming Worker" goroutine.

By delegating the actual work, these foremen remain free to manage the flow of tasks into their respective stages without ever getting blocked.

### 2. The "Preparation Worker" Goroutine Pool (The Apprentices)

*   **Where it's started:** Inside `prepareWorkerManager`.
*   **How many:** A pool of up to `config.AppSettings.MaxConcurrentRequests`.
*   **Purpose:** This is the "first stage" worker, the cook's apprentice. Its job is to perform all the fast, non-streaming preparation for a single request. This is a well-defined, bounded set of tasks:
    1.  Transition the request's state in the central `activeRequests` map from `Queued` to `Processing`.
    2.  Fetch chat history from the database.
    3.  Check Redis for a cached response.
    4.  Execute the first LLM call for tool selection (`toolcore.ProcessTools`).
    5.  Assemble the final prompt.
*   **Key Behavior & Handoff:** Once preparation is complete, its job is done. It packages all its work into a `PreparedRequestData` struct and places it onto the `preparedQueue`. Then, crucially, **it immediately releases its `prepareSemaphore` slot and exits**. It does **not** wait for the streaming to start. This frees up the "prep station" for the next request.

### 3. The "Streaming Worker" Goroutine Pool (The Senior Cooks)

*   **Where it's started:** Inside `streamWorkerManager`.
*   **How many:** A smaller, more exclusive pool of up to `config.AppSettings.MaxConcurrentLLMStreams`.
*   **Purpose:** This is the "second stage" worker, the senior cook with access to the expensive ovens. It picks up a fully prepared request from the `preparedQueue` and performs the final, blocking, resource-intensive work:
    1.  Check for a cached response (a final check in case the request was for a common, already-cached item that didn't need tools).
    2.  Call the main LLM with the final prompt (`llms.GenerateFromSinglePrompt`). This is the slow, expensive part.
    3.  Stream the LLM's token responses back to the client via the `streamChan`.
    4.  Perform final logging to the database.
    5.  **Perform final cleanup.** This worker is responsible for removing the completed request from the central `activeRequests` and `cancellableStreams` maps.
*   **Lifespan:** This goroutine lives for the duration of the LLM stream. It releases its `llmStreamSemaphore` slot only when it is completely finished.

### Visualizing the Handoff: A Request's Journey

This architecture creates a clean, efficient flow, communicating through channels and a shared map.

1.  **Client -> `SubmitRequest`:** A request is born. A `RequestStream` holder is created and placed in the central `activeRequests` map with `State: StateQueued`. A `SubmitRequestArgs` struct is put on the **`requestQueue` channel**.

2.  **`requestQueue` -> `prepareWorkerManager` (Prep Foreman):** The foreman sees the new task. It acquires a slot from `prepareSemaphore` and spins up a **Preparation Worker**.

3.  **Preparation Worker:** This goroutine executes. It locks the `requestsLock`, finds its request in `activeRequests`, and updates its state to `StateProcessing`. It then does its work (history, tools, etc.). After creating the `PreparedRequestData` struct, its last act is to send this struct to the **`preparedQueue` channel**. The worker then exits, releasing its `prepareSemaphore` slot.

4.  **`preparedQueue` -> `streamWorkerManager` (Streaming Foreman):** This foreman sees the prepared data. It acquires a slot from `llmStreamSemaphore` and spins up a **Streaming Worker**.

5.  **Streaming Worker:** This goroutine executes. It finds its `RequestStream` holder in `activeRequests` to get the `Stream` and `Err` channels. It sends the real `streamChan` to the holder, waking up the client-facing `GetRequestResultStream` function. It then performs the LLM call and streams tokens. Finally, it cleans up the `activeRequests` and `cancellableStreams` maps and exits, releasing its `llmStreamSemaphore` slot.

6.  **`GetRequestResultStream` -> Client:** This function, called by the client, simply waits on the channels inside the `RequestStream` holder. It is a passive observer. When the Streaming Worker sends the `streamChan`, it receives it and begins forwarding tokens to the client.

This is a true pipeline. The fast "preparation" workers are never held hostage by the slow "streaming" workers, allowing the system to process a high volume of incoming requests efficiently, even when the final LLM calls are slow.
