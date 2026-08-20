---
title: "Data Driven Tool"
date: 2025-08-02
lastmod: 2026-07-10
draft: false
---

> 📌 **Must-read companion:** [Why We Built Our Own Pipeline Instead of Adopting an Off-the-Shelf Agent Framework](../custom_pipeline_vs_frameworks/) — how these data-driven tools are planned and executed by the custom plan-and-execute engine, and why that engine isn't a framework.

## 1. Overview: The Armory Philosophy

The term "data-driven" here doesn't mean it uses data analytics to make decisions. It means the system's fundamental capabilities—the tools themselves—are defined as declarative **data** structures, not as hard-coded imperative logic.

Think of it as the armory from *John Wick*. The core system—the rules of engagement, the process of selecting a weapon—is fixed and robust. The arsenal itself, however, can be infinitely expanded. Adding a new shotgun doesn't require rewriting the laws of physics or retraining John Wick; you simply add the weapon and its specifications to the inventory.

In our system:
- **The Armory Manifest:** `tools/toolcore/definitions.go`
- **The Weapons (Tools):** `DynamicTool` structs (`tools/toolcore/dynamic.go`)
- **The Rules of Engagement (The Engine):** `tools/toolcore/executor.go` and `tools/toolcore/pipeline/`
- **The Planner:** `tools/toolcore/planner/` for multi-step workflow planning

This design makes the system exceptionally maintainable, scalable, and robust, directly adhering to the Open/Closed Principle.

## 2. Core Components

The architecture relies on a few key components working in concert.

### A. The Contract: `tooltypes.LoggableTool` Interface

This is the "One Ring to rule them all." It is the non-negotiable contract that every tool in our system must honor.

```go
// tools/tooltypes/interfaces.go:15
type LoggableTool interface {
	// Returns the tool's name.
	Name() string

	// Returns the tool's description for the LLM.
	Description() string

	// Invokes the tool's standard, blocking executor function.
	Call(ctx context.Context, input string, logCtx zerolog.Logger) (string, error)

	// Invokes the tool's streaming executor function.
	// requestID travels via ctx (seeded by the pipeline's streaming adapter),
	// not as an explicit parameter — symmetric with the blocking Call path.
	Stream(ctx context.Context, input string, logCtx zerolog.Logger, streamChan chan<- types.StreamEvent) error

	// Converts the tool to the format the LLM needs for selection.
	ToLLMSchema() llms.Tool
}
```

Any struct that implements these methods can be treated as a tool by the core engine. This abstraction is critical. The engine doesn't care about the tool's specific implementation, only that it fulfills the contract.

### B. The Concrete Implementation: `toolcore.DynamicTool` Struct

This is our standard-issue weapon chassis. It's the concrete struct that implements the `LoggableTool` interface and holds all the metadata and logic for a single tool.

```go
// tools/toolcore/dynamic.go:40
type DynamicTool struct {
	NameStr        string             // Unique name identifier for the tool
	DescriptionStr string             // Human-readable description of what the tool does
	Schema         json.RawMessage    // JSON schema for the tool's input parameters
	Executor       executorFunc       // For standard, blocking tools
	StreamExecutor streamExecutorFunc // For streaming tools
}
```

- **`NameStr`**: The unique identifier for the tool (e.g., `news_summary`).
- **`DescriptionStr`**: The text given to the LLM so it knows when to use the tool. This is a critical prompt engineering component.
- **`Schema`**: The JSON schema defining the arguments the tool expects. This allows the LLM to format its requests correctly.
- **`Executor`**: Blocking executor (`executorFunc`, `dynamic.go:18`). Request-scoped values such as the `requestID` travel in `ctx`, so the signature stays uniform.
- **`StreamExecutor`**: A function pointer for streaming tools (`streamExecutorFunc`, `dynamic.go`). This is the "trigger"—the actual code that runs when the tool is streamed.

