---
title: "Busy Wait Loops"
date: 2025-07-12
lastmod: 2026-07-09
draft: false
---

If you're coming from Python, you've probably written `while not ready: time.sleep(0.1)`
at some point. That's a busy-wait loop (well, a polite one). This doc explains why the
pattern is wasteful, how Go's channels let you avoid it, and — most usefully — where
the *real* code in this chatbot uses the good pattern versus where it still (deliberately)
polls.

### What is a Busy-Wait Loop?

A busy-wait loop, or "spinning," is a technique where a process repeatedly checks a
condition in a tight loop. In its purest, most toxic form, it looks like this:

```go
// DO NOT EVER DO THIS
for doorIsClosed {
    // do nothing but loop
}
```

A goroutine running this code will consume 100% of a CPU core, doing absolutely nothing
useful. It's the software equivalent of flooring the accelerator of a car that's in
neutral. You're burning fuel, making a lot of noise, and going nowhere. The CPU is "busy"
while it "waits."

The harm is obvious:
1.  **Wasted CPU Cycles:** You are paying for computation that achieves nothing.
2.  **Resource Starvation:** Other goroutines that need the CPU can't get it.
3.  **Increased Power Consumption & Heat:** It's physically inefficient.

### The "Busy-Wait With Naps"

A slightly more civilized version — and the one you actually see in the wild — spins,
takes a short nap, then spins again:

```go
// A busy-wait with naps
ticker := time.NewTicker(100 * time.Millisecond)
for {
    // ... check some condition ...
    select {
    case <-ticker.C:
        continue // loop again after a short nap
    }
}
```

It's like a security guard told to watch a door. Instead of waiting for an alarm
(an event), he walks to the door, checks the handle, walks back, sits down for a minute,
then repeats the process all night. It's pointless, repetitive work.

Each time the timer fires, the Go runtime has to:
1.  Wake the goroutine.
2.  Schedule it to run on a CPU.
3.  The goroutine runs, acquires a lock, checks a map, releases the lock.
4.  The goroutine goes back to sleep.

For a request that takes 5 seconds to prepare, this ritual happens 50 times to learn
nothing 49 of those times. It's death by a thousand cuts.

### Channels: The Antidote to Busy-Waiting

The reason Go's event-driven style is so much better is that it leverages the runtime's
scheduler. When a goroutine blocks on a channel read (`<-myChan`), it's **not**
busy-waiting. The scheduler performs a "context switch":

1.  The goroutine's state is saved.
2.  It is removed from the list of runnable goroutines.
3.  A different goroutine is scheduled to run on that CPU core.

The waiting goroutine now consumes **zero CPU resources**. It is effectively frozen in
time until another goroutine sends data to that channel (`myChan <- data`). When that
send happens, the scheduler moves the waiting goroutine *back* into the runnable queue.

This is the fundamental difference:

*   **Busy-Wait:** *You* use the CPU to keep checking for an event.
*   **Channel Wait:** You tell the scheduler "wake me up when this event happens," and
    the CPU goes off to do other useful work in the meantime.

(For a Python analogy: a channel wait is closer to `await` on an `asyncio` event than to
a `while` loop with `sleep`. The scheduler parks you; it doesn't keep polling on your
behalf.)

---

## The Good Pattern in *This* Codebase

Here is the payoff. The chatbot's request pipeline is event-driven end to end. When an
HTTP handler asks for a request's result stream, it does **not** poll. It blocks on a
`select` over several channels and lets the scheduler wake it on the first event:

```go
// chatbot/manager.go — getRequestResultStream, the blocking select
select {
case stream := <-streamHolder.Stream:
    // the streamer handed us the live token channel — go serve it
case err := <-streamHolder.Err:
    // processing failed or was cancelled
case <-time.After(m.config.ProcessingTimeout):
    // a *bound*, not a poll — one wakeup after the whole timeout, not every 100ms
case <-ctx.Done():
    // the client's HTTP connection went away
}
```

See `chatbot/manager.go:1064`. Note the `time.After` here is a single upper bound on the
whole wait, not a nap in a loop — the goroutine sleeps once and is woken by whichever
event fires first. That's the correct use of `time.After`.

