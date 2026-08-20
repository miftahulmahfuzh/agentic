---
title: "Design Patterns"
date: 2025-08-14
lastmod: 2026-07-10
draft: false
---

This document identifies software engineering design patterns used in the codebase.
Every pattern below is grounded in current source; file paths and line numbers are
provided for verification.

> 📌 **Must-read companion:** [Why We Built Our Own Pipeline Instead of Adopting an Off-the-Shelf Agent Framework](../custom_pipeline_vs_frameworks/) — why the plan-and-execute / LLMCompiler orchestration is implemented in-house rather than via LangChain/LangGraph/Eino.

---

## Pattern Summary

### Concurrency Patterns
1. **Semaphore** - Controls concurrent resource access via buffered channels
2. **Context Propagation** - Manages cancellation and timeouts across goroutines
3. **Worker Pool** - Fixed set of workers processing from queues

### Behavioral Patterns
4. **Strategy** - Interchangeable algorithm families (tool executors)
5. **State** - Request lifecycle state management

### Structural Patterns
6. **Adapter** - Interface compatibility between subsystems
7. **Facade** - Simplified interface to a complex subsystem
8. **Proxy** - Circuit breaker for external services

### Creational Patterns
9. **Dependency Injection** - External dependency provision
10. **Factory** - Centralized object creation

---

## 1. Semaphore

**Definition**: Controls the maximum number of concurrent operations using buffered
channels as counting semaphores.

**Implementation**:
- **File**: `chatbot/manager_core.go`
- **Components** (`Manager` struct fields, `manager_core.go:66-70`):
  ```go
  processingSemaphore chan struct{} // Limits concurrent request processing
  llmStreamSemaphore  chan struct{} // Limits concurrent LLM streaming
  priorityRateLimiter chan struct{} // Lightweight rate limiting for Redis DoS protection
  ```
- **Sizing** (`manager_core.go:127-130`):
  ```go
  processingSemaphore: make(chan struct{}, cfg.MaxConcurrentRequests),
  llmStreamSemaphore:  make(chan struct{}, cfg.MaxConcurrentLLMStreams),
  priorityRateLimiter: make(chan struct{}, 100), // 100 concurrent priority requests max
  ```

**Code Example** (`chatbot/manager.go:513-526`):
```go
// Acquire processing slot (blocks if at capacity)
semaphoreStart := time.Now()
m.processingSemaphore <- struct{}{}
request.SemaphoreWaitDurationSec = time.Since(semaphoreStart).Seconds()

if m.IsRequestCancelled(request.RequestID) {
    <-m.processingSemaphore // Release on early cancellation
    return
}

// Execute task while holding the slot
m.executeTask(ctx, request, request.CacheKeyData)
<-m.processingSemaphore // Release
```

The priority fast-lane uses its own lightweight limiter (`chatbot/manager.go:649-650`):
```go
m.priorityRateLimiter <- struct{}{}
defer func() { <-m.priorityRateLimiter }()
```

**Purpose**:
- Resource protection: Prevents unbounded goroutine creation
- Load control: Limits concurrent expensive operations (normal processing, LLM streaming)
- Back-pressure: Requests wait in the queue when at capacity

---

## 2. Context Propagation

**Definition**: Thread request-scoped values, deadlines, and cancellation signals across
API boundaries and goroutines.

**Implementation**:
- **Files**: Throughout the codebase (`context.Context` as first argument), with the
  cancellation lifecycle centralized in `chatbot/cancellation/handler.go` and the
  per-request cancel functions tracked in the `Manager`.
- **State** (`chatbot/manager_core.go:35-62`):
  ```go
  type CancellableStreamItem struct { /* ... */ }

  // Manager field
  cancellableStreams map[string]*CancellableStreamItem
  ```

**Code Example** — registration of the per-request cancel func
(`chatbot/manager.go:315`):
```go
m.cancellableStreams[requestID] = &CancellableStreamItem{
    // holds the context.CancelFunc for this request
}
```

**Cancellation flow** (`chatbot/cancellation/handler.go:53-98`):
```go
func (h *Handler) CancelStream(requestID string) error {
    // 1. Set state to cancelled BEFORE cancelling the context, so the streaming
    //    goroutine's context-cancel detection can't overwrite state with 'errored'.
    h.manager.UpdateRequestState(requestID, types.StateCancelled, "Request cancelled by user")

    // 2. Cancel the request context - all downstream goroutines observe ctx.Done().
    if cancelFunc, ok := h.manager.GetCancellableStream(requestID); ok {
        cancelFunc()
    }

    // 3. Persist any partial output, then delete the bowl (no more resume).
    bowlContent := h.bowlMgr.GetBowlContent(requestID)
    // ... persist bowlContent ...
    h.bowlMgr.CancelBowl(requestID)
    return nil
}
```