The tool supports two execution modes:
1. **Executor**: Standard blocking execution. A tool that needs the `requestID` reads it from `ctx` via `contextpkg.GetRequestIDFromContext` (seeded by `executor.go` before the closure runs).
2. **StreamExecutor**: Direct output streaming for natural-answer tools. `requestID` is seeded into `ctx` by `ToolStreamAdapter.CallWithStreaming` (`pipeline/streamingdir/adapter.go`) before `Stream` — and thus the `StreamExecutor` closure — runs (as of 2026-07-10, `Stream` itself carries no `requestID` parameter).

A compile-time assertion (`var _ tooltypes.LoggableTool = DynamicTool{}`, `dynamic.go:123`) guarantees the chassis always satisfies the contract.

### C. The Manifest: `tools/toolcore/definitions.go`

This file is the single source of truth for the system's capabilities. Its public entry point, `BuildAllTools`, assembles the complete slice of `DynamicTool` instances by composing a set of themed builder helpers (`buildSectorTools`, `buildFinancialDataTools`, `buildUserDataTools`, and so on):

```go
// tools/toolcore/definitions.go:566
func BuildAllTools(services *core.Services, arangoStore *db.ArangoStore, authStore interface{}) []DynamicTool {
	// Initialize shared auth provider for all tools
	if authStore != nil {
		if provider, ok := authStore.(toolutils.AuthDataProvider); ok {
			toolutils.InitializeAuthProvider(provider)
		}
	}

	// Build tools from separate helper functions
	allTools := make([]DynamicTool, 0, 30)
	allTools = append(allTools, buildSectorTools(services, arangoStore)...)
	allTools = append(allTools, buildStockInsightsTools(services, arangoStore)...)
	allTools = append(allTools, buildExternalSourceTools()...)
	allTools = append(allTools, buildStockPriceTools(services)...)
	allTools = append(allTools, buildOtherTools(services, arangoStore)...)
	allTools = append(allTools, buildRankingsTools(services)...)
	allTools = append(allTools, buildFinancialDataTools()...)
	allTools = append(allTools, buildMutualFundTools(services, arangoStore)...)
	allTools = append(allTools, buildMarketFlowTools(services)...)
	allTools = append(allTools, buildUserDataTools(services, arangoStore)...)

	// Filter out disabled tools
	filteredTools := filterDisabledTools(allTools, config.AppSettings.DisabledTools)

	// ... logging omitted ...

	return filteredTools
}
```

Each builder returns a slice of `DynamicTool` literals. A representative entry looks like this:

```go
// tools/toolcore/definitions.go (buildExternalSourceTools)
{
	NameStr:        "news_summary",
	DescriptionStr: newsSummaryDesc,   // From descriptions.go
	Schema:         codeArgsSchema,     // From schemas.go
	Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
		var args tooltypes.CodeArgs
		if err := json.Unmarshal([]byte(input), &args); err != nil {
			return "", fmt.Errorf("invalid arguments: %w", err)
		}
		return toolnonbe.NewsSummary(ctx, args.Code, logCtx)
	},
},
```

Some entries are terse one-liners that wire straight to a BE function, e.g.:

```go
// tools/toolcore/definitions.go:515-516 (buildMarketFlowTools)
{NameStr: "broker_summary", DescriptionStr: brokerSummaryDesc, Schema: brokerSummarySchema, Executor: toolbe.BrokerSummary},
{NameStr: "dominant_broker_analysis", DescriptionStr: dominantBrokerAnalysisDesc, Schema: dominantBrokerAnalysisSchema, Executor: toolbe.DominantBrokerAnalysis},
```

