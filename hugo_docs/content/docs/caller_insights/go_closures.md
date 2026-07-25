---
title: "Go Closures"
date: 2026-07-25
draft: false
---

## Overview: How Dependencies Persist Through LLM Decision Making

A defining characteristic of this agentic chatbot is the way build-time dependencies such as `services.LLM`, `services.Tokenizer`, and `arangoStore` remain available to a tool at execution time, even though only the tool's input parameters ever flow through the LLM decision-making pipeline.

This document explains that pattern using Go closures. It shows how the system maintains a clean separation between **dependency injection** (resolved once, at build time) and **runtime parameters** (chosen per request by the LLM). The pattern is a deliberate, framework-free approach to dependency injection.

## The Problem: Two Distinct Data Flows

When reading the tool definitions, a reasonable question arises. A tool executor closure has access to service dependencies it never received as a call argument:

```go
// In tools/toolcore/definitions.go - buildStockInsightsTools()
Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
    var args struct {
        Code      string `json:"code"`
        Summarize bool   `json:"summarize"`
    }
    if err := json.Unmarshal([]byte(input), &args); err != nil {
        return "", fmt.Errorf("invalid arguments: %w", err)
    }
    // How does this closure still reach services.LLM, services.Tokenizer,
    // and arangoStore? They came from BuildAllTools(services, arangoStore, authStore),
    // yet only 'input' flows through the LLM.
    return toolnonbe.StockAnalysisFromResearch(
        ctx, args.Code, args.Summarize,
        services.LLM, services.Tokenizer, logCtx, arangoStore,
    )
},
```

The explanation is that there are two separate parameter flows:

1. **Dependency Flow** (build time): `services.LLM`, `services.Tokenizer`, `arangoStore` — captured when the tool is defined.
2. **Runtime Flow** (execution time): the `input` string — LLM-chosen parameters supplied per request.

## The Complete Data Flow: From Bootstrap to Execution

The following steps trace the full journey.

### Step 1: Tool Definition (Bootstrap Time)

Tools are constructed by `BuildAllTools`, which fans out to per-domain helper functions. Each helper receives the shared dependencies and returns `[]DynamicTool`. The current signature is:

```go
// In tools/toolcore/definitions.go
func BuildAllTools(services *core.Services, arangoStore *db.ArangoStore, authStore interface{}) []DynamicTool {
    // Auth is registered once as a shared provider rather than captured per-closure.
    if authStore != nil {
        if provider, ok := authStore.(toolutils.AuthDataProvider); ok {
            toolutils.InitializeAuthProvider(provider)
        }
    }

    allTools := make([]DynamicTool, 0, 30)
    allTools = append(allTools, buildSectorTools(services, arangoStore)...)
    allTools = append(allTools, buildStockInsightsTools(services, arangoStore)...)
    // ... additional domain groups ...
    allTools = append(allTools, buildUserDataTools(services, arangoStore)...)

    return filterDisabledTools(allTools, config.AppSettings.DisabledTools)
}
```

Inside a helper such as `buildSectorTools`, the executor is an anonymous function that references the captured `services` and `arangoStore` values. This reference is what forms the closure:

```go
// In tools/toolcore/definitions.go - buildSectorTools()
{
    NameStr:        "concept_sector_search",
    DescriptionStr: conceptSectorSearchDesc,
    Schema:         conceptSectorSchema,

    // This function captures services and arangoStore from the enclosing scope.
    Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
        // services.LLM, services.Tokenizer, services.DataStore, and arangoStore
        // remain reachable here. Go captured them when this function value was created.

        // Parse the LLM-chosen parameters.
        var args tooltypes.ConceptSectorSearchArgs
        if err := json.Unmarshal([]byte(input), &args); err != nil {
            return "", fmt.Errorf("invalid arguments: %w", err)
        }

        // Combine build-time dependencies with runtime parameters.
        return toolbe.ConceptSectorSearchUsingLLM(
            ctx,
            args.Query,          // from LLM input
            args.Language,       // from LLM input
            args.TopN,           // from LLM input
            logCtx,              // from runtime
            services.LLM,        // captured build-time dependency
            services.Tokenizer,  // captured build-time dependency
            services.DataStore,  // captured build-time dependency
            arangoStore,         // captured build-time dependency
        )
    },
},
```

A tool may instead expose a **streaming** executor. The `DynamicTool` struct
(`tools/toolcore/dynamic.go`) carries two optional executor fields, exactly
one of which is set per tool. Request-scoped values such as the `requestID`
travel in `ctx` rather than as executor parameters, which keeps both signatures
uniform:

