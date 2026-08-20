---
title: "Pre-stream Deadlock"
date: 2025-07-31
lastmod: 2026-07-09
draft: false
---

This document explains how the system handles the race condition between stream connection requests and cancellation without deadlocks.

> 📌 **Must-read companion:** [Why We Built Our Own Pipeline Instead of Adopting an Off-the-Shelf Agent Framework](../custom_pipeline_vs_frameworks/) — the streaming complexity described here is one place a framework (e.g. Eino) has genuinely better ergonomics; that doc weighs it honestly against the cost of adopting one.

## 1. The Race Condition

The system faces a timing challenge:

1. **Submit**: Client POSTs to `/chat/submit` - request queued
2. **Connect**: Client immediately GETs `/chat/stream/{request_id}` - handler waits for stream
3. **Process**: Worker picks up request and begins processing
4. **Cancel**: User POSTs `/chat/cancel/{request_id}` at any moment

The critical race: cancellation (4) can occur after connection (2) but before processing produces a stream (3).

**Potential Deadlock**: Handler waits for a stream channel that will never arrive because processing was cancelled.

## 2. Current Solution: Immediate Error Return

The public entry point `Manager.GetRequestResultStream()` (`chatbot/main_handlers.go:23`) is a thin logging wrapper that delegates to the private `getRequestResultStream()` (`chatbot/manager.go:954`). The private method avoids deadlock by returning errors immediately whenever the request is cancelled, instead of blocking on a channel that will never deliver.

### Code Flow (`chatbot/manager.go:954`)

```go
// getRequestResultStream retrieves the result stream for a request.
func (m *Manager) getRequestResultStream(ctx context.Context, requestID string) (<-chan types.StreamEvent, error) {
    logger := log.With().Str(internal.LogFieldRequestID, requestID).Logger()
    m.requestsLock.RLock()
    streamHolder, ok := m.activeRequests[requestID]

    // A status-only placeholder (nil ClientConnected / nil Stream) inserted by
    // ResumeRequest is NOT a live streamable holder - treat it like "not found".
    isStatusPlaceholder := ok && (streamHolder.ClientConnected == nil || streamHolder.Stream == nil)

    if !ok || isStatusPlaceholder {
        m.requestsLock.RUnlock()

        // Mid-processing resume: if a bowl still exists, serve a resume pipe.
        if m.config.UseBowl && m.bowlManager != nil {
            if bowl := m.bowlManager.GetBowl(requestID); bowl != nil {
                resumePipe, err := m.bowlManager.CreateResumePipe(requestID)
                if err == nil {
                    return resumePipe, nil
                }
            }
        }

        // Resume scenario: consult the database for terminal status.
        requestLog, err := m.arangoStore.GetRequestLog(ctx, requestID)
        if err == nil && requestLog != nil {
            // CRITICAL: Prevent resume of cancelled requests.
            if requestLog.CompletionStatus == types.StatusCancelled {
                m.CleanupRequest(requestID, logger, false)
                return nil, fmt.Errorf("request %s was cancelled and cannot be resumed", requestID)
            }
        }

        // Not active - try to replay a completed request from the database.
        return m.newCompletedRequestStream(ctx, requestID, logger)
    }

    // Check state while still holding the lock.
    isCancelled := streamHolder.State == types.StateCancelled
    m.requestsLock.RUnlock()

    if isCancelled {
        m.CleanupRequest(requestID, logger, false)
        return nil, fmt.Errorf("request %s was cancelled", requestID)
    }

    // ... signal client connected, then wait on streamHolder.Stream / .Err / timeout / ctx ...
}
```

### Cancellation Error Paths

Three distinct paths return a cancellation error (all fail fast, none blocks indefinitely). A fourth path handles the plain "not found" case.

#### Path 1: Pre-Connection Cancellation (active holder already cancelled)
Request was cancelled while its holder is still in `activeRequests`.

1. The holder is found in `activeRequests`.
2. `isCancelled := streamHolder.State == types.StateCancelled` is read under the lock (`chatbot/manager.go:1004`).
3. **Returns error immediately**: `"request %s was cancelled"` (`chatbot/manager.go:1009`).
4. Handler maps it to 404 `REQUEST_CANCELLED` (`internal/handlers/stream.go:50-52`).

#### Path 2: Resume Attempt on Cancelled Request (database guard)
Client attempts to resume a request no longer in `activeRequests`.

1. Not in `activeRequests` (or a status-only placeholder), so the database is queried (`chatbot/manager.go:989`).
2. `requestLog.CompletionStatus == types.StatusCancelled` is true (`chatbot/manager.go:992`).
3. **Returns error immediately**: `"request %s was cancelled and cannot be resumed"` (`chatbot/manager.go:995`).
4. Handler maps it to 404 `REQUEST_CANCELLED` (`internal/handlers/stream.go:50-52`).