### Workers block on channels, not on clocks

The background workers that drain the queues are all the same shape: an infinite `for`
loop wrapped around a `select` that blocks until either work arrives or the context is
cancelled. No sleeping, no polling.

*   `normalRequestWorker` — `chatbot/manager.go:870`. Blocks on the normal FIFO channel;
    `case <-ctx.Done(): return` is the shutdown path.
*   `priorityRequestWorker` — `chatbot/manager.go:895`. Blocks on the priority (cache-jump)
    channel.
*   `cacheWorker.run` — `chatbot/manager.go:432`. Blocks on `m.cacheRequestChan`, with a
    second `<-cw.stopChan` case for a clean stop.

Each of these looks like:

```go
for {
    select {
    case <-ctx.Done():
        return
    case request := <-someChannel:
        // do the work
    }
}
```

An idle worker here costs nothing. Ten idle workers cost nothing. They're parked by the
scheduler until a send lands on their channel. Contrast that with ten workers each waking
every 100ms to check an empty queue.

### Semaphores are channels too

Go's idiom for "let at most N goroutines do X at once" is a buffered channel used as a
counting semaphore. Sending into it takes a slot (and *blocks* — cheaply — if all slots
are taken); receiving from it frees a slot. This is a channel wait, so a goroutine waiting
for a slot burns zero CPU.

Three of these guard the pipeline. They're declared in `chatbot/manager_core.go:66-70` and
sized in `NewManager` at `chatbot/manager_core.go:127-130`:

*   **`processingSemaphore`** (`make(chan struct{}, cfg.MaxConcurrentRequests)`) — caps how
    many requests run the preparer stage at once. Acquired at `chatbot/manager.go:514`
    (`m.processingSemaphore <- struct{}{}`) and released at `chatbot/manager.go:526`.
*   **`llmStreamSemaphore`** (`make(chan struct{}, cfg.MaxConcurrentLLMStreams)`) — caps
    concurrent LLM streams so a burst of prepared requests can't hammer the provider into
    429s. It's applied through the `runBoundedStream` wrapper at `chatbot/manager.go:780`:

    ```go
    func (m *Manager) runBoundedStream(streamFn func()) {
        if m.llmStreamSemaphore == nil {
            streamFn() // tests may leave it nil; run unbounded
            return
        }
        m.llmStreamSemaphore <- struct{}{}       // take a slot (blocks if full)
        defer func() { <-m.llmStreamSemaphore }() // release on return
        streamFn()
    }
    ```

    Both `executeTask` (`chatbot/manager.go:642`) and the fast-lane `executeTaskImmediate`
    (`chatbot/manager.go:767`) launch their streamer through it.
*   **`priorityRateLimiter`** (`make(chan struct{}, 100)`) — lightweight Redis-DoS guard on
    the priority fast-lane, acquired/released at `chatbot/manager.go:652-653`.

The health check even probes these semaphores with a **non-blocking** `select`
(`chatbot/manager.go:1463-1475`): a `case m.processingSemaphore <- struct{}{}:` with a
`default:` means "grab a slot if one is instantly free, otherwise report exhausted" — no
waiting at all.

### Closing a channel as a broadcast signal

Another event-driven trick: closing a channel wakes *every* goroutine blocked reading from
it. The request holder has a `ClientConnected chan struct{}` that starts open and is closed
exactly once, the moment the client attaches to the stream (`chatbot/manager.go:1052-1060`):

```go
if streamHolder.ClientConnected != nil {
    select {
    case <-streamHolder.ClientConnected:
        // already closed — do nothing
    default:
        close(streamHolder.ClientConnected) // fire the signal
    }
}
```

Anyone waiting on `<-streamHolder.ClientConnected` is released instantly, with no polling.
The `select`/`default` guard makes the close idempotent so a second connect attempt can't
panic with "close of nil/closed channel."

---

## When Polling Is Actually Fine (and Still Lives Here)

Purity is not the goal — correctness is. There are a few genuine polling loops left in the
codebase, and they're **justified**: they wait on state produced by a *detached* goroutine
or an external system where there is no channel to block on. In those cases a bounded poll
with a deadline is the pragmatic, correct choice.

### 1. The janitor — a legitimate periodic task