Downstream consumers select on `ctx.Done()` to terminate promptly when the request
context is cancelled.

**Purpose**:
- Resource leak prevention: Terminate orphaned goroutines on cancellation
- Timeout enforcement: Unified deadline mechanism
- Graceful shutdown: Propagate shutdown signals from the app context to workers

---

## 3. Worker Pool

**Definition**: Fixed set of worker goroutines processing tasks from shared queues.

**Implementation**:
- **Files**: `chatbot/manager.go`, `chatbot/adapters_manager.go`, `chatbot/manager_core.go`
- **Cache fast-lane pool** (`manager_core.go:80-82`):
  ```go
  cacheRequestChan chan types.SubmitRequestArgs // Full request args for cache workers
  cacheWorkerPool  []*cacheWorker
  ```
  The `cacheWorker` type is defined at `chatbot/adapters_manager.go:22`.

**Code Example** — cache worker loop (`chatbot/manager.go:432-479`):
```go
func (cw *cacheWorker) run(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():
            return
        case <-cw.stopChan:
            return
        case request := <-cw.manager.cacheRequestChan:
            if cw.manager.IsRequestCancelled(request.RequestID) {
                continue
            }
            // Try cache fast-lane; on miss, route to normal processing.
            if cw.manager.cacheFastLane.HandleCachedRequest(ctx, request, request.CacheKeyData.CacheKey, logger) {
                // served from cache
            } else {
                cw.manager.routeToNormalProcessing(request)
            }
        }
    }
}
```

**FIFO normal worker** (`chatbot/manager.go:841-863`):
```go
func (m *Manager) normalRequestWorker(ctx context.Context) {
    for {
        select {
        case <-ctx.Done():
            return
        case <-m.queueManager.GetNormalChannel():
            request, found := m.queueManager.DequeueRequestNormal() // queue/manager.go:285
            if found && m.isRequestValid(request.RequestID) {
                m.processRequest(ctx, *request) // manager.go:482 (acquires processingSemaphore)
            }
        }
    }
}
```

`DequeueRequestNormal` is an alias of `DequeueRequest` (`chatbot/queue/manager.go:247`).
A separate `priorityRequestWorker` (`chatbot/manager.go:866`) drains cache-promoted
requests via `DequeueRequestPromoted` (`chatbot/queue/manager.go:290`) and runs them
immediately without the processing semaphore.

**Purpose**:
- Resource management: Bounded goroutine count
- Load balancing: Queues provide back-pressure
- Decoupling: Submission is separate from execution

---

## 4. Strategy

**Definition**: Encapsulates a family of algorithms and makes them interchangeable.

**Implementation**:
- **Files**: `tools/tooltypes/interfaces.go`, `tools/toolcore/dynamic.go`
- **Interface** (`tools/tooltypes/interfaces.go:15-30`):
  ```go
  type LoggableTool interface {
      Name() string
      Description() string
      Call(ctx context.Context, input string, logCtx zerolog.Logger) (string, error)
      // requestID travels via ctx, not as a parameter (as of 2026-07-10)
      Stream(ctx context.Context, input string, logCtx zerolog.Logger,
          streamChan chan<- types.StreamEvent) error
      ToLLMSchema() llms.Tool
  }
  ```

**Code Example** — generic tool wrapper holds the concrete strategy
(`tools/toolcore/dynamic.go:40-47`):
```go
type DynamicTool struct {
    NameStr        string
    DescriptionStr string
    Schema         json.RawMessage
    Executor       executorFunc       // blocking strategy
    StreamExecutor streamExecutorFunc // streaming strategy
}
```

`DynamicTool` implements `LoggableTool`; the tool-calling layer works against the
interface while each tool supplies its own executor function as the concrete strategy.
Exactly one executor is set per tool (`Executor` or `StreamExecutor`); request-scoped
values such as the `requestID` travel in `ctx`, so both signatures stay uniform
(`tools/toolcore/dynamic.go`). For the streaming path, `requestID` is seeded into
`ctx` by `ToolStreamAdapter.CallWithStreaming` (`tools/toolcore/pipeline/streamingdir/adapter.go`)
before `Stream` is called — mirroring how the blocking path seeds it in
`tools/toolcore/executor/executor.go` before `Call`.

