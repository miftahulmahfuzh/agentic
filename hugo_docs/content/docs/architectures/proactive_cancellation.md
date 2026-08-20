---
title: "Proactive Cancellation"
date: 2026-07-09
draft: false
---

## Overview

This document defends a design choice that shows up all over the request
lifecycle: whenever a client goes away, the goroutine serving it should notice
*immediately* and return, rather than blocking on a channel until a background
"janitor" eventually reaps it.

The tempting shortcut is: *"We already have a janitor that sweeps timed-out
requests. Why bother making every send context-aware? Just let the janitor
clean it up."* The short answer is that the janitor is a safety net for the
cases nothing else caught, not a substitute for cleaning up on the way out. A
leaked goroutine that lives until the next janitor tick is not free — it holds
buffers and map entries, and it distorts the concurrency accounting the whole
system relies on.

Both mechanisms exist in the codebase today and both are correct. This note is
about *why we keep both* and what each is actually responsible for.

## What the janitor actually does today

There are two independent janitors, and neither one is fictional — they are
plain `time.Ticker` loops.

**Request janitor** — `chatbot/manager.go:1162` (`Manager.janitor`), started at
`chatbot/manager_core.go:325`. It wakes once per `JanitorInterval` (default
`2m`, `config/config.go:96`) and calls `cleanupTimedOutRequests`
(`chatbot/manager.go:1181`) and `cleanupOldQueuedRequests`. The timeout sweep
walks `activeRequests` under a read lock and flags anything whose
`LastStateChange` has aged past a state-specific threshold
(`chatbot/manager.go:1193`):

- `StateCancelled` older than `ClientPickupTimeout` (default `1s`, `config/config.go:99`)
- `StateQueued` older than `QueueTimeout` (default `1h`, `config/config.go:98`)
- `StateTaskExecution` / `StateFastLaneProcessing` older than `ProcessingTimeout` (default `10m`, `config/config.go:97`)

For each flagged request it pushes an error onto `streamHolder.Err` and calls
`CleanupRequest` (`chatbot/manager.go:1230`).

**Bowl janitor** — `chatbot/bowl/manager.go:132`, whose `cleanup` method
(`chatbot/bowl/manager.go:423`) deletes bowls that have outlived their TTL
(`ResponseBowl.IsExpired`), closing each one's pipe as it goes.

Notice the timeouts. A request stuck in processing is not touched for **ten
minutes**. A request sitting in the queue is not touched for **an hour**. Those
numbers are correct for their purpose — they are backstops against genuinely
wedged state — but they are catastrophic as a primary cleanup path. If a client
disconnects three seconds into a stream and we wait for the janitor, that
goroutine and its buffers linger for up to `ProcessingTimeout` before anyone
notices.

(For why the janitor polls on a timer instead of arming one timer per request,
see the sibling note [`event_driven_janitor.md`](../event_driven_janitor/).
That document argues polling is the right call for the *backstop*; this one
argues the backstop should rarely be the thing that fires.)

## The reactive path: wait for the janitor

If a goroutine's only exit is "finish the work or get reaped," then a
disconnected client leaves it blocked on a send. Concretely, streaming events
flow through buffered channels, and a naive `streamChan <- event` blocks once
the buffer fills and nobody is reading. That goroutine is now parked until the
janitor's `ProcessingTimeout` sweep tears the request down.

While it waits, it is not inert:

- **It holds concurrency budget.** Normal requests run under
  `processingSemaphore`, a buffered channel of size `MaxConcurrentRequests`
  (default `50`, `config/config.go:92`; declared at
  `chatbot/manager_core.go:66`, sized at `chatbot/manager_core.go:127`). A
  parked worker that acquired its slot at `chatbot/manager.go:514` has not yet
  hit the release at `chatbot/manager.go:526`, so it is holding one of the 50
  slots hostage. The companion `llmStreamSemaphore`
  (`MaxConcurrentLLMStreams`, default `5`, `config/config.go:93`) is meant to
  cap concurrent LLM streams on the same principle. `HealthCheck`
  (`chatbot/manager.go:1424`, `chatbot/manager.go:1431`) probes both
  semaphores non-blockingly, so exhausted slots surface as an unhealthy
  server — a parked goroutine can literally fail your health check.
- **It holds memory.** The event buffer, the accumulated response, and the
  goroutine stack all stay resident until cleanup.
- **It muddies the accounting.** Every "how loaded are we?" signal in the
  system is derived from these counters, and a zombie inflates all of them.

Multiply by a handful of abandoned mobile connections and the effective
capacity of a 50-slot server can quietly collapse, with nothing wrong in the
logs until the janitor finally sweeps.