```go
// chatbot/manager.go:1202 — janitor
ticker := time.NewTicker(m.config.JanitorInterval)
defer ticker.Stop()
for {
    select {
    case <-ticker.C:
        m.cleanupTimedOutRequests()
        m.cleanupOldQueuedRequests()
    case <-ctx.Done():
        return
    }
}
```

This is **not** a busy-wait. It's a cron-like task that is *supposed* to run on a fixed
cadence — sweep for timed-out requests every `JanitorInterval`. A ticker is exactly the
right tool; there's no "event" to wait for, the passage of time *is* the event. The
`<-ctx.Done()` case gives it a clean shutdown. This is the good use of `time.NewTicker`.

### 2. Retry with exponential backoff on DB writes

`chatbot/state_management_enhanced.go:114` retries a failed ArangoDB state update, sleeping
between attempts — but it sleeps by racing `time.After(backoff)` against `ctx.Done()`:

```go
select {
case <-time.After(backoff):
    backoff = time.Duration(float64(backoff) * config.RetryMultiplier)
    if backoff > config.MaxBackoff {
        backoff = config.MaxBackoff
    }
case <-ctx.Done():
    result.Error = fmt.Errorf("database update retry cancelled: %w", ctx.Err())
    return result
}
```

The backoff *grows* each attempt (so it's not a tight loop), and it stays cancellable. The
external DB doesn't offer a "ready" channel, so bounded retry is the honest option.

### 3. Waiting on an async write to land — `time.Sleep` in a deadline loop

`chatbot/helpers/status.go:159` handles a real race: the initial request log is written to
ArangoDB *asynchronously* (via `m.logQueue`, see `chatbot/manager.go:352`), so a status
query can arrive before the row exists. It polls for up to 2 seconds:

```go
retryDuration := 2 * time.Second
retryInterval := 100 * time.Millisecond
retryDeadline := time.Now().Add(retryDuration)

for time.Now().Before(retryDeadline) {
    if response, found := CheckActiveRequestsState(...); found {
        return nil, nil
    }
    if requestExists, err := arangoStore.GetFinalRequestStatus(ctx, requestID); err == nil && requestExists != nil {
        return requestExists, nil
    }
    time.Sleep(retryInterval)
}
```

This *is* a busy-wait-with-naps in the classic sense — and it's the pragmatic exception,
not the rule. There is no channel that fires when a background DB write completes, so the
code polls with a hard deadline rather than blocking forever. `retryCancelledRaceCondition`
just below it (`chatbot/helpers/status.go:194`) does the same thing for the
cancelled-vs-active race.

If those async writes ever grew a completion channel, these loops could become blocking
channel reads — which is exactly the upgrade the request pipeline already made.

### 4. Waiting for a bowl to be created

`chatbot/bowl/manager.go:564` (`WaitForBowl`) polls every 100ms for a bowl that a separate
processing goroutine will create, again racing the poll against `ctx.Done()`:

```go
for time.Now().Before(deadline) {
    if bowl := m.GetBowl(requestID); bowl != nil {
        return bowl
    }
    select {
    case <-ctx.Done():
        return nil
    case <-time.After(pollInterval):
        // continue polling
    }
}
```

Same story: it's a resume-path convenience that waits on state created elsewhere, bounded
by a timeout and cancellable.

---

## The Rule of Thumb

*   **Waiting for something another goroutine in *your* program produces?** Use a channel.
    Block on it. The scheduler will wake you for free. This is what the request pipeline,
    workers, semaphores, and the `ClientConnected` signal all do.
*   **Running a task on a fixed cadence?** Use `time.NewTicker` in a `for { select }`
    (like the janitor). That's periodic work, not a busy-wait.
*   **Waiting on state from a detached goroutine or an external system that offers no
    signal channel?** A *bounded, cancellable* poll (deadline + `time.After`/`time.Sleep`,
    always with a `ctx.Done()` escape) is acceptable — see the retry and bowl loops above.
*   **`while (condition) {}` with no sleep and no channel?** Never. That's the toxic form.

The one thing to always avoid is spinning on the CPU to learn nothing. Everything else is
a judgment call about whether an event channel exists to wait on.
