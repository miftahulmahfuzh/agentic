---
title: "Data Driven"
date: 2025-08-02
draft: false
---

# The Data-Driven Tool Architecture

## 1. Overview: The Armory Philosophy

The term "data-driven" here doesn't mean it uses analytics to make decisions. It means the system's fundamental capabilities—the tools themselves—are defined as declarative **data** structures, not as hard-coded imperative logic.

Think of it as the armory from *John Wick*. The core system—the rules of engagement, the process of selecting a weapon—is fixed and robust. The arsenal itself, however, can be infinitely expanded. Adding a new shotgun doesn't require rewriting the laws of physics or retraining John Wick; you simply add the weapon and its specifications to the inventory.

In our system:
- **The Armory Manifest:** `toolcore/definitions.go`
- **The Weapons (Tools):** `DynamicTool` structs
- **The Rules of Engagement (The Engine):** `toolcore/caller.go` and `toolutils/callerutils.go`

This design makes the system exceptionally maintainable, scalable, and robust, directly adhering to the Open/Closed Principle.

## 2. Core Components

The architecture relies on a few key components working in concert.

### A. The Contract: `tooltypes.LoggableTool` Interface

This is the "One Ring to rule them all." It is the non-negotiable contract that every tool in our system must honor.

```go
// tools/tooltypes/interfaces.go
type LoggableTool interface {
	Name() string
	Description() string
	Call(ctx context.Context, input string, logCtx zerolog.Logger) (string, error)
	Stream(ctx context.Context, input string, logCtx zerolog.Logger, streamChan chan<- StreamEvent, requestID string) error
	ToLLMSchema() llms.Tool
}
```

Any struct that implements these methods can be treated as a tool by the core engine. This abstraction is critical. The engine doesn't care about the tool's specific implementation, only that it fulfills the contract.

### B. The Concrete Implementation: `toolcore.DynamicTool` Struct

This is our standard-issue weapon chassis. It's the concrete struct that implements the `LoggableTool` interface and holds all the metadata and logic for a single tool.

```go
// tools/toolcore/dynamic.go
type DynamicTool struct {
	NameStr        string
	DescriptionStr string
	Schema         json.RawMessage
	Executor       ExecutorFunc       // For standard, blocking calls
	StreamExecutor StreamExecutorFunc // For streaming calls
}
```

- **`NameStr`**: The unique identifier for the tool (e.g., `news_summary`).
- **`DescriptionStr`**: The text given to the LLM so it knows when to use the tool. This is a critical prompt engineering component.
- **`Schema`**: The JSON schema defining the arguments the tool expects. This allows the LLM to format its requests correctly.
- **`Executor` / `StreamExecutor`**: A function pointer. This is the "trigger." It's the actual code that runs when the tool is called.

### C. The Manifest: `toolcore/definitions.go`

This file is the single source of truth for the system's capabilities. It contains one function, `BuildAllTools`, which constructs a slice of `DynamicTool` instances.

```go
// tools/toolcore/definitions.go
func BuildAllTools(...) []DynamicTool {
	allTools := []DynamicTool{
		{
			NameStr:        "get_current_time",
			DescriptionStr: "...",
			Schema:         noArgsSchema,
			Executor:       func(...) (string, error) { /* ... */ },
		},
		{
			NameStr:        "news_summary",
			DescriptionStr: "...",
			Schema:         codeArgsSchema,
			Executor:       func(...) (string, error) { /* ... */ },
		},
        // ... more tools
    }
    return allTools
}
```

This is the **data** in "data-driven." It's a simple list. The core engine consumes this list to understand what it can do.

### D. The Engine: `toolcore/caller.go` & `GetFormattedTools`

The engine is completely generic. `GetFormattedTools` iterates through the manifest (`allTools`) and formats the data for different parts of the system:
1.  A `map[string]tooltypes.LoggableTool` for quick lookups during execution.
2.  A `[]llms.Tool` slice for the LLM to perform tool selection.

The `SelectAndPrepareTools` function uses this formatted data to orchestrate the LLM call and subsequent tool execution. It doesn't contain any logic specific to `news_summary` or any other tool. It's a generic executor, like the T-1000: it can execute any plan, provided the plan follows the established structure.

## 3. The Open/Closed Principle (OCP) in Action

OCP states:

> **Software entities (classes, modules, functions, etc.) should be open for extension, but closed for modification.**

Let's apply this to your code. It's a textbook example.

*   **Open for Extension:** You can extend the chatbot's capabilities by adding new tools. You do this by adding a new `DynamicTool{...}` entry to the `allTools` slice in `toolcore/definitions.go`. The system's functionality grows.
*   **Closed for Modification:** To add that new tool, you did **not** have to modify `caller.go`, `manager.go`, `preparer.go`, or `dynamic.go`. Those core components are "closed." They are stable, tested, and don't need to be changed to support the new functionality. They are like the Terminator's chassis—the endoskeleton is fixed, but you can give it different weapon loadouts (the tools).

#### How to Add a New Tool (The Right Way)

1.  **Implement the Logic:** Write the executor function, for example, a new `GetCompanyCompetitors` function in `toolbe`.
2.  **Define the Schema:** Create the JSON schema for its arguments in `definitions.go`.
3.  **Add to the Manifest:** Add a new `DynamicTool{...}` struct to the `allTools` slice in `toolcore/definitions.go`, wiring up the name, description, schema, and executor function.

That's it. You have extended the system's functionality without modifying a single line of the core engine's code.

#### The Wrong Way (Violating OCP)

Imagine if `SelectAndPrepareTools` looked like this:

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

## 4. Architectural Prowess: The Payoff

This data-driven design delivers significant advantages:

1.  **Extreme Maintainability:** Tool logic is self-contained. A bug in the `financial_annualreport` tool is isolated to its executor function, not entangled in a 500-line `switch` statement. You can fix or modify a tool with minimal risk to the rest of the system, like swapping a component in a modular rifle.
2.  **Effortless Scalability:** Adding the 100th tool is no more complex than adding the 1st. The core engine's complexity does not increase as the number of tools grows.
3.  **Superior Testability:** Each tool's executor can be unit-tested in complete isolation. The core engine can be tested with a set of mock tools to ensure its orchestration logic is sound.
4.  **Clarity and Single Source of Truth:** To understand the full capabilities of the chatbot, a developer only needs to read one file: `toolcore/definitions.go`. It's the Marauder's Map of our system—it shows you everything.

By separating the *what* (the data in `definitions.go`) from the *how* (the generic logic in `caller.go`), the architecture remains clean, robust, and ready for future expansion without collapsing under its own weight.