**Key Points:**
1. **Dependency Injection:** `services`, `arangoStore`, and `authStore` are passed in and captured by closures in each tool's executor.
2. **Schema Reuse:** Common schemas (like `codeArgsSchema`, `noArgsSchema`) are defined in `schemas.go`.
3. **Description Separation:** Tool descriptions are defined in `descriptions.go` for maintainability.
4. **Executor Closures:** Each tool's executor is a closure (or a direct function reference) that calls the real implementation in `toolbe/` or `toolnonbe/`.
5. **Tool Filtering:** Disabled tools (listed in `config.AppSettings.DisabledTools`) are filtered out via `filterDisabledTools` before returning (`definitions.go:70`).
6. **Feature Flags:** Some tools register conditionally. `query_user_short_term_memory` is only appended when `config.AppSettings.EnableUserShortTermMemory` is on (`definitions.go:550`).
7. **Streaming Support:** Tools can optionally define a `StreamExecutor` for direct output streaming (e.g., `frequently_asked`).

This is the **data** in "data-driven." It's a simple list, split across cohesive builders. The core engine consumes this list to understand what it can do.

### D. The Engine: `GetFormattedTools` & `PlanExecutor`

The engine is completely generic. `GetFormattedTools` iterates through the manifest and formats the data for different parts of the system:
1. A `map[string]tooltypes.LoggableTool` for quick lookups during execution.
2. A `[]llms.Tool` slice for the LLM to perform tool selection.

```go
// tools/toolcore/definitions.go:105
func GetFormattedTools(allTools []DynamicTool) (map[string]tooltypes.LoggableTool, []llms.Tool) {
	availableTools := make(map[string]tooltypes.LoggableTool, len(allTools))
	llmTools := make([]llms.Tool, 0, len(allTools))
	for i := range allTools {
		tool := allTools[i] // Important: create a local copy for the map
		availableTools[tool.Name()] = tool
		llmTools = append(llmTools, tool.ToLLMSchema())
	}
	return availableTools, llmTools
}
```

**Usage in `chatbot/manager_core.go`:**
```go
// chatbot/manager_core.go:115
dynamicTools := toolcore.BuildAllTools(services, arangoStore, authProvider)
availableTools, llmTools := toolcore.GetFormattedTools(dynamicTools)

// ... Manager constructed with availableTools / llmTools stored on it (manager_core.go:137-138) ...

// Create PlanExecutor for pipeline execution (manager_core.go:205)
planExecutor := toolcore.NewPlanExecutor(availableTools)
```

The `PlanExecutor` is a thin wrapper around the `executor.Executor` (from `tools/toolcore/executor/`), providing the interface that the processing layer expects:

```go
// tools/toolcore/executor.go:45
type PlanExecutor struct {
	exec *executor.Executor
}

// tools/toolcore/executor.go:53
func NewPlanExecutor(availableTools map[string]tooltypes.LoggableTool) *PlanExecutor {
	return &PlanExecutor{
		exec: executor.NewExecutor(availableTools),
	}
}

// Implements processing.ExecutionPlanJSONParser (executor.go:66)
func (e *PlanExecutor) ParseExecutionPlanFromJSON(jsonStr string) (*pipeline.ExecutionPlan, error)

// Implements processing.ToolExecutorFromPlan (executor.go:80)
func (e *PlanExecutor) ExecuteFromPlan(
	ctx context.Context,
	plan *pipeline.ExecutionPlan,
	availableTools map[string]tooltypes.LoggableTool,
	toolTokenizer *tiktoken.Tiktoken,
	stateUpdater types.StateUpdaterInterface,
	requestID string,
	toolInputTokens int,
	logCtx zerolog.Logger,
	llm types.LLMInterface,
	llmTools []llms.Tool,
	formattedHistory, question string,
) (tooltypes.ToolPreparationResult, error)
```

Both interface implementations are asserted at compile time (`executor.go:111`).

## 3. Pipeline Architecture

The system has evolved beyond simple single-tool execution to support sophisticated multi-step workflows.

### A. Pipeline Execution (`tools/toolcore/pipeline/`)

The pipeline package orchestrates multi-tool workflows with dependency management (test files and `.workflows/` omitted):

