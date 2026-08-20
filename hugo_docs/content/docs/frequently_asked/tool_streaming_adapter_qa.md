---
title: "Tool Streaming Adapter Q&A"
date: 2026-07-10
draft: false
---

> **Scope:** Why the streaming boundary for tools looks the way it does — a producer
> goroutine, an internal `StreamEvent` channel, and the `LoggableTool` interface.
>
> **Ground truth (verified 2026-07-10):**
> - Interface: `tools/tooltypes/interfaces.go` (`LoggableTool`)
> - Adapter: `tools/toolcore/pipeline/streamingdir/adapter.go` (`ToolStreamAdapter.CallWithStreaming`)
> - Consumer: `tools/toolcore/pipeline/execution/tool.go` (`executeToolWithStreaming` → `CallWithStreaming`)
> - `StreamExecutor` contract: `tools/toolcore/pipeline/types/plan.go`
>
> An earlier version of this file described `ResponseStreamer.runDirectToolStream`,
> `internalStreamChan`, and a `runStandardLLMPath` fallback. That code no longer exists —
> the streaming boundary was refactored into the `streamingdir` adapter. This version
> tracks the current implementation.

---

## Question

Reading `ToolStreamAdapter.CallWithStreaming`:

```go
func (tsa *ToolStreamAdapter) CallWithStreaming(ctx context.Context, input string, streamChan chan<- string, logCtx zerolog.Logger) (string, error) {
    eventChan := make(chan types.StreamEvent, consts.DefaultStreamEventChannelBufferSize)
    // ...
    var wg sync.WaitGroup
    wg.Add(2)

    // consumer goroutine: eventChan -> streamChan (string tokens)
    go func() { defer wg.Done(); /* ... */ }()

    // producer goroutine: run the tool's Stream into eventChan
    go func() {
        defer wg.Done()
        defer close(eventChan)
        streamCtx := requestcontext.WithRequestID(ctx, tsa.RequestID)
        err := tsa.Tool.Stream(streamCtx, input, logCtx, eventChan)
        // ...
    }()
    // ...
}
```

1. Why run `tool.Stream` in its own goroutine — it's just one tool, what's the wisdom?
2. Why the separate `eventChan` (`chan types.StreamEvent`) instead of handing the tool the outbound `streamChan` directly?
3. What does `tooltypes.LoggableTool` buy us? `DynamicTool` is the only real implementation — why an interface at all?

---

## Answer

Good questions. They target three real design choices at the streaming boundary. Let's take them one at a time.

### 1. The producer goroutine (and why `wg.Add(2)`)

The adapter has a **producer/consumer split**, and each side needs to run at the same time.

- **Producer:** `tsa.Tool.Stream(streamCtx, input, logCtx, eventChan)`. Its job is to *produce* `StreamEvent`s and push them into `eventChan`. For a RAG tool this call blocks for as long as the upstream API keeps sending — potentially seconds.
- **Consumer:** the other goroutine's `for` loop, which *drains* `eventChan`, converts each `token` event to a string, and forwards it to the outbound `streamChan`.

If you called `tsa.Tool.Stream(...)` inline instead of in a goroutine, it would block until the tool had emitted its *entire* response before the consumer loop could run even once. The buffered channel (size `DefaultStreamEventChannelBufferSize` = 100) would fill, the tool would block on a full channel, and — because nothing is draining it — you would deadlock. Even if the buffer were unbounded, you'd lose streaming entirely: the user waits on a spinner, then the whole paragraph lands at once.

By putting the tool in its own goroutine, the consumer starts immediately and the two run concurrently — each token is forwarded the moment it's produced. That is the real-time, word-by-word effect.

`wg.Add(2)` is because there are **two** goroutines here, not one: the producer and the token-converter consumer. The `WaitGroup` ensures the function does not return until both have finished their cleanup — the producer closing `eventChan` (its `defer close(eventChan)`) and the consumer draining it. The main body waits via `wg.Wait()` after it receives the tool's result on `errChan`, and on cancellation it uses a timer + `abandonChan` so a stuck goroutine can't leak.

