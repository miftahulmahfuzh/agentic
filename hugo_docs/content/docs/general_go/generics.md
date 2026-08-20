---
title: "Go Generics"
date: 2025-10-31
lastmod: 2026-07-09
draft: false
---

## Overview

Go 1.18 introduced generics: functions and types parameterized by a type, checked
at compile time. If you come from Python, think of `typing.TypeVar` +
`typing.Generic`, except Go resolves everything statically — there is no runtime
type object, and a mismatch is a compile error, not a `TypeError` at runtime.

This guide grounds every concept in code that actually exists in this repo. The
central example is the pipeline's retry component, which today lives in three
files (it was refactored out of a single `retry.go`):

- **Type definitions:** `tools/toolcore/pipeline/types/retry.go` (package `types`)
- **Retry logic:** `tools/toolcore/pipeline/retrydir/retry.go` (package `pipelineretry`)
- **Thin re-export wrappers:** `tools/toolcore/pipeline/types.go` (package `pipeline`)
- **Tests:** `tools/toolcore/pipeline/retry_test.go`

> Note for readers of older docs: there is no longer a
> `tools/toolcore/pipeline/retry.go`. The generic types moved to the `types`
> subpackage and the logic moved to the `retrydir` subpackage (import name
> `pipelineretry`). The `pipeline` package re-exports both via type aliases and
> wrapper functions so existing call sites keep compiling.

## What Are Generics?

Generics let you write code that works with **any type** while staying type-safe.
Before generics, Go developers reached for:

- `interface{}` (now `any`) plus type assertions — the equivalent of untyped
  Python, pushing errors to runtime
- Code generation
- One near-identical implementation per type

Generics replace all three with **type parameters** that get substituted with
concrete types at the call site.

## Basic Syntax

### Type Parameters

Type parameters go in square brackets `[]` before the ordinary parameter list:

```go
func FunctionName[T any](param T) {
    // T can be any type
}
```

- `[T any]` declares a type parameter `T`.
- `any` is the constraint — the set of types allowed. `any` allows everything
  (it is an alias for `interface{}`).
- `T` can then be used throughout the signature and body.

Python analogy:

```python
from typing import TypeVar
T = TypeVar("T")
def function_name(param: T) -> None: ...
```

The difference: Go's `T` is erased into a concrete type at compile time, so there
is zero runtime cost and full compile-time checking.

### Constraints

A constraint is an interface describing what the type parameter must support:

```go
// any constraint - allows any type
[T any]

// comparable constraint - allows types usable with == and !=
[T comparable]

// custom constraint - allows a specific set of methods
[T interface{ String() string }]
```

## Real-World Analysis: The Retry Component

### Generic Type Definitions

From `tools/toolcore/pipeline/types/retry.go`:

```go
// RetryableOperation represents a function that can be retried
// (types/retry.go:21)
type RetryableOperation[T any] func(ctx context.Context) (T, error)

// RetryResult contains the result of a retry operation
// (types/retry.go:24)
type RetryResult[T any] struct {
    Result     T             // The successful result
    Error      error         // The final error (if any)
    Attempts   int           // Number of attempts made
    RetryCount int           // Number of retries attempted (attempts - 1)
    TotalTime  time.Duration // Total time spent including backoffs
    Success    bool          // Whether the operation succeeded
}
```

`RetryResult[T]` also carries a method (`types/retry.go:34`):

```go
// UpdateMetrics updates the step execution metrics with retry information
func (r *RetryResult[T]) UpdateMetrics(metrics *StepExecutionMetrics) {
    if metrics != nil {
        metrics.RetryCount += r.RetryCount
    }
}
```

Note the receiver is `*RetryResult[T]` — the type parameter is repeated on the
receiver, and the method body works for any `T`.

`RetryConfig` (`types/retry.go:12`) is **not** generic — retry behavior does not
depend on the operation's return type, so it stays a plain struct:

```go
type RetryConfig struct {
    RetryLimit    int              // Maximum number of retry attempts
    DefaultLimit  int              // Default limit if RetryLimit is <= 0
    BackoffBase   time.Duration    // Base duration for exponential backoff (default: 1 second)
    MaxBackoff    time.Duration    // Maximum backoff duration (default: 30 seconds)
    RetryableFunc func(error) bool // Function to determine if an error is retryable
}
```

