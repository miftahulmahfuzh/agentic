---
title: "Circuit Breaker Pattern"
date: 2025-08-12
lastmod: 2026-07-09
draft: false
---

## Overview

The Circuit Breaker pattern is a resilience pattern designed to prevent cascading failures in distributed systems. It acts as a protective barrier between your application and potentially unreliable external services, preventing your entire system from failing when a downstream dependency becomes unavailable or starts responding slowly.

This implementation uses the [`github.com/sony/gobreaker`](https://github.com/sony/gobreaker) library to create circuit breakers for three services (LLM, Redis, and ArangoDB) with customized configurations based on each service's characteristics and reliability expectations.

The breakers are constructed and wired in [`core/services.go`](../../core/services.go). Each breaker is then *injected* into the client that owns the corresponding connection, so the resilience logic is encapsulated inside `ResilientLLM`, `db.RedisStore`, and `db.ArangoStore` rather than scattered across call sites.

## Circuit Breaker States

A circuit breaker operates in three states:

1. **Closed**: Normal operation. All requests pass through to the service. Failures are counted.
2. **Open**: The service is considered unhealthy. All requests are immediately rejected (with `gobreaker.ErrOpenState`) without calling the service.
3. **Half-Open**: Testing phase. After the `Timeout` elapses, a limited number of requests (`MaxRequests`) are allowed through to test if the service has recovered. If they succeed, the breaker returns to Closed; if any fail, it returns to Open.

## Parameter Configuration

The `newCircuitBreaker` helper accepts six parameters. Its signature, verified in [`core/services.go:27`](../../core/services.go), is:

```go
func newCircuitBreaker(
    name string,
    maxRequests uint32,
    interval time.Duration,
    timeout time.Duration,
    failureRateThreshold float64,
    minRequests uint32,
) *gobreaker.CircuitBreaker
```

### Parameter Descriptions

#### `name` (string)
The identifier for the circuit breaker, used for logging and monitoring. It is passed straight through to `gobreaker.Settings.Name` and appears in the `OnStateChange` log line, so you can tell which service tripped.

#### `maxRequests` (uint32)
Maps to `gobreaker.Settings.MaxRequests`. **Applies only to the Half-Open state.** After the timeout expires and the breaker enters Half-Open, this is how many test requests are allowed through. If they succeed, the breaker closes; if any fail, it re-opens immediately.

#### `interval` (time.Duration)
Maps to `gobreaker.Settings.Interval`. **The cyclic window** over which the breaker accumulates counts while Closed; when the interval elapses, the internal counts are cleared. Setting this to `0` disables the periodic clearing, so counts would accumulate indefinitely — avoid that.

#### `timeout` (time.Duration)
Maps to `gobreaker.Settings.Timeout`. **The penalty period.** When the breaker trips to Open, it stays there for this duration, rejecting all requests immediately, before transitioning to Half-Open to probe recovery.

#### `failureRateThreshold` (float64)
Used inside the `ReadyToTrip` callback. When the ratio `TotalFailures / Requests` within the current window reaches or exceeds this threshold, the breaker trips to Open. Value is between `0.0` (0%) and `1.0` (100%).

#### `minRequests` (uint32)
Used inside `ReadyToTrip` as a floor: the breaker will not trip unless it has observed at least this many requests in the current window. This prevents a couple of failures in a low-traffic window from tripping the breaker on noise.

## `newCircuitBreaker` Implementation

The helper wraps `gobreaker.NewCircuitBreaker` with a ratio-based `ReadyToTrip` and a state-change logger. Verified against [`core/services.go:27-45`](../../core/services.go):

```go
func newCircuitBreaker(name string, maxRequests uint32, interval time.Duration, timeout time.Duration, failureRateThreshold float64, minRequests uint32) *gobreaker.CircuitBreaker {
	return gobreaker.NewCircuitBreaker(gobreaker.Settings{
		Name:        name,
		MaxRequests: maxRequests, // For Half-Open state probes. Keep it low.
		Interval:    interval,    // THE SLIDING WINDOW. DON'T SET THIS TO 0.
		Timeout:     timeout,     // Penalty box time after tripping.
		ReadyToTrip: func(counts gobreaker.Counts) bool {
			// Don't trip if we haven't seen enough traffic to make a decision.
			if counts.Requests < minRequests {
				return false
			}
			failureRate := float64(counts.TotalFailures) / float64(counts.Requests)
			return failureRate >= failureRateThreshold
		},
		OnStateChange: func(name string, from gobreaker.State, to gobreaker.State) {
			log.Info().Str("breaker", name).Str("from", from.String()).Str("to", to.String()).Msg("Circuit Breaker state changed.")
		},
	})
}
```

## Service-Specific Configurations

The three breakers are created at the top of `NewServices`. Verified against [`core/services.go:100-102`](../../core/services.go):

```go
llmCB := newCircuitBreaker("LLM", 2, 15*time.Second, 60*time.Second, 0.5, 1000)
redisCB := newCircuitBreaker("Redis", 3, 10*time.Second, 30*time.Second, 0.6, 1000)
arangoCB := newCircuitBreaker("ArangoDB", 5, 5*time.Second, 30*time.Second, 0.5, 1000)
```

> **Note on `minRequests`:** All three breakers currently use `minRequests = 1000`. This is a deliberately high floor: the breaker will not trip until it has observed at least 1000 requests within a single interval window. Combined with the short intervals below, this makes the breakers effectively very conservative — they only open under sustained, high-volume failure, and will not trip on sparse errors in low-traffic windows. The per-service `interval`, `timeout`, `maxRequests`, and `failureRateThreshold` values below still shape behavior once that request floor is crossed.

### LLM Circuit Breaker
`newCircuitBreaker("LLM", 2, 15*time.Second, 60*time.Second, 0.5, 1000)`

**Configuration reasoning:**
- **15-second window (`interval`)**: Enough time to observe patterns in LLM response behavior.
- **50% failure threshold**: Moderate tolerance, as LLM services can be inherently variable.
- **60-second timeout**: Longer recovery period accounts for the time LLM services need to stabilize.
- **2 test requests in Half-Open**: Conservative probing for expensive LLM calls.
- **`minRequests` = 1000**: High request floor before the failure ratio is even evaluated (see note above).

**Use case:** Suitable for slow, expensive, and potentially variable services like Large Language Models.

### Redis Circuit Breaker
`newCircuitBreaker("Redis", 3, 10*time.Second, 30*time.Second, 0.6, 1000)`

**Configuration reasoning:**
- **10-second window (`interval`)**: Faster detection for a service that should respond quickly.
- **60% failure threshold**: More tolerant of failures, as Redis is generally reliable and network blips are transient.
- **30-second timeout**: Quicker recovery expectation for a fast, reliable service.
- **3 test requests in Half-Open**: Moderate testing approach.
- **`minRequests` = 1000**: High request floor before the failure ratio is even evaluated (see note above).

**Use case:** Optimized for fast, high-throughput services that are generally reliable but may experience occasional network issues.

### ArangoDB Circuit Breaker
`newCircuitBreaker("ArangoDB", 5, 5*time.Second, 30*time.Second, 0.5, 1000)`

**Configuration reasoning:**
- **5-second window (`interval`)**: Very responsive to recent problems.
- **50% failure threshold**: Less tolerant of failures for a critical database service.
- **30-second timeout**: Quick recovery expectation for a database service.
- **5 test requests in Half-Open**: More thorough testing before fully reopening.
- **`minRequests` = 1000**: High request floor before the failure ratio is even evaluated (see note above).

**Use case:** Designed for critical, high-throughput database services that should be consistently available and performant. Note that ArangoDB is also wrapped in an infinite connect-retry loop (`initArangoWithRetry`) at startup because it is vital to the chatbot — see the wiring section below.

## Wiring: the `Services` struct and `NewServices`

The breakers are injected into their owning clients during `NewServices`. The container struct, verified at [`core/services.go:18-24`](../../core/services.go):

```go
type Services struct {
	LLM         *ResilientLLM
	Tokenizer   *tiktoken.Tiktoken
	RedisClient *db.RedisStore
	ArangoStore *db.ArangoStore
	DataStore   *DataStore // Centralized JSON data store (concept sectors, mappings, etc.)
}
```

The constructor creates the three breakers, then injects each into its client. Note that the tokenizer is now built separately via `NewTokenizer()` (it is no longer returned by `NewResilientLLM`), and ArangoDB is initialized through a retry loop. Condensed from [`core/services.go:98-189`](../../core/services.go):

```go
func NewServices(ctx context.Context, cfg *config.Settings) (*Services, error) {
	// --- Create all circuit breakers first ---
	llmCB := newCircuitBreaker("LLM", 2, 15*time.Second, 60*time.Second, 0.5, 1000)
	redisCB := newCircuitBreaker("Redis", 3, 10*time.Second, 30*time.Second, 0.6, 1000)
	arangoCB := newCircuitBreaker("ArangoDB", 5, 5*time.Second, 30*time.Second, 0.5, 1000)

	// --- Initialize services, injecting their respective circuit breakers ---
	tokenizer, tokenizerErr := NewTokenizer()
	if tokenizerErr != nil {
		return nil, fmt.Errorf("❌ Failed to initialize Tokenizer: %w", tokenizerErr)
	}

	llm, llmErr := NewResilientLLM(ctx, cfg, llmCB)
	if llmErr != nil {
		return nil, fmt.Errorf("❌ (CircuitBreaker) - Failed to initialize LLM: %w", llmErr)
	}

	redisStore, redisErr := db.NewRedisStore(ctx, cfg, redisCB)
	if redisErr != nil {
		log.Warn().Err(redisErr).Msg("❌ (CircuitBreaker) - Failed to initialize Redis.")
	}

	// ArangoDB is vital - retry until connected (breaker is injected inside)
	arangoStore, err := initArangoWithRetry(ctx, cfg, arangoCB)
	if err != nil {
		return nil, fmt.Errorf("❌ Failed to initialize ArangoDB after all retries: %w", err)
	}

	// ... DataStore initialization and question-template bootstrap omitted ...

	return &Services{
		LLM:         llm,
		Tokenizer:   tokenizer,
		RedisClient: redisStore,
		ArangoStore: arangoStore,
		DataStore:   dataStore,
	}, nil
}
```

The injected constructors all accept a `*gobreaker.CircuitBreaker`:

- `NewResilientLLM(_ context.Context, cfg *config.Settings, llmCB *gobreaker.CircuitBreaker) (*ResilientLLM, error)` — [`core/model.go:66`](../../core/model.go)
- `db.NewRedisStore(ctx context.Context, cfg *config.Settings, redisCB *gobreaker.CircuitBreaker) (*RedisStore, error)` — [`db/redis.go:27`](../../db/redis.go)
- `db.NewArangoStore(ctx context.Context, cfg *config.Settings, arangoCB *gobreaker.CircuitBreaker) (*ArangoStore, error)` — [`db/arango.go:48`](../../db/arango.go)

Each client stores the breaker on a private `breaker *gobreaker.CircuitBreaker` field (`ResilientLLM` at [`core/model.go:57-62`](../../core/model.go), `RedisStore` at [`db/redis.go:17-23`](../../db/redis.go), `ArangoStore` at [`db/arango.go:23-42`](../../db/arango.go)).

## How the Breaker Wraps a Call

Construction is only half the story — the breaker only helps if every outbound call goes through `breaker.Execute(...)`. Here is the actual LLM path, verified against `ResilientLLM.GenerateContent` at [`core/model.go:355-391`](../../core/model.go):

```go
func (r *ResilientLLM) GenerateContent(ctx context.Context, messages []llms.MessageContent, options ...llms.CallOption) (*llms.ContentResponse, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}

	ctx, capture := WithErrorCapture(ctx)

	var response *llms.ContentResponse
	var opErr error

	_, err := r.breaker.Execute(func() (any, error) {
		res, err := r.llm.GenerateContent(ctx, messages, options...)
		if err != nil {
			// Context errors are not service failures, so don't count them.
			if errors.Is(err, context.Canceled) || errors.Is(err, context.DeadlineExceeded) {
				opErr = err
				return nil, nil // Tell breaker it was successful.
			}
			return nil, err // Real error, count it.
		}
		response = res
		return nil, nil
	})
	if err != nil { // Breaker tripped or a real service error occurred.
		err = EnrichLLMError(err, capture)
		r.handleLLMError(ctx, err, messages) // 429 alerting
		return nil, err
	}
	if opErr != nil { // A context error occurred.
		return nil, opErr
	}

	return response, nil
}
```

Two subtleties worth internalizing, both of which recur in `GenerateFromSinglePrompt`/`Stream` ([`core/model.go:394-469`](../../core/model.go)) and in the Redis/Arango stores:

1. **Context cancellation is not a service failure.** When the underlying call fails with `context.Canceled` / `context.DeadlineExceeded`, the closure returns `(nil, nil)` so the breaker records a *success*, and the real error is smuggled out through the outer `opErr` variable. This keeps client-side cancellations from tripping the breaker. `db.RedisStore.Get` does the same for cache misses ([`db/redis.go:57-95`](../../db/redis.go)).
2. **The Open state surfaces as `gobreaker.ErrOpenState`.** When the breaker is Open, `Execute` returns immediately without calling the closure, and `err` is `gobreaker.ErrOpenState`. Callers can detect this to degrade gracefully.

### Breaker in action: detecting an open breaker

A real caller-side example lives in `StockAnalysisFromResearch` at [`tools/toolnonbe/equity_research.go:130-143`](../../tools/toolnonbe/equity_research.go). It queries ArangoDB (whose store owns the ArangoDB breaker) and translates the open-state error into a user-friendly "temporarily unavailable" message:

```go
doc, err := arangoStore.GetResearchDocByStockCode(ctx, code)
if err != nil {
	// Arango has its own CircuitBreaker, we just check the condition here
	if errors.Is(err, gobreaker.ErrOpenState) {
		logCtx.Warn().Err(err).Msg("ArangoDB circuit breaker is open. Not attempting query.")
		return "", fmt.Errorf("research database is temporarily unavailable")
	}
	// ... other error handling ...
}
```

This is the intended failure mode: when ArangoDB is unhealthy, the breaker short-circuits the query and the tool degrades gracefully instead of piling up slow, doomed requests.

## Benefits

- **Fail-fast behavior**: Prevents long timeouts and resource exhaustion when a dependency is down.
- **System stability**: Isolates failures to prevent cascading effects across services.
- **Automatic recovery**: The Half-Open state probes service health and resumes traffic when appropriate.
- **Configurable resilience**: Per-service tuning based on service characteristics.
- **Observability**: `OnStateChange` logging surfaces every state transition for monitoring.
- **Correct failure accounting**: Context cancellations and cache misses are deliberately *not* counted as service failures.

## Best Practices

1. **Configure based on service characteristics**: Fast services should have shorter intervals and timeouts; slower services may need longer windows.

2. **Set an appropriate `minRequests` floor**: Prevent false positives in low-traffic windows. (This codebase currently sets it high, at 1000, for all three breakers.)

3. **Monitor circuit breaker state changes**: Use the `OnStateChange` logging to understand system behavior and tune configurations.

4. **Route every outbound call through `breaker.Execute`**: A breaker only protects calls that actually go through it.

5. **Do not count client-side cancellations as failures**: Return `(nil, nil)` to the breaker for `context.Canceled` / `context.DeadlineExceeded` and surface the real error out-of-band.

6. **Handle `gobreaker.ErrOpenState` at the call site**: Implement graceful degradation (fallbacks, friendly messages) rather than propagating raw errors to users.