### 2. The internal `eventChan`

Why not hand the tool the outbound `streamChan` directly? Because `eventChan` and `streamChan` are **different types serving different roles**, and the adapter needs to sit between them.

- **Type translation.** The tool speaks `types.StreamEvent` — a tagged union (`token`, and other event types). The pipeline's `StreamExecutor` contract speaks `chan<- string`. `eventChan` is where that translation happens: the consumer inspects `event.Type == "token"`, unwraps `event.Payload.(string)`, and only then writes the string to `streamChan`. Non-token events are filtered out here rather than leaking downstream.

- **Result accumulation.** As it forwards each token, the consumer also appends it to a `strings.Builder` (`fullOutput`). `CallWithStreaming` returns that accumulated string so the caller (`executeToolWithStreaming`, wrapped in `ExecuteToolWithRetry`) gets the complete tool output for retry logic, metrics, token counting, and persistence — *while* the user was streamed the same content live. A tool writing straight to `streamChan` couldn't give you both the live stream and the captured result.

- **Ownership and clean shutdown.** The adapter creates `eventChan`, so the adapter (via the producer goroutine's `defer`) closes it — the component that owns a channel closes it. The outbound `streamChan` is owned by the caller up the pipeline; the adapter only holds a send-only view (`chan<- string`) and never closes it. That separation is what lets the adapter manage cancellation cleanly: on `ctx.Done()` it drains or abandons `eventChan` on its own terms without corrupting the caller's channel.

Handing the tool the outbound channel directly would collapse all three of these — no translation point, no captured result, and tangled ownership of a channel the adapter doesn't own.

### 3. The `LoggableTool` interface

`DynamicTool` may be the only concrete tool type today, but the interface is what keeps the streaming machinery decoupled from it.

Look at where the abstraction actually pays off — `executeToolWithStreaming` in `pipeline/execution/tool.go`:

```go
streamExecutor, ok := tool.(pipelinetypes.StreamExecutor)
if !ok {
    adapter := pipelinestreaming.NewToolStreamAdapter(tool, pe.dependencies.RequestID)
    streamExecutor = adapter
}
```

Here `tool` is a `tooltypes.LoggableTool`. The execution layer never names `DynamicTool`. It knows only the contract:

```go
type LoggableTool interface {
    Name() string
    Description() string
    Call(ctx context.Context, input string, logCtx zerolog.Logger) (string, error)
    Stream(ctx context.Context, input string, logCtx zerolog.Logger, streamChan chan<- types.StreamEvent) error
    ToLLMSchema() llms.Tool
}
```

What the interface enables:

1. **Substitutability.** Any type that satisfies `LoggableTool` drops into the `AvailableTools` map and the whole pipeline — planner validation, parallel executor, streaming adapter — works with it unchanged. `DynamicTool` proves it satisfies the contract at compile time: `var _ tooltypes.LoggableTool = DynamicTool{}` in `tools/toolcore/dynamic.go`.
2. **Testability.** The executor and adapter tests use a `mockTool` implementing `LoggableTool` (see `executor/helpers_test.go`, `pipeline/test_helpers.go`) — no real API calls, predictable output, fast isolated tests. That's only possible because the consumers depend on the interface, not the concrete type.
3. **Decoupling across packages.** `tooltypes` defines the contract; `pipeline`, `executor`, and `chatbot/processing` depend on the contract. None of them import concrete tool implementations, so tools can be added or changed without touching the orchestration core.

> **Note on `requestID`.** `LoggableTool.Stream` takes **no** `requestID` parameter. Request-scoped values travel in `ctx`: the adapter seeds it via `requestcontext.WithRequestID(ctx, tsa.RequestID)` before calling `Stream`, and the tool's streaming closure reads it from context the same way blocking tools do. This keeps the interface free of request-plumbing — see the doc comment on `Stream` in `tools/tooltypes/interfaces.go`.