This is a deliberate split: the *behavior* (generic retry loop) is separated from
the *configuration* (limits, backoff strategy).

### The Core Generic Function

From `tools/toolcore/pipeline/retrydir/retry.go:47`:

```go
func ExecuteWithRetry[T any](
    ctx context.Context,
    config types.RetryConfig,
    operation types.RetryableOperation[T],
    logCtx zerolog.Logger,
    operationName string,
) types.RetryResult[T]
```

**Key components:**

1. **Type parameter `[T any]`** — `T` is the value the operation returns.
2. **Generic operation `types.RetryableOperation[T]`** — a `func(ctx) (T, error)`.
3. **Generic result `types.RetryResult[T]`** — the returned struct's `Result`
   field is exactly `T`.

On failure the function returns `RetryResult[T]{Result: result, ...}` where
`result` is the last attempt's value (which is the zero value of `T` if the
operation never produced one). See `retrydir/retry.go:62` (`var result T`) and the
final return at `retrydir/retry.go:165`.

### Why a Generic Return Type?

1. **Type safety** — `Result` has the operation's exact type, no casting.
2. **Zero values** — on failure, `Result` is the zero value of `T`
   (`var result T` at `retrydir/retry.go:62`).
3. **No type assertions** — callers use `result.Result` directly.
4. **Compile-time checking** — type errors surface at build time.

## Helper Functions Built on Top

The `retrydir` package layers two convenience wrappers over `ExecuteWithRetry`.

### ExecuteToolWithRetry

From `retrydir/retry.go:178`:

```go
func ExecuteToolWithRetry[T any](
    ctx context.Context,
    toolName string,
    operation types.RetryableOperation[T],
    logCtx zerolog.Logger,
    metrics *types.StepExecutionMetrics,
) types.RetryResult[T]
```

It applies `DefaultRetryConfig()` and calls `result.UpdateMetrics(metrics)` for
you.

> **Important — signature change:** there is **no `retryLimit int` parameter**.
> Per change P2-PP-A028, the retry limit is always taken from
> `config.AppSettings.DefaultRetryLimit` via `DefaultRetryConfig()`, so the
> explicit parameter was removed. Older documentation that shows
> `ExecuteToolWithRetry(ctx, toolName, retryLimit, operation, ...)` is stale.

### ExecuteLLMWithRetry

From `retrydir/retry.go:201`:

```go
func ExecuteLLMWithRetry[T any](
    ctx context.Context,
    llmName string,
    operation types.RetryableOperation[T],
    logCtx zerolog.Logger,
) types.RetryResult[T]
```

It uses `DefaultLLMRetryConfig()` (a lower default limit tuned for LLM calls) and
does not update metrics.

### Default Configs

`DefaultRetryConfig()` (`retrydir/retry.go:18`) and `DefaultLLMRetryConfig()`
(`retrydir/retry.go:33`) both return `RetryLimit: 0` so the effective limit comes
from `DefaultLimit` — `config.AppSettings.DefaultRetryLimit` for tools, and a
hard-coded `1` for LLM calls.

### The Re-export Layer

Because the logic moved into subpackages, `tools/toolcore/pipeline/types.go`
re-exports everything so the `pipeline` package's public API is unchanged:

```go
// Type aliases (types.go:105, types.go:108)
type RetryableOperation[T any] = types.RetryableOperation[T]
type RetryResult[T any] = types.RetryResult[T]

// Wrapper functions (types.go:141, :152, :163) delegate to pipelineretry
func ExecuteWithRetry[T any](...) types.RetryResult[T] {
    return pipelineretry.ExecuteWithRetry(ctx, config, operation, logCtx, operationName)
}
```

The `= types.RetryableOperation[T]` form is a **generic type alias** — it defines
`pipeline.RetryableOperation[T]` as the *same* type as `types.RetryableOperation[T]`,
not a distinct new type.

## Usage Examples

### From the actual codebase

The streaming tool executor in
`tools/toolcore/pipeline/execution/tool.go:435` calls the tool helper. `T` is
inferred as `string` from the closure's return type:

```go
retryResult := pipelineretry.ExecuteToolWithRetry(
    ctxWithTracker,
    toolSpec.Name,
    func(ctx context.Context) (string, error) {
        return streamExecutor.CallWithStreaming(ctx, string(argsJSON), streamChan, pe.dependencies.LogCtx)
    },
    pe.dependencies.LogCtx,
    metrics,
)
// retryResult.Result is a string
```

### Different return types (from retry_test.go)

**String return type** (`retry_test.go:41`, `TestExecuteWithRetry_Success`):

```go
operation := func(_ context.Context) (string, error) {
    return "success", nil
}
result := ExecuteWithRetry(ctx, config, operation, logger, "test_operation")
// result.Result is of type string
```

**Zero-value `int`** (`retry_test.go:263`, `TestExecuteWithRetry_ZeroValueType`):

```go
operation := func(_ context.Context) (int, error) {
    return 0, nil
}
result := ExecuteWithRetry(ctx, config, operation, logger, "test_operation")
// result.Result == 0 (the int zero value)
```

**Pointer type** (`retry_test.go:279`, `TestExecuteWithRetry_PointerType`):

```go
expectedValue := "test"
operation := func(_ context.Context) (*string, error) {
    return &expectedValue, nil
}
result := ExecuteWithRetry(ctx, config, operation, logger, "test_operation")
// result.Result is of type *string
```

## Type Inference

You almost never write the type argument explicitly — the compiler infers `T`
from the operation's return type:

```go
// T inferred as string
result := ExecuteWithRetry(ctx, config, func(_ context.Context) (string, error) {
    return "hello", nil
}, logger, "test")
```

Explicit instantiation (`ExecuteWithRetry[string](...)`) is legal but redundant
here. Prefer inference.

## Other Real Generics in This Codebase

The retry component is not the only place generics appear. A few more, all real:

### Generic containers: `multisource.Result[T]`

`tools/toolbe/multisource/result.go:9` and `:18` — reusable containers for
multi-source tool output, parameterized by the per-item metadata type:

```go
type Result[T any] struct {
    FormattedOutput string `json:"formatted_output"`
    Items           []T    `json:"items"`
}

type ResultWithLogs[T any] struct {
    FormattedOutput string                 `json:"formatted_output"`
    Items           []T                    `json:"items"`
    ExternalAPIs    []types.ExternalAPILog `json:"external_apis,omitempty"`
}
```

### Generic utility over a slice: `BuildResultList[T]`

`tools/toolbe/stringutil/builder.go:33` — formats any slice into a labeled string,
taking a per-item formatter callback:

```go
func BuildResultList[T any](
    items []T,
    label string,
    formatter func(item T, index int) []string,
    estimatedBytesPerItem int,
) string
```

### Generic slice helper: `evictOldest[T]`

`chatbot/processing/usershorttermmemoryeditor/stats.go:98` — trims a slice to a
size limit, using a caller-supplied accessor to extract the sort key:

```go
func evictOldest[T any](items []T, limit int, lastMention func(T) string) []T
```

This is the common Go idiom of pairing `[T any]` with a `func(T) ...` callback
when the code needs a value *out of* `T` but should not care what `T` is.

## Custom Constraints in Practice

The concept-sector API code uses a **custom method constraint** so one generic
function can call several concrete response types.

`tools/toolutils/conceptsector.go:364`:

```go
// responseWithErrorCode is the interface for API responses with
// ErrorCode and Message fields
type responseWithErrorCode interface {
    GetErrorCodePtr() *string
    GetMessagePtr() *string
}
```

`tools/toolutils/conceptsector.go:390`:

```go
// T must be a pointer type implementing responseWithErrorCode.
func callConceptAPI[T responseWithErrorCode](
    ctx context.Context,
    serviceURL string,
    endpointName string,
    requestBody HealthRequest,
    logCtx zerolog.Logger,
) (T, error) {
    var zero T
    // ... unmarshal into T, then read T's ErrorCode/Message via the interface
}
```

Concrete types like `*SummaryResponse`, `*OverviewResponse`, and
`*ResearchResponse` satisfy the constraint by implementing `GetErrorCodePtr()`
and `GetMessagePtr()` (`conceptsector.go:371`–`:386`). This is exactly what a
method constraint buys you: inside the generic body you may call the constraint's
methods on values of type `T`.