```go
// In tools/toolcore/dynamic.go
type executorFunc func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error)

type streamExecutorFunc func(ctx context.Context, input string, logCtx zerolog.Logger, streamChan chan<- types.StreamEvent) error

type DynamicTool struct {
    NameStr        string
    DescriptionStr string
    Schema         json.RawMessage
    Executor       executorFunc       // standard blocking tool
    StreamExecutor streamExecutorFunc // streaming tool
}
```

The one streaming tool registered today, `frequently_asked`, uses the
`StreamExecutor` field. When it needs the `requestID` it reads it from `ctx`
via `contextpkg.GetRequestIDFromContextOrDefault`, the same source blocking
tools use:

```go
// In tools/toolcore/definitions.go - buildExternalSourceTools()
StreamExecutor: func(ctx context.Context, input string, logCtx zerolog.Logger, streamChan chan<- types.StreamEvent) error {
    var args tooltypes.QueryArgs
    if err := json.Unmarshal([]byte(input), &args); err != nil {
        return fmt.Errorf("invalid arguments: %w", err)
    }
    requestID := contextpkg.GetRequestIDFromContextOrDefault(ctx, "")
    return toolnonbe.StreamTencentFrequentlyAsked(ctx, requestID, args.Query, logCtx, streamChan)
},
```

Unlike the blocking path, `DynamicTool.Stream` itself takes no `requestID`
parameter at all (as of 2026-07-10, P3-TC-A098). The boundary that bridges the
two worlds moved one level up: `ToolStreamAdapter.CallWithStreaming`
(`tools/toolcore/pipeline/streamingdir/adapter.go`), which is the streaming
framework's entry point and already holds `tsa.RequestID`, seeds it into `ctx`
(`streamCtx := requestcontext.WithRequestID(ctx, tsa.RequestID)`) immediately
before calling `tsa.Tool.Stream(streamCtx, ...)`. The closure therefore never
receives `requestID` directly — it reads it from `ctx`, exactly as the blocking
path does after `executor.go` seeds it.

### Step 2: Manager Initialization

`NewManager` constructs the auth provider, builds the tools (capturing dependencies in closures), and formats them for the LLM:

```go
// In chatbot/manager_core.go - NewManager()
func NewManager(
    ctx context.Context,
    cfg *config.Settings,
    services *core.Services,
    arangoStore *db.ArangoStore,
    fixedAnswersLoader *fixedanswers.Loader,
) (*Manager, error) {
    var authProvider interface{}
    // ... authProvider is derived from the auth Redis store when available ...

    // Build tools with dependencies captured in closures.
    dynamicTools := toolcore.BuildAllTools(services, arangoStore, authProvider)

    // At this point, every tool's executor closure has captured the dependencies
    // it references (for example services.LLM, services.Tokenizer, arangoStore).

    // GetFormattedTools returns a name->tool lookup map and the []llms.Tool schema list.
    availableTools, llmTools := toolcore.GetFormattedTools(dynamicTools)

    return &Manager{
        // availableTools and llmTools are retained for the lifetime of the manager.
        // ... other fields ...
    }, nil
}
```

`GetFormattedTools` has the signature:

```go
// In tools/toolcore/definitions.go
func GetFormattedTools(allTools []DynamicTool) (map[string]tooltypes.LoggableTool, []llms.Tool)
```

The map (`availableTools`) is later consulted by the pipeline executor to resolve a tool by name; the `[]llms.Tool` (`llmTools`) is the schema list handed to the planner so the LLM knows which tools exist.

### Step 3: Planning and Tool Selection (Runtime)

Tool selection is performed by the **planner** subsystem (`tools/toolcore/planner`), not by any single "prepare" function. The entry point is `Planner.PlanOnly`, which delegates to `ClassifyAndPlan`:

```go
// In tools/toolcore/planner/planner.go
func (p *Planner) PlanOnly(
    ctx context.Context,
    logCtx zerolog.Logger,
    llm types.LLMInterface,
    tokenizer *tiktoken.Tiktoken,
    formattedHistory, question string,
    llmTools []llms.Tool,
    userQueryTimestamp time.Time,
) (*types.PlanningResult, error) {
    // ...
    executionPlan, err := ClassifyAndPlan(ctx, question, formattedHistory, llm, llmTools, logCtx)
    // ...
}
```

`ClassifyAndPlan` prompts the LLM with the tool schemas (`llmTools`) and returns an `*pipeline.ExecutionPlan`. The plan names the tools to run and the arguments to pass, for example:

```json
{
  "mode": "...",
  "steps": [
    {
      "tool": "concept_sector_search",
      "arguments": "{\"query\": \"banking sector leaders\", \"language\": \"en\", \"top_n\": 5}"
    }
  ]
}
```

Only the tool name and its arguments are decided by the LLM. The dependencies were already captured in the closures during Step 1, so they do not appear in the plan.

> Historical note: an earlier version of this system routed selection through a `SelectAndPrepareTools` function in a `tools/toolcore/caller.go` file. Both have been removed. Selection and planning now live entirely in the `planner` subsystem, and execution lives in the `pipeline`/`executor` subsystem. See `CLAUDE.md` section 2 for the current subsystem map.

### Step 4: Tool Execution (Runtime)

The pipeline executor runs the plan. For a direct streaming step, the relevant function is `PipelineExecutor.executeToolCallStepWithStreaming` in `tools/toolcore/pipeline/execution/tool.go`:

```go
// In tools/toolcore/pipeline/execution/tool.go
func (pe *PipelineExecutor) executeToolCallStepWithStreaming(
    ctx context.Context,
    step *pipelinetypes.PipelineStep,
    streamChan chan<- string,
    metrics *pipelinetypes.StepExecutionMetrics,
) (string, error) {
    // ... resolve the step's single tool ...
    toolSpec := resolvedTools[0]

    // Resolve the tool by name from the map produced by GetFormattedTools.
    tool, argsJSON, err := validateAndPrepareTool(toolSpec, pe.dependencies.AvailableTools)
    if err != nil {
        return "", fmt.Errorf("failed to validate and prepare tool %s for streaming: %w", toolSpec.Name, err)
    }

    // Obtain a StreamExecutor: either the tool implements it directly, or it is
    // wrapped by an adapter that bridges to the tool's Stream method.
    streamExecutor, ok := tool.(pipelinetypes.StreamExecutor)
    if !ok {
        adapter := pipelinestreaming.NewToolStreamAdapter(tool, pe.dependencies.RequestID)
        streamExecutor = adapter
    }

    // Invoke the tool. The closure it carries already holds its build-time dependencies.
    return streamExecutor.CallWithStreaming(ctx, string(argsJSON), streamChan, pe.dependencies.LogCtx)
}
```

For `DynamicTool` values the adapter path is taken. `ToolStreamAdapter.CallWithStreaming` (`tools/toolcore/pipeline/streamingdir/adapter.go`) is the requestID→ctx injection boundary, then calls `tool.Stream(...)`, which is `DynamicTool.Stream` in `tools/toolcore/dynamic.go`:

```go
// In tools/toolcore/pipeline/streamingdir/adapter.go
streamCtx := requestcontext.WithRequestID(ctx, tsa.RequestID)
err := tsa.Tool.Stream(streamCtx, input, logCtx, eventChan)
```

```go
// In tools/toolcore/dynamic.go
func (t DynamicTool) Stream(ctx context.Context, input string, logCtx zerolog.Logger, streamChan chan<- types.StreamEvent) error {
    if t.StreamExecutor == nil {
        return fmt.Errorf("tool '%s' does not support streaming", t.NameStr)
    }
    return t.StreamExecutor(ctx, input, logCtx, streamChan)
}
```

The final call reaches the closure defined back in Step 1. At that moment:

- `input` (here `argsJSON`) carries the LLM-chosen parameters.
- The captured dependencies (`services.LLM`, `services.Tokenizer`, `arangoStore`, and any others referenced) are still bound and ready to use.

Blocking tools follow the analogous path through `DynamicTool.Call`, which invokes the `Executor` closure instead. Any `requestID` it needs is already in `ctx` (seeded by `tools/toolcore/executor/executor.go`), read via `contextpkg.GetRequestIDFromContext`.

## Go Closures Explained

### What is a Closure?

A closure is a function value that captures and retains variables from its surrounding scope, remaining valid even after the enclosing function has returned. In Go, an anonymous function automatically forms a closure over any external variable it references.

### Simple Closure Example

```go
func createMultiplier(factor int) func(int) int {
    // The returned function captures the 'factor' variable.
    return func(x int) int {
        return x * factor // factor remains accessible here.
    }
}

func main() {
    double := createMultiplier(2) // factor = 2 is captured
    triple := createMultiplier(3) // factor = 3 is captured

    fmt.Println(double(5)) // 10 (uses captured factor = 2)
    fmt.Println(triple(5)) // 15 (uses captured factor = 3)
}
```

### A Closure Resembling the Tool Executors

