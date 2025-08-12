---
title: "Circuit Breaker Pattern"
date: 2025-08-12
draft: false
---

## Overview

The Circuit Breaker pattern is a resilience pattern designed to prevent cascading failures in distributed systems. It acts as a protective barrier between your application and potentially unreliable external services, preventing your entire system from failing when a downstream dependency becomes unavailable or starts responding slowly.

This implementation uses the `gobreaker` library to create circuit breakers for different services (LLM, Redis, and ArangoDB) with customized configurations based on each service's characteristics and reliability expectations.

## Circuit Breaker States

A circuit breaker operates in three states:

1. **Closed**: Normal operation. All requests pass through to the service.
2. **Open**: The service is considered unhealthy. All requests are immediately rejected without calling the service.
3. **Half-Open**: Testing phase. A limited number of requests are allowed through to test if the service has recovered.

## Parameter Configuration

The `newCircuitBreaker` function accepts the following parameters:

```go
newCircuitBreaker(name, maxRequests, interval, timeout, failureRateThreshold, minRequests)
```

### Parameter Descriptions

#### `name` (string)
The identifier for the circuit breaker, used for logging and monitoring purposes. This helps you identify which service is experiencing issues in your logs.

#### `maxRequests` (uint32)
**Applies only to Half-Open state.** After the circuit breaker has been in the Open state and the timeout period expires, it enters Half-Open state. This parameter defines how many test requests are allowed through during this phase. If all test requests succeed, the breaker returns to Closed state. If any fail, it immediately returns to Open state.

#### `interval` (time.Duration)
**The sliding window duration.** This defines the time window over which the circuit breaker evaluates request statistics. All success and failure metrics are calculated based on requests made within this rolling time window.

**Important:** Setting this to 0 will prevent the breaker from resetting its counts, making it ineffective.

#### `timeout` (time.Duration)
**The penalty period.** When the circuit breaker trips and enters the Open state, it remains in this state for the specified timeout duration. During this time, all requests are rejected immediately without attempting to call the service.

#### `failureRateThreshold` (float64)
**The failure percentage that triggers the breaker.** When the percentage of failed requests within the sliding window reaches or exceeds this threshold, the circuit breaker will trip to Open state. Value should be between 0.0 (0%) and 1.0 (100%).

#### `minRequests` (uint32)
**The minimum sample size required.** The circuit breaker will not consider tripping unless it has observed at least this many requests within the current sliding window. This prevents single failures in low-traffic scenarios from unnecessarily triggering the breaker.

## Service-Specific Configurations

### LLM Circuit Breaker
```go
llmCB = newCircuitBreaker("LLM", 2, 15*time.Second, 60*time.Second, 0.5, 5)
```

**Configuration reasoning:**
- **15-second sliding window**: Provides enough time to observe patterns in LLM response behavior
- **Minimum 5 requests**: Ensures statistical significance before considering a trip
- **50% failure threshold**: Moderate tolerance, as LLM services can be inherently variable
- **60-second timeout**: Longer recovery period accounts for the time needed for LLM services to stabilize
- **2 test requests in Half-Open**: Conservative approach for expensive LLM calls

**Use case:** Suitable for slow, expensive, and potentially variable services like Large Language Models.

### Redis Circuit Breaker
```go
redisCB = newCircuitBreaker("Redis", 3, 10*time.Second, 30*time.Second, 0.6, 10)
```

**Configuration reasoning:**
- **10-second sliding window**: Faster detection for a service that should respond quickly
- **Minimum 10 requests**: Higher threshold reflects expected high throughput
- **60% failure threshold**: More tolerant of failures, as Redis is generally reliable
- **30-second timeout**: Quicker recovery expectation for a fast, reliable service
- **3 test requests in Half-Open**: Moderate testing approach

**Use case:** Optimized for fast, high-throughput services that are generally reliable but may experience occasional network issues.

### ArangoDB Circuit Breaker
```go
arangoCB = newCircuitBreaker("ArangoDB", 5, 5*time.Second, 30*time.Second, 0.5, 10)
```

**Configuration reasoning:**
- **5-second sliding window**: Very responsive to recent problems
- **Minimum 10 requests**: Expects high traffic volume
- **50% failure threshold**: Less tolerant of failures for a critical database service
- **30-second timeout**: Quick recovery expectation for a database service
- **5 test requests in Half-Open**: More thorough testing before fully reopening

**Use case:** Designed for critical, high-throughput database services that should be consistently available and performant.

## Implementation Example

```go
type Services struct {
	LLM         *ResilientLLM
	Tokenizer   *tiktoken.Tiktoken
	RedisClient *db.RedisStore
	ArangoStore *db.ArangoStore
}

// Creates a new circuit breaker with a sane, ratio-based configuration.
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

// This function initializes all external clients, passing the resilience patterns (circuit breakers)
// into them for encapsulation.
func NewServices(ctx context.Context, cfg *config.Settings) (*Services, error) {
	// --- Create all circuit breakers first ---
	llmCB := newCircuitBreaker("LLM", 2, 15*time.Second, 60*time.Second, 0.5, 5)
	redisCB := newCircuitBreaker("Redis", 3, 10*time.Second, 30*time.Second, 0.6, 10)
	arangoCB := newCircuitBreaker("ArangoDB", 5, 5*time.Second, 30*time.Second, 0.5, 10)

	// --- Initialize services, injecting their respective circuit breakers ---
	llm, tokenizer, llmErr := NewResilientLLM(ctx, cfg, llmCB)
	if llmErr != nil {
		return nil, fmt.Errorf("❌ (CircuitBreaker) - Failed to initialize LLM & Tokenizer: %w", llmErr)
	}

	redisStore, redisErr := db.NewRedisStore(ctx, cfg, redisCB)
	if redisErr != nil {
		log.Warn().Err(redisErr).Msg("❌ (CircuitBreaker) - Failed to initialize Redis.")
	}

	arangoStore, arangoErr := db.NewArangoStore(ctx, cfg, arangoCB)
	if arangoErr != nil {
		log.Warn().Err(arangoErr).Msg("❌ (CircuitBreaker) - Failed to initialize ArangoDB")
	}

	return &Services{
		LLM:         llm,
		Tokenizer:   tokenizer,
		RedisClient: redisStore,
		ArangoStore: arangoStore,
	}, nil
}
```

## Benefits

- **Fail-fast behavior**: Prevents long timeouts and resource exhaustion
- **System stability**: Isolates failures to prevent cascading effects
- **Automatic recovery**: Tests service health and automatically resumes traffic when appropriate
- **Configurable resilience**: Allows fine-tuning based on service characteristics
- **Observability**: Provides logging and state change notifications for monitoring

## Best Practices

1. **Configure based on service characteristics**: Fast services should have shorter intervals and timeouts, while slower services may need longer windows.

2. **Set appropriate minimum request thresholds**: Prevent false positives in low-traffic scenarios.

3. **Monitor circuit breaker state changes**: Use the logging output to understand system behavior and adjust configurations.

4. **Test your configurations**: Verify that your settings provide the right balance between sensitivity and stability for your specific use case.

5. **Consider fallback strategies**: Implement graceful degradation when services are unavailable rather than just failing requests.