**Purpose**:
- Flexibility: Add tools without changing the caller logic
- Decoupling: Tool-calling logic is separate from tool implementation
- Clarity: Separates "what" (the interface) from "how" (the executor)

---

## 5. State

**Definition**: An object's behavior changes based on its internal state.

**Implementation**:
- **File**: `types/enums.go` (state enum), `chatbot/` (transitions)
- **State type**: `types.RequestState`
- **States** (`types/enums.go:11-20`):
  ```go
  const (
      StateQueued             RequestState = "submitted"
      StateChoosingTools      RequestState = "choosing_tools"
      StateCallingTools       RequestState = "calling_tools"
      StateFormulatingAnswer  RequestState = "formulating_final_answer"
      StateReadyToStream      RequestState = "ready_to_stream"
      StateCompleted          RequestState = "completed"
      StateCancelled          RequestState = "cancelled"
      StateErrored            RequestState = "errored"
      StateTaskExecution      RequestState = "task_execution"
      StateFastLaneProcessing RequestState = "fastlane_processing"
  )
  ```
  `StateCompleted`, `StateCancelled`, and `StateErrored` are terminal
  (`RequestState.IsTerminal`, `types/enums.go:29`).

**Code Example** — state gates behavior. The public `CancelStream`
(`chatbot/main_handlers.go:37`) delegates to the cancellation handler, which reads and
transitions state under lock (`chatbot/cancellation/handler.go:53-74`):
```go
func (m *Manager) CancelStream(requestID string) error {
    return m.cancellationHandler.CancelStream(requestID)
}

// Handler.CancelStream:
if h.manager.IsRequestCancelled(requestID) {
    return nil // already cancelled - idempotent
}
// Set terminal state BEFORE cancelling the context so a late context-cancel
// detection cannot overwrite 'cancelled' with 'errored'.
h.manager.UpdateRequestState(requestID, types.StateCancelled, "Request cancelled by user")
```

`processRequest` also short-circuits based on state before doing work
(`chatbot/manager.go:498-504`): if `streamHolder.State == types.StateCancelled`, it returns
without processing.

**Purpose**:
- Clarity: Explicit lifecycle stages
- Robustness: Prevents illegal operations (e.g. double-cancel, overwriting terminal state)
- Maintainability: Organized state-dependent logic and race-safe transitions

---

## 6. Adapter

**Definition**: Converts the interface of a type into another interface that clients expect.

**Implementation**:
- **Files**: `chatbot/adapters_cache.go`, `adapters_config.go`, `adapters_database.go`,
  `adapters_manager.go`, `adapters_queue.go`, `adapters_services.go`, `adapters_storage.go`
- **Purpose**: Bridge the `Manager` and its subsystems (cache, cancellation, LLM, Redis,
  ArangoDB) so each subsystem depends only on the narrow interface it defines.

**Code Example** (`chatbot/adapters_manager.go:219`):
```go
// Adapt Manager to the state-updater interface expected by subsystems.
type managerStateUpdaterAdapter struct {
    manager *Manager
}

func (msa *managerStateUpdaterAdapter) UpdateRequestState(requestID string,
    newState types.RequestState, message string) {
    msa.manager.UpdateRequestState(requestID, newState, message)
}
```

The cache fast-lane is constructed against an adapter rather than the concrete Manager
(`chatbot/manager_core.go:280`):
```go
m.cacheFastLane = cache.NewFastLane(&cacheFastLaneAdapter{m}) // cacheFastLaneAdapter: adapters_cache.go:22
```

**Verified adapter structs** (partial list):
- `cacheFastLaneAdapter` — `adapters_cache.go:22`
- `managerCacheNotifierAdapter` — `adapters_cache.go:99`
- `managerConfigAdapter` — `adapters_config.go:13`
- `executorConfigAdapter` — `adapters_config.go:59`
- `managerStateUpdaterAdapter` — `adapters_manager.go:219`
- `bowlManagerCancellationAdapter` — `adapters_manager.go:250`
- `nilBowlManagerAdapter` — `adapters_manager.go:268`
- `managerServicesAdapter` — `adapters_services.go:27`
- `llmAdapter` — `adapters_services.go:53`
- `redisAdapter` — `adapters_services.go:121`
- `cacheRedisAdapter` — `adapters_services.go:136`
- `cacheArangoAdapter` — `adapters_services.go:151`
- `managerArangoAdapter` — `adapters_storage.go:12`

**Purpose**:
- Interface compatibility: Connect otherwise-incompatible interfaces
- Subsystem isolation: Subsystems define their own narrow interfaces
- Dependency inversion: Subsystems depend on abstractions, not on the concrete Manager