```
tools/toolcore/pipeline/
├── types.go               # Re-exports from subdirectories for API convenience
├── helpers.go             # Package-level helper functions
├── types/                 # Core type definitions
│   ├── plan.go            # ExecutionPlan, PipelineStep, ToolSpec, SimpleToolCall, MapSourceConfig, ...
│   ├── metrics.go         # ExecutionMetrics, StepExecutionMetrics
│   ├── retry.go           # RetryConfig, RetryableOperation
│   ├── patterns.go        # Pattern helpers
│   └── synthesizer.go     # Synthesizer types
├── ctx/                   # Context management
│   ├── manager.go         # ContextManager for step output storage
│   └── resolver.go        # Field path resolution (GetFieldByPath)
├── execution/             # Pipeline execution orchestration
│   ├── executor.go        # PipelineExecutor main orchestration
│   ├── step.go            # Step execution logic
│   ├── tool.go            # Tool execution logic
│   ├── modes.go           # Execution mode routing
│   ├── single.go          # Sequential tool execution
│   ├── parallel.go        # Concurrent tool execution
│   ├── map.go             # Array iteration with map operations
│   ├── map_iteration.go   # Per-iteration map execution
│   ├── map_results.go     # Map result assembly
│   ├── map_substitution.go# Argument substitution for map steps
│   ├── map_tool_filter.go # Per-iteration tool filtering
│   ├── map_fallback.go    # Map extraction fallbacks
│   ├── aggregation.go     # Data aggregation steps
│   ├── dag.go             # DAG-based dependency ordering
│   ├── cache.go           # Step/tool result caching
│   └── helpers.go         # Helper functions
├── retrydir/              # Retry logic with circuit breaker
│   └── retry.go
├── streamingdir/          # Streaming adapters for tool execution
│   └── adapter.go
├── transforms/            # Data transformation utilities
│   └── transforms.go
├── fallback/              # LLM fallback mechanisms
│   └── llm.go
└── validation/            # Plan and step validation
    ├── validator.go
    ├── plan.go
    ├── step.go
    └── dependencies.go
```

### B. Execution Modes

1. **Single**: Execute one tool, wait for result
2. **Parallel**: Execute multiple tools concurrently
3. **Map**: Iterate over a collection, executing tools for each item
4. **Aggregation**: Combine outputs from previous steps for external synthesis

### C. Pipeline Plan Structure

The plan types live in `tools/toolcore/pipeline/types/plan.go` and are re-exported through `pipeline/types.go`:

```go
// tools/toolcore/pipeline/types/plan.go:144
type ExecutionPlan struct {
	Mode      string `json:"mode"`      // "simple", "pipeline", or "fixed_answer"
	Reasoning string `json:"reasoning"` // Why this mode was chosen

	// For Simple Mode
	Tools []SimpleToolCall `json:"tools,omitempty"` // Selected tools (parsed from JSON)

	// For Pipeline Mode
	EstimatedSteps int            `json:"estimated_steps,omitempty"`
	Steps          []PipelineStep `json:"steps,omitempty"`

	// For Fixed Answer Mode
	FixedAnswer *FixedAnswerConfig `json:"fixed_answer,omitempty"`

	// Internal field - not serialized to JSON
	OriginalJSON string `json:"-"` // Original LLM output before post-processing
}

// tools/toolcore/pipeline/types/plan.go:45
type PipelineStep struct {
	ID                string                 `json:"id"`
	Type              string                 `json:"type"`                          // "tool_call", "llm_decision"
	Description       string                 `json:"description"`
	ExecutionMode     string                 `json:"execution_mode,omitempty"`      // "single", "parallel", "map"
	Tools             []ToolSpec             `json:"tools,omitempty"`
	IsDirectStream    bool                   `json:"is_direct_stream,omitempty"`
	AggregationMode   bool                   `json:"aggregation_mode,omitempty"`
	MapSource         *MapSourceConfig       `json:"map_source,omitempty"`
	Context           map[string]interface{} `json:"context,omitempty"`
	ParallelLimit     int                    `json:"parallel_limit,omitempty"`
	EnableParallelMap bool                   `json:"enable_parallel_map,omitempty"`
}

// tools/toolcore/pipeline/types/plan.go:62
type ToolSpec struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments"` // may include DependencyReference values
}