#### Path 3: Cancellation During the Wait (error channel)
The client is already connected and waiting on `streamHolder.Stream`, and processing is cancelled mid-flight.

1. The `select` receives on `streamHolder.Err` (`chatbot/manager.go:1081`).
2. The error matches `errors.ErrRequestCancelled` (`chatbot/manager.go:1082`).
3. **Returns error immediately**: `"request %s was cancelled"` (`chatbot/manager.go:1084`).
4. Handler maps it to 404 `REQUEST_CANCELLED`.

#### Path 4: Not Found (non-cancellation)
Request exists in neither `activeRequests` nor the completed-request store.

1. Falls through to `newCompletedRequestStream()` (`chatbot/manager.go:1097`).
2. The completed lookup returns nil (`chatbot/manager.go:1108`).
3. **Returns error**: `"request %s not found"` (`chatbot/manager.go:1110`).
4. Handler maps it to 404 `NOT_FOUND` (`internal/handlers/stream.go:47-49`).

## 3. Handler Error Handling (`internal/handlers/stream.go:37`)

`StreamHandler.HandleStreamRequest` calls `GetRequestResultStream` and maps its error to an HTTP response before ever entering the streaming loop:

```go
func (h *StreamHandler) HandleStreamRequest(c *gin.Context) {
    requestID := c.Param("request_id")
    streamChan, err := h.app.GetChatManager().GetRequestResultStream(c.Request.Context(), requestID)
    if err != nil {
        logCtx := log.With().Str("request_id", requestID).Logger()
        if err == context.Canceled {
            // Client went away before the stream was established - nothing to report.
            return
        }
        switch {
        case errors.IsErrorType(err, errors.ErrNotFound) || errors.IsErrorMessage(err, "not found"):
            c.JSON(http.StatusNotFound, response.ErrorResponse(404, "NOT_FOUND",
                fmt.Sprintf("no stream data found for request %s", requestID), nil))
        case errors.IsErrorType(err, errors.ErrRequestCancelled) || errors.IsErrorMessage(err, "was cancelled"):
            c.JSON(http.StatusNotFound, response.ErrorResponse(404, "REQUEST_CANCELLED",
                fmt.Sprintf("request %s was cancelled and cannot be resumed", requestID), nil))
        case errors.IsErrorType(err, errors.ErrRequestTimeout) || errors.IsErrorMessage(err, "timed out"):
            c.JSON(http.StatusRequestTimeout, response.ErrorResponse(408, "REQUEST_TIMEOUT", err.Error(), nil))
        default:
            c.JSON(http.StatusInternalServerError, response.ErrorResponse(500, "INTERNAL_ERROR",
                "An internal error occurred", nil))
        }
        return
    }

    // Only reached on success: set SSE headers and stream events to the client.
    // ...
}
```

Note the matcher is dual: it checks both the typed error (`errors.IsErrorType`) and the error message (`errors.IsErrorMessage`), so both typed cancellation errors and the string-formatted ones from `getRequestResultStream` land on the same 404 `REQUEST_CANCELLED` branch.

## 4. Why No Deadlock

**Key Design Principle**: `getRequestResultStream()` performs **synchronous state checks** before any blocking operation.

1. **Lock-Protected State Check**: Acquires `requestsLock` and reads the cancelled state under the lock (`chatbot/manager.go:958-1005`).
2. **Immediate Error Return**: If cancelled, returns an error **before** waiting on any channel.
3. **No Blocking on Cancelled Requests**: The handler never enters the streaming loop for cancelled requests.
4. **Database Guard**: Even resume attempts are blocked when `CompletionStatus == StatusCancelled`.
5. **Bounded Wait Otherwise**: For live requests, the wait on `streamHolder.Stream` is bounded by `streamHolder.Err`, `m.config.ProcessingTimeout`, and `ctx.Done()` (`chatbot/manager.go:1024-1092`), so it can never block forever even without a cancellation.

**Contrast with Old Design**: earlier revisions described a `newCancelledStream()` helper that produced a synthetic "ghost stream" channel. That helper no longer exists. The current design uses **fail-fast error propagation** rather than delivering cancellation through a stream channel.

## 5. Cancellation State Persistence

Cancellation runs a single unconditional path in `Handler.CancelStream()` (`chatbot/cancellation/handler.go:53`). There is no longer any branching between "direct" and other delivery mechanisms.

### State Updates (`chatbot/cancellation/handler.go:53-104`)

