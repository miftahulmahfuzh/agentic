---
title: "RAG Stream"
date: 2025-08-02
draft: false
---

# Architectural Blueprint: Dual-Path Request Processing

## 1. Core Principle: No-Nonsense Efficiency

This system does not use a one-size-fits-all approach. That's inefficient and expensive. Instead, it operates on a dual-path architecture designed to segregate requests based on complexity. Like Anton Chigurh, it chooses the right tool for the job, without sentiment.

The architecture features two distinct processing pathways, chosen dynamically by an LLM router:

1.  **The Agentic Synthesis Loop:** For complex, multi-faceted queries requiring data fusion from several sources. This is the thinking path. It's powerful but slow and expensive.
2.  **Direct Stream Passthrough:** For simple, factual queries that can be answered by a single, authoritative source (like a RAG knowledge base). This is the knowing path. It's brutally fast, cheap, and high-fidelity.

An LLM-based router in `toolcore.SelectAndPrepareTools` inspects every query and routes it down the appropriate path. Simple questions get fast, direct answers. Complex questions get the full analytical power of the agentic engine. We don't waste compute cycles on questions a simple lookup can solve.

## 2. The Processing Pathways

### Path 1: The Agentic Synthesis Loop (The "Goodfellas" Crew)

This is the multi-step, heavy-hitting path for queries that need more than a simple answer. It assembles a crew of tools to pull off a job.

**Use Case:** "Compare BBCA's profitability ratios to its historical stock performance over the last year and summarize any relevant news."

**Execution Flow:**