// tools/toolcore/pipeline/types/plan.go:127
type SimpleToolCall struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments"`
}
```

Steps reference each other's output via `DependencyReference` (`plan.go:89`), and map steps configure iteration with `MapSourceConfig` (`plan.go:75`). The `fixed_answer` mode short-circuits tool execution with a predefined `FixedAnswerConfig` (`plan.go:98`)—used, for example, for prompt-injection guards.

## 4. Planner System (`tools/toolcore/planner/`)

The planner handles plan parsing, validation, correction, and dependency wiring (test files and `.workflows/` omitted):

```
tools/toolcore/planner/
├── planner.go             # Main planner orchestration
├── parser.go              # JSON parsing with trailing comma handling
├── postprocess.go         # Post-processing corrections
├── extractor.go           # Extraction helpers for plan fields
├── consts/                # Constants and configuration
│   └── constants.go
├── validation/            # Plan validation logic
│   ├── first.go           # First-step validation
│   ├── plan.go
│   ├── stream.go
│   └── transform.go
├── dependency/            # Dependency management
│   ├── detect.go          # Automatic dependency detection
│   ├── convert.go         # Dependency conversion
│   ├── remove.go          # Unused dependency removal
│   └── compare_stocks.go  # compare_stocks-specific enforcement rules
├── correction/            # Plan correction algorithms
│   ├── parallel.go
│   └── transform.go
├── schema/                # Schema enforcement
│   ├── enforce.go
│   └── transform.go
└── aggregation/           # Data aggregation logic
    └── builder.go
