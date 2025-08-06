---
title: "RAG Questions Part 1"
date: 2025-08-06
draft: false
---

## Question 1

The delta calculation seems convoluted.

```go
var delta string
if after, ok := strings.CutPrefix(payload.Content, previousContent); ok {
    delta = after
} else {
    logCtx.Warn().Str("previous", previousContent).Str("current", payload.Content).Msg("Stream content diverged, sending full payload.")
    delta = payload.Content
}
previousContent = payload.Content

if delta == "" {
    continue
}
```

How exactly does this work, and more importantly, how does it handle bizarre edge cases like repeating words or fully duplicate stream events? It seems fragile.

---

## Answer

You're questioning the most critical piece of the stream consumer. Your skepticism is warranted, but your conclusion that it's fragile is wrong. This logic is a hardened solution to a common, and frankly annoying, API design pattern.

### The "Why": An Inefficient API Pattern

First, understand the problem this code solves. The Tencent RAG API does not send *just the new characters* (the "token"). In each event, it sends the **entire accumulated string from the very beginning**.

It behaves like Bill Murray in *Groundhog Day*, forced to relive the entire sentence over and over just to add one more word at the end.

*   Event 1: `{"content": "The"}`
*   Event 2: `{"content": "The answer"}`
*   Event 3: `{"content": "The answer is"}`

If we just forwarded `content` to the UI, the user would see a flickering mess: "The", then "The answer", then "The answer is". We need to calculate the *difference*—the delta—to provide a smooth, word-by-word stream.

### The "How": `strings.CutPrefix`

The logic is a precise surgical tool:

1.  `previousContent` stores the full string from the last event.
2.  `strings.CutPrefix(payload.Content, previousContent)` attempts to cut the *previous* string off the front of the *current* string.
3.  **If it succeeds** (`ok` is `true`), the leftover piece (`after`) is our delta.
    *   `strings.CutPrefix("The answer", "The")` -> `ok=true`, `after=" answer"`. This is our delta.
4.  `previousContent` is then updated to the current full string, preparing it for the next event.

### Scenario 1: Repeating Words (e.g., "fox...fox")

Let's test this against a repeating word. Does it get confused? **No.**

*   **State:** `previousContent` = `"The quick brown fox jumps"`
*   **Next Event:** `payload.Content` = `"The quick brown fox jumps fox"`
*   **Execution:** `strings.CutPrefix("The quick brown fox jumps fox", "The quick brown fox jumps")`
*   **Result:** `ok` is `true`, `after` is `" fox"`.
*   **Action:** The delta `" fox"` is correctly identified as new text and is sent down the channel. The logic performs perfectly.

### Scenario 2: Duplicate Events (Stream "Stutter")

What if the API stutters and sends the exact same event twice? This is where the `if delta == "" { continue }` shines.

*   **State:** `previousContent` = `"The quick brown fox"`
*   **Next Event (Duplicate):** `payload.Content` = `"The quick brown fox"`
*   **Execution:** `strings.CutPrefix("The quick brown fox", "The quick brown fox")`
*   **Result:** `ok` is `true`, but `after` is `""` (an empty string).
*   **Action:** `delta` is `""`. The `if` condition is met, and the `continue` statement skips to the next iteration of the loop. **Nothing is sent down the channel.** This is correct. The system identified a worthless, duplicate event and discarded it, preventing noise in the stream. It's like seeing a glitch in the Matrix, recognizing it, and moving on without alarm.

This logic is not fragile. It's a robust mechanism designed specifically to handle the redundancy of an accumulative streaming API while gracefully managing common network and data anomalies.

---

## Question 2

The code uses `for {}` and a `select` statement.

```go
for {
    select {
    case <-ctx.Done():
        logCtx.Warn().Msg("Context cancelled during SSE stream processing.")
        return ctx.Err()
    default:
    }
    // ... read from stream ...
}
```

This looks like an infinite loop waiting to happen. How is this not a bug? How does this loop possibly know when the RAG stream is actually finished?

---

## Answer

You are correct that `for {}` is Go's idiomatic `while True`. You are incorrect to assume it's a bug. This is the foundational pattern for any long-running I/O consumer. The loop itself is designed to run forever, but the code *inside it* is actively looking for one of several termination signals.

Thinking this loop doesn't know when to stop is like thinking Anton Chigurh doesn't know when the job is done in *No Country for Old Men*. The process is relentless, but it has very clear conditions for termination.

Here are the five ways this "infinite" loop terminates, from a successful mission to a catastrophic failure.

### 1. The Logical "I'm Done": `payload.IsFinal`

The API itself can declare that it's finished. Inside the JSON payload, there's a flag: `IsFinal: true`.

```go
if payload.IsFinal {
    logCtx.Info().Msg("Final RAG content received and streamed.")
    break // EXIT
}
```

This is the API giving its final monologue. Once our code sees this, it knows the sequence is complete and uses `break` to exit the loop.

### 2. The Protocol "I'm Done": `data: [DONE]`

Some SSE implementations send a final, literal string `[DONE]` to terminate the stream.

```go
if dataStr == "[DONE]" {
    logCtx.Info().Msg("Received SSE end marker [DONE].")
    break // EXIT
}
```

This is a formal protocol signal, like a self-destruct sequence announcing its completion. Our code listens for it and `break`s.

### 3. The Physical "End of the Line": `io.EOF`

When the server has sent all its data and gracefully closes the connection, the `reader.ReadString('\n')` call will eventually fail with a special error: `io.EOF` (End of File).

```go
line, err := reader.ReadString('\n')
if err == io.EOF {
    logCtx.Info().Msg("SSE stream ended normally (EOF).")
    break // EXIT
}
```

This is the physical equivalent of the phone line going dead after the conversation is over. It's a clean, normal termination.

### 4. The External "Abort Mission": `ctx.Done()`

This is the emergency brake. The `context` passed into this function can be cancelled by an upstream caller (e.g., due to a request timeout or user clicking "cancel").

```go
select {
case <-ctx.Done():
    return ctx.Err() // EXIT
}
```

On every single loop, this code checks for the abort signal. This is Commander Cody receiving "Execute Order 66." The current mission is terminated *immediately* and the function returns with an error.

### 5. The Catastrophic Failure: Any Other Error

If anything else goes wrong—the network cable is cut, the server sends garbage data, the connection resets—`reader.ReadString` will return an error that is *not* `io.EOF`.

```go
if err != nil {
    // ...
    return fmt.Errorf("error reading SSE stream: %w", err) // EXIT
}
```

This is the alien bursting from John Hurt's chest in *Alien*. It's an unexpected, catastrophic failure. The loop is terminated instantly by a `return`, and an error is propagated up the call stack.

In summary, the `for {}` loop is not a runaway process. It's a vigilant listener with a multi-layered exit strategy, prepared for everything from a polite goodbye to a sudden, violent termination.