```go
func (h *Handler) CancelStream(requestID string) error {
    logCtx := log.With().Str("request_id", requestID).Logger()

    streamHolder, ok := h.manager.GetActiveRequest(requestID)
    if !ok {
        return fmt.Errorf("no active request found for request_id %s", requestID)
    }

    // Idempotent: ignore a duplicate cancellation (state read under the manager lock).
    if h.manager.IsRequestCancelled(requestID) {
        return nil
    }

    // 1. Flip in-memory state to cancelled BEFORE stopping processing, so the
    //    state guard prevents the streaming goroutine from overwriting it with 'errored'.
    h.manager.UpdateRequestState(requestID, types.StateCancelled, "Request cancelled by user")

    // 2. Stop the processing context.
    if cancelFunc, ok := h.manager.GetCancellableStream(requestID); ok {
        cancelFunc()
    }

    // 3. Persist any partial bowl content to the database before deleting the bowl.
    bowlContent := h.bowlMgr.GetBowlContent(requestID)
    if bowlContent != "" {
        _ = h.manager.UpdateRequestFinalOutput(context.Background(), requestID, bowlContent)
    }

    // 4. Cancel the magic bowl - deletes the bowl and signals its active pipe.
    //    Bowl deletion means resume is no longer possible.
    h.bowlMgr.CancelBowl(requestID)

    // 5. Clean up the request, then purge it from activeRequests to enable resubmission.
    err := h.handleRequestCancellation(requestID, streamHolder, logCtx) // handler.go:108
    h.finalizeActiveRequestsPurge(requestID, logCtx)                     // handler.go:148
    return err
}
```

`handleRequestCancellation` (`chatbot/cancellation/handler.go:108`) calls `CleanupRequest`, and `finalizeActiveRequestsPurge` (`chatbot/cancellation/handler.go:148`) purges the entry from `activeRequests` via the `PurgeActiveRequest` interface.

### Multi-Layer Protection

The cancellation state is written across independent barriers:

- **Database** (`CompletionStatus == StatusCancelled`) - blocks resume attempts (Path 2).
- **In-Memory** (`streamHolder.State == StateCancelled`) - blocks new stream connections (Path 1).
- **Bowl System** (bowl deleted/cancelled via `bowlMgr.CancelBowl`, `chatbot/cancellation/handler.go:97`) - stops event accumulation and removes resume capability.

Any subsequent `getRequestResultStream()` call hits at least one of these barriers and returns an error immediately.

## 6. Test Validation

The integration test `TestStream_PreCancellation` (package `main`, `stream_test.go:52`, repo root) confirms the pre-connection behavior:

```go
func TestStream_PreCancellation(t *testing.T) {
    t.Parallel()

    userID := "user_prestream"
    requestType := "pre_stream"
    requestID := submitRequest(t, userID, "a question to be cancelled early", requestType)
    if requestID == "" {
        t.Skip("Request submission failed (likely queue full), skipping cancellation test")
        return
    }

    // Cancel before streaming.
    cancelRequest(t, requestID, http.StatusOK)

    // Attempt to stream the cancelled request.
    streamURL := fmt.Sprintf("%s/chat/stream/%s", testServer.URL, requestID)
    req, _ := http.NewRequest("GET", streamURL, nil)
    resp, err := http.DefaultClient.Do(req)
    assert.NoError(t, err, "Failed to connect to stream endpoint")
    defer func() { _ = resp.Body.Close() }()

    // Expect a 404 because the cancelled request was purged.
    assert.Equal(t, http.StatusNotFound, resp.StatusCode)

    // Verify the standard error envelope.
    body, _ := io.ReadAll(resp.Body)
    var standardResp struct {
        Status      int     `json:"status"`
        ErrorCode   *string `json:"errorCode"`
        Message     string  `json:"message"`
        TraceID     string  `json:"traceId"`
        PopUpRouter *string `json:"popUpRouter"`
        Data        any     `json:"data"`
    }
    _ = json.Unmarshal(body, &standardResp)
    assert.Equal(t, 404, standardResp.Status)
    assert.NotNil(t, standardResp.ErrorCode)
    assert.Equal(t, "REQUEST_CANCELLED", *standardResp.ErrorCode)
    assert.Contains(t, standardResp.Message, "was cancelled and cannot be resumed")
}
```

The key assertions (`stream_test.go:96-99`) verify the 404 status, the `REQUEST_CANCELLED` error code, and the `"was cancelled and cannot be resumed"` message.

## 7. Summary

The pre-stream deadlock is prevented through:

1. **Synchronous state checks** in `getRequestResultStream()` before any blocking.
2. **Immediate error returns** when a cancelled state is detected.
3. **Multi-layer cancellation state persistence** (database + memory + bowl).
4. **Handler error mapping** to appropriate HTTP status codes and error codes.
5. **No ghost streams** - errors propagate directly, with no synthetic channels.

This fail-fast approach eliminates the possibility of handlers waiting indefinitely on cancelled requests.
</content>
</invoke>