```go
type Services struct {
    LLM       LLMInterface
    Tokenizer *tiktoken.Tiktoken
    Database  DatabaseInterface
}

func createToolExecutor(services *Services) func(string) (string, error) {
    // This function captures the entire 'services' value.
    return func(input string) (string, error) {
        // Although this function is invoked much later, it still has access
        // to the original 'services' value.

        var args ToolArgs
        json.Unmarshal([]byte(input), &args)

        result := services.Database.Query(args.Query)
        tokens := services.Tokenizer.Encode(result, nil, nil)
        response, _ := services.LLM.GenerateContent(args.Prompt + result)

        return response.Content, nil
    }
}

func main() {
    services := initializeServices()             // create dependencies once
    toolExecutor := createToolExecutor(services) // capture them in a closure

    // Invoked later; the closure still holds the original 'services'.
    result, _ := toolExecutor(`{"query": "...", "prompt": "Analyze this data"}`)
}
```

## Why This Pattern Is Effective

### 1. Clean Separation of Concerns

Dependencies are resolved at build time; runtime parameters arrive through `input`. The two never intermix at the call site of the LLM:

```go
Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
    var args ToolArgs
    json.Unmarshal([]byte(input), &args)

    data := services.Database.Query(args.Query)          // build-time dep + runtime param
    analysis := services.LLM.Analyze(data, args.Prompt)  // build-time dep + runtime param
    return analysis, nil
},
```

### 2. Dependency Injection Without a Framework

The system achieves dependency injection without a container or reflection:

```go
// Struct-field injection (more boilerplate)
type Tool struct {
    llm       LLMInterface
    tokenizer *tiktoken.Tiktoken
    database  DatabaseInterface
}

func (t *Tool) Execute(input string) error { /* uses t.llm, t.tokenizer, ... */ }

// Closure-based injection (used here)
func createTool(llm LLMInterface, tokenizer *tiktoken.Tiktoken, database DatabaseInterface) func(string) error {
    return func(input string) error {
        // Dependencies are captured directly; no struct fields required.
        return nil
    }
}
```

### 3. Minimal Capture

Each closure retains only the dependencies it actually references:

```go
// A tool that needs only the LLM captures only services.LLM.
Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
    return analyzeText(services.LLM, input)
},

// A tool that needs the data store and arango captures both.
Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
    data := services.DataStore.Query(input)
    return process(data, arangoStore)
},
```

## Visualizing the Two Data Flows

```
┌───────────────────────────────────────────────────────────────────┐
│                       BUILD TIME (Bootstrap)                        │
├───────────────────────────────────────────────────────────────────┤
│  services.LLM        ──┐                                            │
│  services.Tokenizer  ──┤                                            │
│  services.DataStore  ──┤──► BuildAllTools(services,                 │
│  arangoStore         ──┤        arangoStore, authStore)             │
│  authStore           ──┘         │                                  │
│                                  ├─► authStore registered once via  │
│                                  │   InitializeAuthProvider         │
│                                  │                                  │
│                                  └─► []DynamicTool                   │
│                                        │                            │
│                                        └─► each executor closure    │
│                                            captures the deps it     │
│                                            references               │
│                                                                     │
│  GetFormattedTools([]DynamicTool)                                   │
│        ├─► availableTools: map[name]LoggableTool                    │
│        └─► llmTools: []llms.Tool (schemas for the planner)          │
└───────────────────────────────────────────────────────────────────┘

┌───────────────────────────────────────────────────────────────────┐
│                         RUNTIME (Execution)                         │
├───────────────────────────────────────────────────────────────────┤
│  Planner.PlanOnly ──► ClassifyAndPlan(question, ..., llmTools)      │
│                                  │                                  │
│                                  ▼                                  │
│  ExecutionPlan: { steps: [ { tool: "concept_sector_search",        │
│                              arguments: "{...}" } ] }               │
│                                  │                                  │
│                                  ▼                                  │
│  PipelineExecutor.executeToolCallStepWithStreaming                  │
│        ├─► validateAndPrepareTool(step, availableTools)             │
│        └─► streamExecutor.CallWithStreaming(ctx, argsJSON, ...)     │
│                                  │                                  │
│                                  ▼                                  │
│  DynamicTool.Stream ──► t.StreamExecutor(ctx, input, ...)           │
│                                  │                                  │
│                                  ▼                                  │
│  Inside the closure:                                                │
│  - parse 'input' (LLM-chosen parameters)                            │
│  - use captured services.LLM / services.Tokenizer / arangoStore     │
└───────────────────────────────────────────────────────────────────┘
```