1.  **The Sit-Down (LLM Call #1):** The query enters `toolcore.SelectAndPrepareTools`. The LLM acts as a capo, assessing the job and assigning a crew of tools (e.g., `financial_profitability_ratio`, `historical_marketdata`, `news_summary`). This is the first LLM call.
2.  **The Heist (Parallel Tool Execution):** The system calls `toolutils.ExecuteToolsInParallel`. Each tool's standard `Call()` method is invoked. They run concurrently to gather their piece of the score—raw JSON data, news text, etc.
3.  **The Kick-Up (LLM Call #2):** The raw outputs from all tools are consolidated into a single context. This context, plus the original query, is fed to the LLM a second time within the response streaming component. The LLM's job is to synthesize this raw intelligence into a coherent, human-readable answer. This is the second, more expensive LLM call.

**Operational Reality:**

*   **Capability:** Handles intricate, multi-domain questions that require reasoning.
*   **Latency:** High. The total time is `LLM_Call_1 + max(Tool_Execution_Time) + LLM_Call_2`.
*   **Cost:** High. Two LLM calls. The second (synthesis) call can be token-heavy.
*   **Fidelity:** The final answer is an LLM *interpretation* of the tool data. There is a non-zero risk of hallucination, like a witness getting the facts wrong.

### Path 2: Direct Stream Passthrough (The "John Wick" Path)

This is the surgical, high-speed path. It is engaged when the router identifies that a query can be answered by a single, designated "Natural Answer" tool that supports streaming. It executes with a singular, brutal efficiency.

**Use Case:** "How do I register on the Tuntun application?"

**Execution Flow:**

1.  **Target Acquisition (LLM Call #1):** In `toolcore.SelectAndPrepareTools`, the LLM router sees the query and recognizes it can be handled by the `frequently_asked` RAG tool alone. It generates a single tool call for it and returns, setting `IsDirectStream: true`. Its job is done.
2.  **Execution (Bypass and Stream):** The `Manager` sees the `IsDirectStream` flag and **skips the second LLM call entirely**. It invokes the tool's dedicated `.Stream()` method (`toolnonbe.StreamTencentFrequentlyAsked`). This method pipes the response from the underlying RAG service directly to the user, token by token. The synthesis loop is completely bypassed.

**Operational Reality:**

*   **Speed:** Maximum velocity. Latency is reduced to a single, small LLM call plus the Time-To-First-Token of the RAG service.
*   **Cost:** Minimal. We pay for one cheap tool-selection call. High-volume FAQ traffic becomes financially trivial.
*   **Fidelity:** Absolute. The user gets the raw, unaltered truth from the knowledge base. There is **zero chance** of LLM misinterpretation because the LLM never touches the answer content.

## 3. The Dual-Mode Tool: A Tool for Two Paths

The key to this architecture's flexibility is not just having two paths, but having tools that can walk both.

The `frequently_asked` RAG tool, as defined in `toolcore/definitions.go`, is the prime example. It implements the `tooltypes.LoggableTool` interface by providing **two distinct executors**:
1.  **`Executor` (the `Call` method):** A standard, blocking function that returns a complete string. This is used when the RAG tool is just one member of a multi-tool crew in the **Agentic Synthesis Loop (Path 1)**.
2.  **`StreamExecutor` (the `Stream` method):** A streaming function that pipes data to a channel. This is used when the RAG tool is chosen for a solo mission in the **Direct Stream Passthrough (Path 2)**.

This dual implementation is a deliberate design choice. It allows the system to leverage the same authoritative RAG knowledge base in the most efficient manner possible based on the query's context. It's either a contributing member of a team or a lone operative, and the system decides which role it plays.

## 4. Architectural Resilience: The Fallback Protocol

"Hope is not a strategy." The system is built to anticipate failure. The response streaming component has a fallback protocol. If Path 2 is chosen (Direct Stream) but the tool's `Stream()` method fails or returns no data, the system doesn't just die. It reverts, treating the failure as if Path 1 was chosen all along. It takes the original query, notes the tool failure, and proceeds to the **Agentic Synthesis Loop (Path 1, LLM Call #2)** to try and generate an answer from the available information. This ensures robustness. The mission succeeds, even if the primary plan goes sideways.

## 5. Visual Architecture

This diagram shows the decision point and the two pathways of the dual pathways, including the fallback.

{{< mermaid >}}
graph TD
    subgraph UserInputLayer ["User Input Layer"]
        UserQuery["User Query"]
    end

    subgraph DecisionLayer ["Routing & Decision Layer"]
        LLMRouter["LLM-based Router<br/>Tool Selection & Path Determination"]
    end

    subgraph ProcessingPathways ["Processing Pathways"]
        subgraph AgenticPathway ["Path 1: Agentic Synthesis Pathway"]
            direction TB
            ToolExecution["Concurrent Tool Execution<br/>Standard_Call() Invocation"]
            LLMSynthesis["LLM-based Synthesis<br/>Consolidates Tool Outputs into a Final Response"]
            ToolExecution --> LLMSynthesis
        end

        subgraph DirectPathway ["Path 2: Direct Stream Pathway"]
            direction TB
            DirectToolStream["Direct Tool Stream<br/>Special_Stream() Invocation<br/>Bypasses Synthesis Stage"]
        end
    end

    subgraph ResponseLayer ["Response Generation Layer"]
        StreamedResponse["Streamed Response to Client"]
    end

    %% Flow Connections
    UserQuery --> LLMRouter
    LLMRouter -- "Complex Query<br/>(Multiple Tools Selected)" --> ToolExecution
    LLMRouter -- "Simple Query<br/>(Single Streaming Tool Selected)" --> DirectToolStream
    LLMSynthesis --> StreamedResponse
    DirectToolStream --> StreamedResponse
    DirectToolStream -. "Fallback on Stream Failure" .-> LLMSynthesis

    %% Styling Definitions
    classDef userInputStyle fill:#e3f2fd,stroke:#1976d2,stroke-width:2px,color:#0d47a1
    classDef decisionStyle fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#4a148c
    classDef agenticStyle fill:#fff3e0,stroke:#f57c00,stroke-width:2px,color:#e65100
    classDef directStyle fill:#e8f5e8,stroke:#388e3c,stroke-width:2px,color:#1b5e20
    classDef responseStyle fill:#fce4ec,stroke:#c2185b,stroke-width:2px,color:#880e4f
    classDef pathwayContainer fill:#f8f9fa,stroke:#6c757d,stroke-width:1px,stroke-dasharray: 5 5

    %% Class Assignments
    class UserInputLayer userInputStyle
    class DecisionLayer decisionStyle
    class AgenticPathway agenticStyle
    class DirectPathway directStyle
    class ResponseLayer responseStyle
    class ProcessingPathways pathwayContainer
{{< /mermaid >}}

## 6. Side-by-Side Tactical Comparison

| Feature               | Path 1: Agentic Synthesis Loop (The Strategist)                                | Path 2: Direct Stream Passthrough (The Specialist)                                    |
| :-------------------- | :----------------------------------------------------------------------------- | :------------------------------------------------------------------------------------ |
| **Core Task**         | Analysis, Reasoning, Data Fusion                                               | Factual Recall, Direct Retrieval                                                      |
| **Latency**           | High (2 LLM calls + Tool execution)                                            | **Low** (1 LLM call + RAG stream TTFT)                                                |
| **API Cost**          | High (2 LLM API calls)                                                         | **Low** (1 small LLM API call)                                                        |
| **Data Fidelity**     | Interpreted by LLM. Risk of hallucination.                                     | **Absolute.** Direct from the source of truth. Zero interpretation risk.              |
| **Tool Method Used**  | Standard `tool.Call()` for all selected tools.                                 | Specialized `tool.Stream()` for the single selected tool.                             |
| **Best Use Case**     | "What should I think about this data?"                                         | "What is the data?"                                                                   |

## 7. Conclusion

This dual-path architecture is not a fancy feature; it's a fundamental requirement for a production-grade system that balances capability with cost and performance. It intelligently applies force where needed and finesse where it's most effective. One path is for complex reasoning, the other is for delivering hard facts with extreme prejudice. A professional system knows the difference and acts accordingly.

**Related QA:** [RAG Q&A 1](https://miftahulmahfuzh.github.io/agentic/docs/frequently_asked/rag_qa_1)