## The proactive path: cleanup on `ctx.Done()`

The alternative is to make every blocking send *also* select on the request's
context. The moment the client disconnects, the request context is cancelled,
the send unblocks with an error, and the goroutine unwinds — releasing its
semaphore slot, its buffers, and its map entry right away instead of minutes
later.

This pattern appears at each layer that can block on a client channel:

- **Streamer.** `Streamer.sendError` (`chatbot/processing/streamer.go:319`)
  selects on `ctx.Done()` versus `streamChan <- event` and simply `return`s if
  the context is already gone. The canonical form of this send is also exported
  as a reusable helper, `processing.SendEvent`
  (`chatbot/processing/streamer_strategy_helpers.go:54`).
- **Cache fast-lane.** `FastLane.sendEvent`
  (`chatbot/cache/fastlane.go:429`) selects on `ctx.Done()`, the send, *and* a
  bounded `time.After` timeout, so it can never park forever even if the
  context outlives the reader. It is the send primitive for every fast-lane
  emission (`chatbot/cache/fastlane.go:233`, `:242`, `:267`).
- **Bowl.** The bowl takes a slightly different tack. `safeSendEvent`
  (`chatbot/bowl/bowl.go:562`) and the exported `SafeSendEvent`
  (`chatbot/bowl/bowl.go:582`) use a non-blocking `select`/`default` guarded by
  panic recovery: if the pipe is full or closed, the send is dropped rather
  than blocking. Same goal — never park a goroutine on a dead reader — reached
  by never blocking in the first place.

Because the request context is cancelled the instant a client disconnects (and
explicit cancellation flows through the same context), these sends turn "block
until the janitor reaps me" into "return now."

## Explicit cancellation uses the same discipline

When a client explicitly cancels, the cancellation handler does not wait for a
sweep either. `Handler.handleRequestCancellation`
(`chatbot/cancellation/handler.go:108`) calls `CleanupRequest` straight away,
and the surrounding flow then calls `finalizeActiveRequestsPurge`
(`chatbot/cancellation/handler.go:148`) to purge the request from
`activeRequests` so a resubmission with the same ID can proceed immediately.
There is a single, unconditional cleanup path here — cancellation is handled
one way, promptly, and the request is gone.

## The bowl is a single handoff, not a fan-out

Proactive cleanup does not mean throwing away in-flight work when a client
drops. The `bowl` mechanism lets a reconnecting client resume a response that is
still being produced. Crucially it is a **one-to-one** handoff: a bowl owns a
single `ActivePipe` (`chatbot/bowl/bowl.go:44`), and acquiring a new pipe
(`chatbot/bowl/bowl.go:203`) first closes any existing one to preserve
exclusivity before replaying buffered events into the fresh pipe. One producer,
one live consumer at a time. Resume is a clean handoff of that single pipe — not
a subscription model — which is exactly why a disconnect can free the old pipe
immediately and a reconnect can claim a new one without racing anyone else.

## The fast lane never parks at all

Worth noting: the true fast-lane path (`Manager.executeTaskImmediate`,
`chatbot/manager.go:644`) deliberately skips `processingSemaphore` entirely,
using only a lightweight `priorityRateLimiter` (`chatbot/manager.go:649`) and
launching the stream directly (`chatbot/manager.go:761`). Its cancellation
checks are sprinkled throughout (`chatbot/manager.go:659`, `:714`, `:741`,
`:747`) so it bails the moment the request is cancelled. Because it holds no
processing slot, it has even less to leak — but it still honors the same
context-first discipline on every send.

## Summary

| | Reactive (janitor-only) | Proactive (context-aware cleanup) |
| :-- | :-- | :-- |
| **Trigger** | Timer tick, up to `ProcessingTimeout` (`10m`) later | `ctx.Done()`, immediate on disconnect/cancel |
| **Semaphore slot** | Held hostage until the sweep | Released as the goroutine unwinds |
| **Memory** | Buffers + stack resident until reaped | Freed at return |
| **Capacity signal** | Counters inflated by zombies | Counters track reality |
| **Role** | Backstop for genuinely wedged state | Primary cleanup for the common case |

Neither mechanism is redundant. The janitor is the last line of defense for
requests that somehow slip past every context check — and there should always be
a last line of defense. But it is a backstop, tuned with minute- and hour-scale
timeouts precisely because it is *not* supposed to fire in the normal flow. The
context-aware sends are what keep the normal flow clean, so that by the time the
janitor wakes up, there is usually nothing left for it to sweep.