Python analogy: this is like a `TypeVar("T", bound=SomeProtocol)` where
`SomeProtocol` is a `typing.Protocol` requiring `get_error_code_ptr` and
`get_message_ptr`.

## Testing Generic Code

`retry_test.go` exercises the generic code across several `T` values without any
special generic-testing machinery — you just instantiate at different types:

- `TestExecuteWithRetry_ZeroValueType` (`retry_test.go:263`) — `T = int`
- `TestExecuteWithRetry_PointerType` (`retry_test.go:279`) — `T = *string`
- `TestExecuteToolWithRetry_Helper` (`retry_test.go:215`) — the tool wrapper
- `TestExecuteLLMWithRetry_Helper` (`retry_test.go:232`) — the LLM wrapper
- `TestRetryResult_UpdateMetrics` (`retry_test.go:249`) — the generic method,
  instantiated as `RetryResult[string]`

## Best Practices

### 1. Use the least-restrictive constraint that still works

```go
// Use 'any' when the body performs no operations on the value itself
func BuildResultList[T any](items []T, ...) string

// Use a method constraint when the body must call methods on T
func callConceptAPI[T responseWithErrorCode](...) (T, error)
```

### 2. Prefer type inference

```go
// Good: let the compiler infer T
result := ExecuteWithRetry(ctx, config, op, logger, "test")

// Avoid: redundant explicit instantiation
result := ExecuteWithRetry[string](ctx, config, op, logger, "test")
```

### 3. Pass callbacks to extract values from an opaque `T`

When you need a value out of `T` but should not constrain what `T` is, take a
`func(T) X`, as `evictOldest` and `BuildResultList` do.

### 4. Handle zero values deliberately

`ExecuteWithRetry` returns `var result T` (its zero value) on failure, so callers
should gate on `result.Success` before trusting `result.Result`:

```go
if result.Success {
    use(result.Result) // safe: Result holds a real value
}
```

## Performance

Go compiles generics with a mix of monomorphization and shape-based dictionaries.
For the value types used here this means:

- No `interface{}` boxing/unboxing on the hot path.
- No reflection.
- Type errors caught at compile time, not runtime — the opposite of Python's
  duck typing.

## When to Use Generics

### Good use cases (all present in this repo)

1. **Reusable containers** — `multisource.Result[T]`.
2. **Utility functions over collections** — `BuildResultList[T]`, `evictOldest[T]`.
3. **Deduplicating near-identical logic** — the retry component collapses what
   would otherwise be per-return-type retry loops into one function.
4. **API flexibility with a method contract** — `callConceptAPI[T responseWithErrorCode]`.

### Avoid generics when

1. **Only one concrete type is ever used** — just write it concretely.
2. **A plain interface parameter suffices** — use the interface.
3. **Behavior must branch on the type** — use a type switch instead.

## Conclusion

The retry component (`tools/toolcore/pipeline/retrydir/retry.go` +
`tools/toolcore/pipeline/types/retry.go`, re-exported by
`tools/toolcore/pipeline/types.go`) is the flagship generics example in this
codebase:

1. **Eliminates duplication** — one `ExecuteWithRetry[T]` serves every return
   type; `ExecuteToolWithRetry[T]` and `ExecuteLLMWithRetry[T]` add policy on top.
2. **Type-safe** — `RetryResult[T].Result` is exactly the operation's type.
3. **Zero-value-aware** — failures return `var result T`.
4. **Testable across types** — `retry_test.go` instantiates at `int`, `*string`,
   and `string`.

---

**Key Takeaways:**

1. **Type parameters** — `[T any]` declares a placeholder for any type.
2. **Constraints** — from `any`, to `comparable`, to custom method interfaces
   like `responseWithErrorCode`.
3. **Type inference** — the compiler resolves `T` at the call site; write it
   explicitly only when needed.
4. **Compile-time, not runtime** — unlike Python's `TypeVar`, Go generics are
   checked and specialized at build time.
5. **Generic methods** — `func (r *RetryResult[T]) UpdateMetrics(...)` shows a
   method on a generic receiver.
6. **Where they live now** — retry generics moved out of a single `retry.go`
   into the `types` and `retrydir` (`pipelineretry`) subpackages, with the
   `pipeline` package re-exporting them via aliases and wrappers.