## Key Benefits of This Approach

### 1. Decoupled Definition and Execution

Tools are defined once with their dependencies bound. Runtime parameter passing is fully separate, and the LLM chooses tools and arguments without any knowledge of dependencies.

### 2. Compile-Time Validation

Dependencies are ordinary Go values checked at compile time. Runtime argument parsing is validated separately at execution. No reflection or dynamic resolution is involved.

### 3. Predictable Performance

Dependencies are captured once at startup. There is no per-call dependency lookup, and calls into the captured services are direct.

### 4. Testability

Because `BuildAllTools` takes its dependencies as arguments, tests can inject mocks and every resulting closure captures the mocked handles:

```go
mockServices := &core.Services{
    LLM:       &mockLLM{},
    Tokenizer: &mockTokenizer{},
    // DataStore, etc.
}

// authStore is interface{}; pass a mock provider or nil.
tools := toolcore.BuildAllTools(mockServices, mockArangoStore, mockAuthStore)
// Every tool now carries the mocked dependencies in its closure.
```

## Worked Example: The `concept_sector_search` Tool

### 1. Definition (build time)

```go
// In tools/toolcore/definitions.go - buildSectorTools()
{
    NameStr:        "concept_sector_search",
    DescriptionStr: conceptSectorSearchDesc,
    Schema:         conceptSectorSchema,

    // Captures: services.LLM, services.Tokenizer, services.DataStore, arangoStore.
    Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
        var args tooltypes.ConceptSectorSearchArgs
        if err := json.Unmarshal([]byte(input), &args); err != nil {
            return "", fmt.Errorf("invalid arguments: %w", err)
        }
        return toolbe.ConceptSectorSearchUsingLLM(
            ctx,
            args.Query,          // from LLM input
            args.Language,       // from LLM input
            args.TopN,           // from LLM input
            logCtx,              // runtime
            services.LLM,        // captured build-time dependency
            services.Tokenizer,  // captured build-time dependency
            services.DataStore,  // captured build-time dependency
            arangoStore,         // captured build-time dependency
        )
    },
},
```

### 2. Plan produced by the LLM (runtime)

```json
{
  "steps": [
    {
      "tool": "concept_sector_search",
      "arguments": "{\"query\": \"banking sector leaders\", \"language\": \"en\", \"top_n\": 5}"
    }
  ]
}
```

### 3. Execution (runtime)

```go
// The pipeline executor resolves the tool from availableTools and calls it.
// Inside the closure:
// - input   = the arguments string chosen by the LLM
// - services.LLM, services.Tokenizer, services.DataStore, arangoStore
//   are still bound from build time.
```

> Note on `compare_stocks`: it is intentionally **not** a registered executable
> tool. It is a reserved terminal synthesis-step marker. When the plan reaches a
> `compare_stocks` step, `executeToolCallStepWithStreaming` routes it to the
> injected `ComparisonSynthesizer` (in `chatbot/processing/comparison`) via
> `executeComparisonSynthesis` rather than looking it up in `availableTools`.
> There is therefore no `compare_stocks` `StreamExecutor` closure in the tool
> registry.

## Best Practices for This Pattern

### 1. Capture Dependencies Explicitly

```go
// Preferred: dependencies enter through the enclosing function's parameters.
func buildSectorTools(services *core.Services, arangoStore *db.ArangoStore) []DynamicTool {
    return []DynamicTool{ /* closures over services, arangoStore */ }
}

// Avoid: implicit reliance on package-level globals, which is harder to test.
func createBadToolExecutor() func(string) error {
    return func(input string) error {
        return globalServices.LLM.Process(input)
    }
}
```

### 2. Treat Captured Dependencies as Immutable

Closures capture references. Dependencies are expected to be stable for the lifetime of the tool set. If they must change, rebuild the tools with `BuildAllTools`.

### 3. Keep Runtime Parameters Distinct

Parse runtime parameters out of `input`; keep them separate from captured dependencies. The closure pattern makes this separation natural because dependencies never appear in the executor's parameter list.

## Conclusion

This closure-based dependency injection pattern is effective because it:

1. Maintains a clean separation between dependency injection (build time) and parameter passing (runtime).
2. Relies only on Go's language features, avoiding an injection framework.
3. Provides compile-time type safety while remaining flexible.
4. Supports tool composition in which LLM decisions and system dependencies coexist without interfering.

The mechanism works because Go closures capture the external variables they reference. Tools retain access to their dependencies throughout the application lifecycle, even though only runtime parameters flow through the planner and executor.
