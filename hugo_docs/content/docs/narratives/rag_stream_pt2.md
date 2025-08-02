---
title: "RAG Stream Part 2"
date: 2025-08-02
draft: false
---

Let's trace the journey of the query "how to register in tuntun?" from the moment the user hits "send" to the final word appearing on their screen.

This story unfolds in four main acts:
1.  **The Submission:** The request enters the system.
2.  **The Preparation:** The system decides *what* to do. This is the critical decision point.
3.  **The Execution:** The system performs the action, in this case, a direct RAG stream.
4.  **The Delivery:** The streaming answer reaches the user.

---

### The Story of "how to register in tuntun?"

#### Act I: The Submission (`Manager.SubmitRequest`)

A user opens the chatbot and types "how to register in tuntun?". The client-facing API calls `Manager.SubmitRequest`.

1.  **Request ID Generation:** A unique ID is created, let's say `req_f4a12`. This ID is the key to tracking the request throughout its lifecycle.
2.  **State Holder Creation:** The `Manager` creates a `types.RequestStream` "holder". This is a crucial control structure in `activeRequests["req_f4a12"]`. It contains:
    *   `Stream (chan (<-chan tooltypes.StreamEvent))`: A channel that will eventually carry the *actual* result channel. Think of it as a mailbox waiting for a letter that is, itself, a pipeline.
    *   `Err (chan error)`: A channel to send fatal errors or cancellation signals.
    *   `ClientConnected (chan struct{})`: A signal to indicate the client is ready to receive the stream.
    *   `State`: Set to `types.StateQueued`.
3.  **Enqueueing:** The request details (ID, question, user) are wrapped in `types.SubmitRequestArgs` and placed into the `requestQueue`.
4.  **Immediate Return:** The function immediately returns the `requestID` ("req_f4a12") to the client. The client now holds this ID and will use it to ask for the results.

The request is now waiting in a line, like a customer at a bank teller.

#### Act II: The Preparation (`prepareWorkerManager` & `RequestPreparer`)

This is where the system's "brain" makes its decision.

1.  **Dequeueing:** A `prepareWorker` goroutine, managed by `prepareWorkerManager`, picks up `req_f4a12` from the `requestQueue`. It acquires a slot from the `prepareSemaphore`.
2.  **State Update:** The request's state is updated from `StateQueued` to `StateProcessing`. A cancellable context is created and its `cancelFunc` is stored in `cancellableStreams["req_f4a12"]`, linking the request ID to a "stop" button.
3.  **Calling the Preparer:** The worker calls `preparer.Prepare(..., req_f4a12, ...)`.
4.  **Inside the Preparer (`doExpensivePreparation`)**:
    *   It checks for a Redis cache entry based on the conversation history and question. It's a `miss`.
    *   It calls `toolcore.SelectAndPrepareTools`. This is the pivotal moment.
5.  **The Critical Decision (`SelectAndPrepareTools`)**:
    *   The function assembles a prompt for the LLM that includes the tool descriptions and the user's question.
    *   The `frequently_asked` tool has a very specific description: `This is the primary tool for answering all user questions that seek knowledge, definitions, explanations, or guidance... Use this tool for any of the following: ... How-to guides for using Tuntun Sekuritas products.` It even has an instruction to translate informal queries into formal ones.
    *   The LLM analyzes "how to register in tuntun?" and sees a perfect match. It decides to call the `frequently_asked` tool. It also formalizes the query.
    *   The LLM's response is a single tool call: `frequently_asked(query="how to register on the Tuntun application")`.
    *   The code in `SelectAndPrepareTools` checks this result. It sees:
        *   There is only one tool call.
        *   The tool's name, `frequently_asked`, is listed in the `config.AppSettings.NaturalAnswerTools` array.
    *   **The Flag is Set:** Because both conditions are met, it returns a `tooltypes.ToolPreparationResult` with `IsDirectStream: true`. It does *not* execute the tool here. It simply flags this request for the direct streaming path.
6.  **Back to the Manager:** The `prepareWorker` receives the `PreparedRequestData` with `IsDirectStream: true`. It puts this prepared data onto the `preparedQueue`, ready for the next stage.

The system has now decided: "This doesn't need complex reasoning. I will connect the user directly to the knowledge base."

#### Act III: The Execution (`streamWorkerManager` & `ResponseStreamer`)

This is where the direct RAG streaming path is executed and where the channels play their intricate dance.

1.  **Dequeueing for Streaming:** A `streamWorker` goroutine picks up the prepared data for `req_f4a12` from the `preparedQueue`. It acquires a slot from the `llmStreamSemaphore`.
2.  **Locating the Holder:** It finds the original `RequestStream` holder using the `requestID`.
3.  **Calling the Streamer:** It calls `s.streamer.Stream(streamChan, preparedData, ...)`.
4.  **Inside the Streamer (`runDirectToolStream`)**:
    *   The `Stream` method sees `IsDirectStream` is true and immediately calls `runDirectToolStream`.
    *   It finds the `frequently_asked` tool's definition in `availableTools`. This `DynamicTool` struct contains a `StreamExecutor` field pointing to `toolnonbe.StreamTencentFrequentlyAsked`.
    *   **The Tool is Called:** It invokes the tool's `Stream` method, passing it the request's cancellable context, arguments, logger, and a *newly created internal channel* (`internalStreamChan`).