```

Note: `compare_stocks` is no longer a standalone registered tool. It survives here only as a planner enforcement rule (`dependency/compare_stocks.go`) that ensures any `compare_stocks` step is correctly preceded by a map step.

## 5. The Open/Closed Principle (OCP) in Action

OCP states:

> **Software entities (classes, modules, functions, etc.) should be open for extension, but closed for modification.**

Let's apply this to your code. It's a textbook example.

* **Open for Extension:** You can extend the chatbot's capabilities by adding new tools. You do this by adding a new `DynamicTool{...}` entry to the appropriate builder in `tools/toolcore/definitions.go`. The system's functionality grows.
* **Closed for Modification:** To add that new tool, you did **not** have to modify `executor.go`, `pipeline/`, `planner/`, or `dynamic.go`. Those core components are "closed." They are stable, tested, and don't need to be changed to support the new functionality. They are like the Terminator's chassis—the endoskeleton is fixed, but you can give it different weapon loadouts (the tools).

#### How to Add a New Tool (The Right Way)

1. **Implement the Logic:** Write the executor function, for example, a new `GetCompanyCompetitors` function in `toolbe`.
2. **Define the Schema:** Create or reuse a JSON schema in `schemas.go`.
3. **Define the Description:** Add the tool description in `descriptions.go`.
4. **Add to the Manifest:** Add a new `DynamicTool{...}` struct to the appropriate builder helper in `tools/toolcore/definitions.go`, wiring up the name, description, schema, and executor function.

That's it. You have extended the system's functionality without modifying a single line of the core engine's code.

#### The Wrong Way (Violating OCP)

Imagine if tool execution looked like this:

```go
// THIS IS THE PATH TO THE DARK SIDE. BRITTLE AND PAINFUL.
func executeTool(call llms.ToolCall) {
    switch call.FunctionCall.Name {
    case "get_current_time":
        // ...
    case "news_summary":
        // ...
    // To add a tool, you'd add:
    // case "get_company_competitors":
    //     // new logic here...
    }
}
```

This is a nightmare. It's tightly coupled, hard to test, and every change carries the risk of breaking existing functionality. It's the difference between adding a new app to your phone versus needing the manufacturer to issue a full firmware update for every new app.

## 6. Architectural Prowess: The Payoff

This data-driven design delivers significant advantages:

1. **Extreme Maintainability:** Tool logic is self-contained. A bug in the `financial_annualreport` tool is isolated to its executor function, not entangled in a 500-line `switch` statement. You can fix or modify a tool with minimal risk to the rest of the system, like swapping a component in a modular rifle.
2. **Effortless Scalability:** Adding the 100th tool is no more complex than adding the 1st. The core engine's complexity does not increase as the number of tools grows.
3. **Superior Testability:** Each tool's executor can be unit-tested in complete isolation. The core engine can be tested with a set of mock tools to ensure its orchestration logic is sound.
4. **Clarity and Single Source of Truth:** To understand the full capabilities of the chatbot, a developer only needs to read one file: `tools/toolcore/definitions.go`. It's the Marauder's Map of our system—it shows you everything.
5. **Sophisticated Workflows:** The pipeline architecture enables complex multi-step tool workflows with automatic dependency resolution, parallel execution, and intelligent error handling.

By separating the *what* (the data in `definitions.go`) from the *how* (the generic logic in `pipeline/`), the architecture remains clean, robust, and ready for future expansion without collapsing under its own weight.

## 7. Current Tool Inventory (31 Tool Definitions)

As of 2026-07-09, `BuildAllTools` defines **31 tools** across its builder helpers. Note that `query_user_short_term_memory` is registered only when `EnableUserShortTermMemory` is on, so a default deployment exposes 30 tools; any names in `config.AppSettings.DisabledTools` are filtered out at build time.

| Category | Tools |
|----------|-------|
| **Market Data** | `realtime_market`, `historical_marketdata`, `stock_ranks` |
| **Market Flow / Broker** | `foreign_flow`, `broker_summary`, `dominant_broker_analysis` |
| **Financial Reports** | `financial_annualreport`, `financial_quarterreport`, `financial_ttmreport`, `financial_ytdreport` |
| **Financial Ratios** | `financial_profitability_ratio`, `financial_solvency_ratio`, `financial_valuation_ratio`, `financial_dividend_ratio` |
| **Analysis** | `stock_analysis`, `stock_analysis_from_research`, `company_overview`, `mutual_fund_analysis` |
| **Selection** | `stock_selection`, `mutual_fund_selection`, `mutual_fund_selection_v2` |
| **Sector / Search** | `concept_sector_search`, `concept_sector_search_by_stock_code`, `web_search` |
| **User Tools** | `query_user_portfolio`, `query_user_memory`, `query_user_watchlist`, `query_user_short_term_memory` (feature-flagged) |
| **Natural Answer** | `frequently_asked`, `news_summary` |
| **Utilities** | `get_current_time` |

> Changes since the previous inventory: `dominant_broker_analysis` and `query_user_short_term_memory` were added; `compare_stocks` was removed as a registered tool (it now exists only as a planner enforcement rule—see §4).

## 8. Common Misconceptions: Addressing "God Function" Concerns

### Misconception: "BuildAllTools is a large function"

**Reality:** `BuildAllTools` is not a function with lines of **logic**. It composes themed builder helpers, each of which returns a **data structure**—a catalog of tools, each defined in ~15-20 lines.

```go
// This is NOT "logic":
{
    NameStr:        "news_summary",
    DescriptionStr: newsSummaryDesc,  // Reference to descriptions.go
    Schema:         codeArgsSchema,    // Reference to schemas.go
    Executor: func(...) { /* 1-2 lines calling the real implementation */ },
}