---

## 7. Facade

**Definition**: Provides a simplified, unified interface to a complex subsystem.

**Implementation**:
- **Files**: `chatbot/manager_core.go` (struct + constructor), `chatbot/main_handlers.go`
  (public API)
- **Facade**: the `Manager` struct
- **Simple public interface** (`chatbot/main_handlers.go`):
  ```go
  SubmitRequest(question, userID, requestID, conversationID string,
      prevContext []types.HistoryItem, lang string) (string, string, error)
  CancelStream(requestID string) error
  CancelAllStreams(userID string) error
  ```

**Hidden Complexity** (`chatbot/manager_core.go:60-96`):
```go
type Manager struct {
    // Request state management
    activeRequests     map[string]*types.RequestStream
    cancellableStreams map[string]*CancellableStreamItem
    requestsLock       sync.RWMutex

    // Resource limiting semaphores
    processingSemaphore chan struct{}
    llmStreamSemaphore  chan struct{}
    priorityRateLimiter chan struct{}

    // Subsystem managers
    queueManager        *queue.Manager
    cancellationHandler *cancellation.Handler
    cacheFastLane       *cache.FastLane
    bowlManager         *bowl.Manager

    // Cache fast-lane
    cacheRequestChan chan types.SubmitRequestArgs
    cacheWorkerPool  []*cacheWorker

    // Cache notification / re-evaluation
    cacheNotificationChan chan string
    cacheReevalWorker     *cache.ReevaluationWorker

    // Async database logging
    logQueue chan types.LogDataForDB
}
```

**Purpose**:
- Simplicity: Hide complex interactions behind a small API
- Centralized control: Single orchestration point
- Maintainability: Internal changes don't affect HTTP-layer clients

---

## 8. Proxy (Circuit Breaker)

**Definition**: A surrogate controls access to another object, adding functionality.

**Implementation**:
- **Files**: `core/model.go` (LLM wrapper), `core/services.go` (breaker construction)
- **Proxy**: `ResilientLLM` wraps the actual `llms.Model` client
- **Struct** (`core/model.go:58-62`):
  ```go
  type ResilientLLM struct {
      llm       llms.Model
      breaker   *gobreaker.CircuitBreaker
      modelName string
  }
  ```
- **Breaker construction** (`core/services.go:27-45`) via `github.com/sony/gobreaker`;
  breakers are created for LLM, Redis, and ArangoDB (`core/services.go:100-102`).

**Code Example** (`core/model.go:355-391`):
```go
func (r *ResilientLLM) GenerateContent(ctx context.Context, messages []llms.MessageContent,
    options ...llms.CallOption) (*llms.ContentResponse, error) {
    if err := ctx.Err(); err != nil {
        return nil, err
    }
    ctx, capture := WithErrorCapture(ctx)

    var response *llms.ContentResponse
    var opErr error

    _, err := r.breaker.Execute(func() (any, error) {
        res, err := r.llm.GenerateContent(ctx, messages, options...)
        if err != nil {
            // Context errors are not service failures - don't count them.
            if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
                opErr = err
                return nil, nil
            }
            return nil, err // Real error - counts toward tripping the breaker.
        }
        response = res
        return nil, nil
    })
    if err != nil { // Breaker tripped or a real service error occurred.
        err = EnrichLLMError(err, capture)
        r.handleLLMError(ctx, err, messages) // e.g. 429 alerting
        return nil, err
    }
    if opErr != nil {
        return nil, opErr
    }
    return response, nil
}
```

**Circuit Breaker States** (provided by `gobreaker`):
- **Closed**: Normal operation
- **Open**: Fails fast after the configured failure-rate threshold
- **Half-Open**: Tests whether the service has recovered

**Purpose**:
- Fault tolerance: Prevent cascading failures
- Resource protection: Fail fast when a dependency is unavailable
- Observability: Surface enriched provider errors (e.g. Gemini 429 bodies) and alert on them

---

## 9. Dependency Injection

**Definition**: A component receives its dependencies externally rather than creating them.

**Implementation**:
- **Constructor injection** for the Manager (`chatbot/manager_core.go:100`):
  ```go
  func NewManager(ctx context.Context, cfg *config.Settings, services *core.Services,
      arangoStore *db.ArangoStore, fixedAnswersLoader *fixedanswers.Loader) (*Manager, error)
  ```