5.  **Inside the Tool (`StreamTencentFrequentlyAsked`)**:
    *   This function is now active. It makes an HTTP POST request to the Tencent RAG API, which is a Server-Sent Events (SSE) endpoint.
    *   It starts reading the streaming response body from Tencent line-by-line.
    *   As it receives data chunks (e.g., `data: {"payload": {"content": "To register,"}}`, `data: {"payload": {"content": "To register, you must first"}}`, etc.), it calculates the new text (`delta`).
    *   For each `delta`, it creates a `tooltypes.StreamEvent` and **sends it into the channel it was given (`internalStreamChan`)**.
6.  **Forwarding the Stream:** Simultaneously, back in `runDirectToolStream`, a `for range` loop is listening on that same `internalStreamChan`. As it receives events from the tool, it **immediately forwards them to `streamChan`** (the channel it received from the `streamWorkerManager`). This acts as a simple relay.

#### Act IV: The Delivery (`GetRequestResultStream`)

While all of this is happening, the user's client has been waiting.

1.  **Client Polls for Result:** The client code calls `Manager.GetRequestResultStream("req_f4a12")`.
2.  **Waiting for the Pipe:** The function finds the `RequestStream` holder for `req_f4a12`. It blocks on the `select` statement, specifically on `stream := <-streamHolder.Stream`. It's waiting for the "pipeline" to be delivered to its "mailbox".
3.  **The Handoff:** In Act III, the `streamWorkerManager` put the main `streamChan` into the holder's `Stream` channel. This action unblocks `GetRequestResultStream`.
4.  **Connection Complete:** `GetRequestResultStream` now has the `streamChan`—the very same one the `ResponseStreamer` is feeding events into—and returns it to the client.
5.  **Receiving Tokens:** The client now has a direct line to the output. It runs a `for event := range streamChan` loop. As the `StreamTencentFrequentlyAsked` tool sends tokens to the `ResponseStreamer`, which forwards them to the `streamChan`, the client receives them in near real-time and displays them to the user.

The user sees the answer "To register, you must first download the Tuntun application from..." appearing on their screen word by word.

---

### How the Direct RAG Streaming Channels Work

This is the core of your second question. The process involves a chain of channels, like a bucket brigade, ensuring a direct, cancellable path from the RAG API to the user's screen.

Here is a visual representation of the channel flow:

{{< mermaid >}}
graph LR
    %% Define Subgraphs for architectural layers
    subgraph Client_Tier ["Client Tier"]
        Client[Client Application]
    end

    subgraph Application_Backend ["Application Backend"]
        subgraph Request_Lifecycle ["The Manager"]
            Manager["Manages state for req_f4a12"]
        end

        subgraph Execution_Engine ["Execution Engine"]
            Streamer["Response Streamer<br/>Orchestrates the streaming process"]
            ToolExecutor["RAG Tool Executor<br/>(e.g., StreamTencentFrequentlyAsked)"]
        end
    end

    subgraph External_Services ["External Services"]
        RAG_API["External RAG Service<br/>(Server-Sent Events Endpoint)"]
    end

    %% Define Styles for clarity and elegance
    classDef client fill:#e3f2fd,stroke:#0d47a1,stroke-width:2px
    classDef manager fill:#f3e5f5,stroke:#4a148c,stroke-width:2px
    classDef executor fill:#e8f5e9,stroke:#1b5e20,stroke-width:2px
    classDef external fill:#fff3e0,stroke:#e65100,stroke-width:2px

    class Client client
    class Manager manager
    class Streamer,ToolExecutor executor
    class RAG_API external

    %% Control Flow: Establishes the connection
    Client -.->|"1-Polls with request ID<br/>(GetRequestResultStream)"| Manager
    Manager -.->|"2-Provides client with<br/>mainStreamChan for results"| Client

    %% Execution & Data Flow: The main pipeline
    Manager -->|"3-Dispatches Prepared Request"| Streamer
    Streamer -->|"4-Invokes Tool with a new<br/>internalStreamChan & context"| ToolExecutor
    ToolExecutor -->|"5-HTTP Stream Request"| RAG_API
    RAG_API -->|"6-SSE Data Chunks"| ToolExecutor
    ToolExecutor -->|"7-Writes tooltypes.StreamEvent<br/>to internalStreamChan"| Streamer
    Streamer -->|"8-Relays events from internal to<br/>mainStreamChan"| Client
{{< /mermaid >}}

**The Handoffs Explained:**

1.  **Handoff 1 (The Pipe Delivery):** The `streamWorkerManager` creates the primary channel (`streamChan`) that the client will eventually read. It places this channel *inside* another channel (`holder.Stream`), essentially delivering the pipe to a known location. `GetRequestResultStream` is waiting at that location to pick it up.

2.  **Handoff 2 (The Tool Connection):** The `ResponseStreamer` acts as an adapter. It can't give `streamChan` directly to the tool because it might need to intercept or modify events (e.g., add a "Time to First Token" event). So it creates its own `internalStreamChan`, passes *that* to the tool, and starts a goroutine to relay messages from `internalStreamChan` to `streamChan`.

3.  **The Source:** The `StreamTencentFrequentlyAsked` function is the ultimate source of the data. It's blissfully unaware of the client or the manager; its only job is to read from an HTTP stream and write the parsed events into the channel it was given (`internalStreamChan`).

This separation of concerns makes the system robust:
*   The **Manager** handles request lifecycle and state.
*   The **Streamer** orchestrates *how* a response is generated (cache, tool, or LLM).
*   The **Tool** is an expert in one thing: getting data from its specific source and streaming it.

This layered channel approach creates a direct, efficient, and fully managed data pipeline from the external RAG service straight to the end-user.