// This IS "logic" (what you'd find in a god function):
if toolName == "news_summary" {
    // 20 lines of conditional logic
} else if toolName == "stock_analysis" {
    // 20 more lines of conditional logic
} // ... repeat for 31 tools
```

The distinction matters. The first example is **declarative data**. The second is **imperative logic** with cyclomatic complexity.

### Misconception: "The code is repetitive"

**Reality:** The repetition is **31 similar data entries**, not duplicate logic. This is like calling a CSV file "repetitive code" because each row follows the same format.

Each ~15-20-line block defines:
1. A name (string)
2. A description (string reference to `descriptions.go`)
3. A schema (json.RawMessage reference to `schemas.go`)
4. An executor closure (1-2 lines of actual logic, calling the real implementation)

**The real logic lives in `toolbe/` and `toolnonbe/` packages**, not in `definitions.go`.

### Misconception: "We should use a factory pattern"

**Reality:** We already have a factory pattern. `BuildAllTools` (and its builder helpers) IS the factory. What would a separate factory pattern add?

```go
// Current approach (declarative):
tools := []DynamicTool{
    {NameStr: "tool1", Executor: func() {...}},
    {NameStr: "tool2", Executor: func() {...}},
}

// "Factory pattern" approach (what???):
func CreateTool1() DynamicTool { return DynamicTool{...} }
func CreateTool2() DynamicTool { return DynamicTool{...} }
tools := []DynamicTool{CreateTool1(), CreateTool2()}
```

The second approach adds indirection without removing complexity. It's just moving the data around.

### Misconception: "We should move to external configuration (JSON/YAML)"

**Reality:** This would make things worse:

| Current Approach | External Config (JSON/YAML) |
|------------------|-----------------------------|
| Compile-time type safety | Runtime errors only |
| IDE jump-to-definition works | Can't navigate from config to code |
| Closures capture dependencies naturally | Can't serialize closures; need reflection |
| Refactoring tools automatically updates schema | Must manually sync config and code |
| Schema is typed json.RawMessage | Schema is string; no validation until runtime |

### Misconception: "The file is too long"

**Reality:** With 31 tools split across themed builder helpers and descriptions/schemas separated into their own files, `definitions.go` is well-organized. Of the ~15-20 lines per tool:
- ~5 lines for the struct fields (name, description, schema, executor)
- ~8 lines for the executor closure (mostly argument unmarshaling)
- ~5 lines of closing braces and formatting

**Only ~8 lines per tool are actual "code."** The rest is data or references to external files. (Note that several entries—e.g. `broker_summary`, `dominant_broker_analysis`—are single-line references to a BE function, which is even leaner.)

If this becomes a problem at 50+ tools, we can split the builders into their own files (financial_tools.go, market_tools.go, etc.)—but this is an organizational change, not an architectural one.

### When Would This Architecture Need to Change?

**Consider changing if:**
1. You need hot-reload of tools without restarting the server (rare for production systems)
2. You have 100+ tools and merge conflicts are unbearable (organizational, not architectural)
3. You need to dynamically load tools from plugins (legitimate use case, but different architecture entirely)

**Don't change because:**
1. A linter says the file is "too long" (it's data, not code)
2. "Clean code" principles say to avoid repetition (this isn't duplicate logic)
3. Someone wants to extract a "factory pattern" (we already have one)

## 9. Summary

This architecture is **intentional, documented, and effective**. It follows the Open/Closed Principle by being:
- **Open for extension:** Add new tools by adding data to a builder in the manifest
- **Closed for modification:** Core engine code never changes when adding tools

The "data-driven" name is accurate. The tools are defined as data structures. The engine consumes that data to do its job. This is not a bug. It's a feature.

The evolution to include pipeline execution and sophisticated planning has only strengthened this architecture—the core data-driven tool registry remains unchanged, while the pipeline layer provides powerful workflow orchestration on top of it.