- **Constructor injection** for subsystems, e.g. the cancellation handler
  (`chatbot/cancellation/handler.go:45`):
  ```go
  func NewHandler(mgr ManagerInterface, bowlMgr BowlManagerInterface) *Handler
  ```

**Code Example** — tools receive injected services
(`tools/toolcore/definitions.go:566`):
```go
func BuildAllTools(services *core.Services, arangoStore *db.ArangoStore,
    authStore interface{}) []DynamicTool {
    // each tool's executor closes over the injected services / arangoStore
}
```

**Purpose**:
- Testability: Inject mocks/adapters for unit tests
- Decoupling: Components don't construct their own dependencies
- Flexibility: Swap implementations (real vs. lorem-ipsum LLM, real vs. nil bowl manager)

---

## 10. Factory

**Definition**: Centralizes object-creation logic.

**Implementation**:
- **File**: `tools/toolcore/definitions.go`
- **Factory function** (`definitions.go:566`):
  ```go
  func BuildAllTools(services *core.Services, arangoStore *db.ArangoStore,
      authStore interface{}) []DynamicTool
  ```

**Code Example**:
```go
func BuildAllTools(services *core.Services, arangoStore *db.ArangoStore,
    authStore interface{}) []DynamicTool {
    allTools := []DynamicTool{
        {
            NameStr:        "get_current_time",
            DescriptionStr: "Returns current time",
            Executor: func(ctx context.Context, input string, logCtx zerolog.Logger) (string, error) {
                return time.Now().Format(time.RFC3339), nil
            },
        },
        // ... additional tools, each supplying its own executor strategy ...
    }
    return allTools
}
```

**Purpose**:
- Centralization: All tool definitions live in one place
- Abstraction: Callers don't know construction details
- Maintainability: Add or modify tools in a single location

---

## Pattern Interactions

### Request Processing Pipeline

```
Client → Facade (Manager.SubmitRequest / CancelStream)
       ↓
       Worker Pool (cacheWorker drains cacheRequestChan)
       ↓
       Cache fast-lane (cacheFastLane.HandleCachedRequest)
       │
       ├─ hit  → served immediately (StateFastLaneProcessing)
       │
       └─ miss → routeToNormalProcessing
                     ↓
                 Worker Pool (normalRequestWorker) + FIFO queue (DequeueRequestNormal)
                     ↓
                 Semaphore (processingSemaphore) in processRequest
                     ↓
                 Strategy + Factory (tools built by BuildAllTools, executed via LoggableTool)
                     ↓
                 Proxy (ResilientLLM.GenerateContent, circuit-breaker protected)
                     ↓
                 Bowl streaming/resume (bowlManager: accumulate + replay on reconnect)
                     ↓
                 Context Propagation (per-request cancel via cancellableStreams)
                     ↓
                 State (RequestState transitions)
                     ↓
                 Adapter (subsystems integrate through narrow adapter interfaces)
```

The priority fast-lane (`priorityRequestWorker` + `priorityRateLimiter`) is a parallel
path for cache-promoted requests that bypasses the normal `processingSemaphore`.

---

## Anti-Patterns Avoided

1. **No Global State**: State is managed through dependency injection and the Manager
2. **No Circular Dependencies**: Subsystems depend on narrow adapter interfaces
3. **No God Object**: Manager is a facade orchestrating subsystems, not a monolith
4. **No Tight Coupling**: Interfaces (adapters) separate concerns
5. **Cancellation-Aware**: Context propagation and `ctx.Done()` checks throughout
6. **No Resource Leaks**: Deferred semaphore release and context-driven goroutine teardown

---

## Summary

The codebase uses the following patterns, all verified against current source:

- **Concurrency**: semaphores (`processingSemaphore` / `llmStreamSemaphore` /
  `priorityRateLimiter`), worker pools (cache + normal + priority workers), and
  context propagation for cancellation
- **Behavioral**: strategy (tool executors) and state (request lifecycle)
- **Structural**: adapter (many implementations across `adapters_*.go`), facade
  (`Manager`), and proxy (`ResilientLLM` circuit breaker)
- **Creational**: dependency injection (`NewManager`, subsystem constructors) and
  factory (`BuildAllTools`)

Together they deliver:
- **Cache-first serving** via the fast-lane worker pool before any LLM work
- **Bounded concurrency** via the single processing semaphore plus the LLM-stream and
  priority limiters
- **Fault tolerance** via the gobreaker circuit breakers wrapping LLM/Redis/Arango
- **Resumable streaming** via the bowl system's accumulate-and-replay pipes
- **Maintainability** via adapters, the Manager facade, and dependency injection
