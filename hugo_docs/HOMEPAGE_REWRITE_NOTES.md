# Homepage Rewrite — Session Notes (2026-07-25)

Ground-truth notes from the full rewrite of `layouts/page/custom-home.html`, produced by
auditing the Go implementation at `~/agentic_golang` on branch **`feat/T-230035-2-phase1`**.

**Purpose of this file:** the *Documentation & Deep Dives* pages under `content/docs/` were
NOT touched in this session. They still describe the retired architecture. This file records
what is true now, what was deleted and why, so the docs pass can be done without re-auditing.

---

## 1. The single most important correction

The **leader/follower broadcast subsystem is gone.** It is not deprecated, not disabled —
deleted.

**Why it was removed** (from `docs/token_maxxing/2026-07-09-leader-follower-deadcode-sweep.md`
and the removal commits): its premise was that many users fire *identical* queries at the same
instant, so one "leader" could compute a result and "followers" could subscribe to a broadcast.
That premise did not hold in production. The near-simultaneous duplicate case was **already**
covered by the cache fast-lane, so the broadcast machinery was pure complexity — races,
dual semaphores, intelligent dispatch — for no benefit. It was deleted rather than maintained.

**The architecture today is:**

```
FIFO queue  +  single processingSemaphore  +  cache fast-lane  +  bowl (resume)
                                            +  plan-and-execute pipeline
                                            +  dual-agent execution
```

**`bowl` is NOT the replacement for broadcast.** This is the most common misreading. Bowl
solves a completely different problem: **HTTP disconnect resilience**. One `ResponseBowl` per
`request_id`, events accumulate permanently, and there is **exactly one active pipe at a time**
(`CreatePipe` closes the previous one). Fan-out to multiple simultaneous clients is
structurally impossible. Replay survives a reconnect; broadcast does not exist.

### Removal commits (evidence trail)

| Commit | Date | What |
|---|---|---|
| `3df3c723` | 2025-10-22 | remove broadcast subsystem completely |
| `5868411f` | 2025-10-24 | remove singleflight + broadcast; dual semaphore → single `processingSemaphore`; intelligent dispatch → FIFO |
| `2812a15b` | 2025-10-29 | completes transition to simplified cache fast-lane |
| `f476677c` | 2026-06-18 | remove unused `MAX_CONCURRENT_LEADERS` / `MAX_CONCURRENT_SUBSCRIBERS` |
| `b297f8a1` | 2026-07-08 | remove write-only remnants ("not coming back") |
| `ad644bc9` + 7 others | 2026-07-09 | full code + docs sweep |

A repo-wide grep for `StreamBroadcaster`, `singleflight`, `leaderSemaphore`,
`followerSemaphore`, `PeekAndSelectRequest`, `UpdateStreamHolder`, `ClientEventChan` is
**clean in all `.go` files**.

---

## 2. Banned vocabulary for the docs pass

Never write, except as explicitly-labelled history: *leader, follower, subscriber, broadcast,
StreamBroadcaster, singleflight (as request dedup), MAX_CONCURRENT_LEADERS,
MAX_CONCURRENT_SUBSCRIBERS, "one stream many subscribers", "priority dispatch with follower
queue-jumping", thundering-herd-via-broadcast.*

One legitimate exception: the user-lifecycle cache uses a hand-rolled `sync.Map` **single-flight
refresh guard**. That deduplicates *refreshes of one cached value*, not user requests. If you
mention it, say so explicitly.

---

## 3. Docs pages that still contain dead architecture

These live under `content/docs/` and were **not** touched. Grep hits for
`broadcast|leader|follower|singleflight`:

| File | Likely action |
|---|---|
| `architectures/stream_broadcaster.md` | **DELETE** — entirely about removed machinery |
| `manager_insights/broadcast_pattern.md` | **DELETE** — same |
| `manager_insights/sauron.md` | **DELETE or heavy rewrite** — the single-flight/broadcast deep dive. The homepage previously linked here twice; those links are now removed. |
| `manager_insights/adapter_pattern.md` | Rewrite — check which adapters survive |
| `manager_insights/concurrent_and_parallel.md` | Rewrite — evergreen core, dead examples |
| `manager_insights/implicit_decoupling.md` | Rewrite |
| `manager_insights/solving_problems.md` | Rewrite |
| `architectures/design_pattern.md` | Rewrite — dead examples |
| `frequently_asked/optimization_qa_1.md` | Rewrite |
| `frequently_asked/semaphore_qa_1.md` | Rewrite — dual-semaphore model is gone |
| `narratives/fantastic_beasts.md`, `narratives/four_pigs.md` | Narrative/allegorical — rewrite or retire |
| `python_stuff/python_vs_go.md` | Check the incidental mention |

Note: the Go repo deleted its own `docs/manager_insights/` directory in the 2026-07-09 sweep.
The Hugo mirror of it is now orphaned.

Also independently wrong (found during the audit, not broadcast-related):
- `architectures/event_driven_janitor.md:15` cites `cleanupOldQueuedRequests`, which no longer exists.
- The old janitor description claimed **three** cleanup operations; only request cleanup remains.

---

## 4. What the homepage now says (section by section)

| Section | Status |
|---|---|
| Hero + `#architecture` | Rewritten. New 46-node mermaid diagram. |
| `#agents` | **NEW SECTION** — multi-agent routing + multimodal. |
| `#features` | Rewritten — 4 buckets, 27 popups. |
| `#tools` | Rewritten — all 30 registered tools. |
| `#api` | Rewritten — 36 endpoints + auth model + SSE events. |
| `#installation` / `#configuration` / `#usage` | Rewritten. |
| `#development` | Rewritten — real project tree. |
| `#documentation` | Untouched (deliberately). |

### Verified numbers now on the page
- Go **1.25.7**; gin 1.10.1, langchaingo 0.1.13, genai 1.42.0, arango-driver 1.6.6, go-redis/v9 9.11.0, gobreaker 1.0.0
- `MAX_CONCURRENT_REQUESTS` default **50** (not overridden in dev `.env`)
- `MAX_CONCURRENT_LLM_STREAMS` default **5** (dev `.env` = 30)
- `QUEUE_SIZE` default **100** (dev `.env` = 1000)
- `TOTAL_CACHE_WORKERS` **3**, `PRIORITY_WORKER_COUNT` **3**
- **30** registered tools (29 live; `mutual_fund_selection` disabled)
- **3** images per query, 20 MB each, jpeg/png/heic
- **182** test files
- ~199 config vars declared, ~152 set in `.env`

---

## 5. The two agents (for the docs pass)

Defined in `types/agents.go:16-19`. There are exactly two.

| Wire value | Shorthand | Behaviour |
|---|---|---|
| `tuntun_ai` | — | Professional analyst. **Token-streamed** over `/chat/stream/:request_id`. System prompt `core/prompts/v7.txt`, fixed 7-section framework. |
| `customer_service_manager` | `cs_manager` | Relationship follow-up. **One-shot**, not streamed. Delivered on its own SSE endpoint `/chat/cs_manager/answer/:request_id`. |

**Naming trap:** the wire value is `customer_service_manager`. `cs_manager` is only the
code/route/field shorthand. Do not use them interchangeably in prose.

Orthogonal to agents are three user-selected **personas** — Luna (default), Kevin, Mia —
six prompt files under `core/persona/prompts/`.

**Routing is server-owned.** There is no router model. `classify_and_plan` emits three
booleans (`need_professional_analysis`, `need_personalization`, `marketing_opportunity`); the
server owns the truth table `DeriveSelectedAgents` (`planner/routing.go:21-30`) and
**re-derives `selected_agents` unconditionally**. The prompt literally tells the model "You do
NOT decide which agent(s) respond." `EnforceRoutingRules` layers six steps: flag gate →
fixed_answer → missing-block default → marketing guard → reply_to override → re-derivation.

Tools execute **once** and feed both agents. The CS manager consumes tuntun_ai's output as
`{{AI Answer}}` and is instructed never to contradict it.

---

## 6. Multimodal (for the docs pass)

- Entry: `POST /v2/chat/submit`, multipart — a JSON `payload` part plus `image_file` parts.
- IDs: `img_` + 12 crypto-random hex. Kinds `image` / `voice` / `voice_stream` (`img_`/`vf_`/`sttvf_`).
- Validation on **sniffed bytes**, not the declared MIME or extension, with explicit HEIC
  ISO-BMFF brand detection. Empty allow-list **fails closed**.
- Blob store: `<root>/<kind>/<yyyy>/<mm>/<dd>/<id>.<ext>`, dirs 0700 / files 0600,
  temp-file + rename. `Persist` rolls the blob back if the metadata write fails.
  `PersistAsync` uses its own 30 s timeout because the HTTP 202 cancels the request context.
- Single injection point `requestcontext.WithImageAttachments`; single read gate
  `core.ImageAttachmentsFromContext`.
- **Five** multimodal call sites: planner, simple-mode streamer, `compare_stocks`,
  `web_search`, CS manager.
- **Two transports.** langchaingo reaches Gemini through an OpenAI-compatible client, so
  `llms.BinaryContent` does not serialise — only `llms.ImageURLContent` with a base64 `data:`
  URI works. `web_search` is on the native genai SDK and uses real `inline_data` parts.
- Cache: SHA-256 over length-prefixed, ordered blob **content** (not ids) → 16 hex chars
  appended as `:img_<fp>`. Image turns bypass the cache at three independent guard points.
- **Voice is scaffolding only.** Kinds and id prefixes exist; both voice kinds are hardcoded
  disabled, there is no registered audio validator and no STT. Do not imply voice ships.

---

## 7. Honesty caveats that must survive into the docs

These were deliberately written into the homepage. Do not quietly drop them.

1. **Circuit breakers are dormant.** Three exist (LLM, Redis, ArangoDB — `core/services.go:100-102`)
   but all use `minRequests = 1000`, so at normal traffic they effectively never trip. The old
   "Anti-Fragile Circuit Breakers" framing was dropped.
2. **No metrics pipeline.** No Prometheus, no `/metrics`, no pprof. Observability is logs-only:
   zerolog → Vector → Loki → Grafana.
3. **Status is polled, not pushed.** ~600 ms polling, and progress is per **pipeline step**,
   not per tool. The old page claimed 750 ms and per-tool checkmarks.
4. **Direct-Stream RAG is dormant.** `NATURAL_ANSWER_TOOLS` still exists but defaults to empty
   and is unset, so `frequently_asked` takes the normal blocking + synthesis path. Only
   `compare_stocks` direct-streams, intrinsically by name.
5. **Shutdown is not idempotent.** `Manager.Shutdown` does a bare `close(m.logQueue)` with no
   `sync.Once` (`chatbot/manager_core.go:378`); a second call panics. Only the drain behaviour
   is documented.
6. **CI `package_tests` is `allow_failure: true`** — a green pipeline does not mean green tests.

---

## 8. Dead config — never document

Verified zero references in any `.go` file:

`MAX_TOTAL_TOOL_OUTPUT_TOKENS`, `LONG_TEXT_TOOLS`, `TruncateToolOutputs` (the whole
tool-output truncation feature — the old page's "Targeted Token Truncation" is fiction now),
`ExecuteToolsInParallel`, `MAX_CONCURRENT_LEADERS`, `MAX_CONCURRENT_SUBSCRIBERS`,
`SUBMIT_TIMEOUT`, `TOOL_SELECTION_PROMPT_VERSION`, `HEALTH_PORT`, `BE_FAQ_RAG_URL`,
`COMPARE_STOCKS_MAX_HISTORY_ITEMS`.

Live replacement for input budgeting is `MAX_LLM_INPUT_TOKENS` — it caps LLM *input*, driving
fallback truncation, the aggregation guard and the summarisation target. It is not a per-tool
output cap.

### Renamed / removed tools
- `stock_valuation` — **removed** (`a9ce282e`, 2025-12-08), folded into `stock_analysis`.
- `analyze_stock` → `research_report` (`7736bf37`) → `stock_analysis_from_research` (`83e3349b`).
- Also gone: `get_sector_stock_codes`, `query_user_short_term_memory`.

### Renamed endpoints
- `POST /chat/update_reaction` → `POST /chat/reaction`
- `GET /chat/get_chat_history` → `GET /session/history` (or `/v2/session/history`)

---

## 9. Items worth raising separately (NOT for public docs)

Surfaced during the audit; deliberately kept off the public page.

1. `docker-compose.yml` hardcodes a real `DEEPSEEK_TENCENT_API_KEY` in plaintext, and
   `tuntun123` appears as an inline password across the compose files.
2. `PRODUCTION_MODE` defaults to **false**, which keeps a development credential accepted.
   The page states it must be `true` in deployed environments, without naming the credential.
3. `authz.EnforceOwnership` is a **no-op when `DYNAMIC_AUTH=false`** — every ownership check
   across the API disappears in static-auth deployments.
4. Four DataStore routes (`/concept_sector/repopulate` in particular, which triggers real
   external work) are unauthenticated. The page labels them "(Public)" and recommends
   ingress-layer restriction, without flagging them as exposed.
5. `CONSUL_ENABLED` is absent from `.env` (defaults false) while nearly every `BE_*` URL is
   `consul://`.

---

## 10. Where the audit material lives

Seven recon reports were produced (session scratchpad, not persisted to git):
`01-architecture`, `02-multiagent`, `03-multimodal`, `04-tools`, `05-api`,
`06-setup-config-test`, `07-features-structure` (~1030 lines, 60 verified features with
bucket assignments and old-feature verdicts).

If a future session needs them regenerated, the method was: read-only subagents, each
briefed to cite `file:line` and to report "could not verify" rather than infer.

### Gotcha: mermaid must not render before the webfonts load

Mermaid sizes every node by measuring its label. If it measures against the fallback font and
the real face (IBM Plex Mono) arrives afterwards, the text grows past the box it was given and
**the second line of every multi-line node is clipped**. It looks like a text-length problem
and is not — shortening labels only hides it.

The fix, in `static/diagram.html`, is to await `document.fonts.ready` plus an explicit
`document.fonts.load()` for each weight before calling `mermaid.render()`. Any new page that
renders mermaid must do the same. The overview page is fine because its popup diagrams render
on click, by which time the fonts are in.

Symptom to watch for: nodes whose label box is taller than the shape around it. A headless
check that catches it is to compare `label.getBoundingClientRect().height` against
`shape.getBoundingClientRect().height` — `scrollHeight` will *not* catch it, because the
foreignObject does not clip.

### Gotcha: cycles invert the whole dagre layout

Two feedback edges (`SSE → client` and the cache-promotion loop) made dagre rank the queue
first and put the entry points at the bottom, so the diagram read upwards. Removing the
`SSE → client` edge — the delivery direction is obvious without it — restored a clean
top-to-bottom flow and cut the canvas from 6971x2930 to 1682x2240. Keep at most one feedback
edge per diagram.

### Gotcha: Hugo eats `{{ ... }}`

`layouts/page/custom-home.html` is a **Hugo template**, so any literal `{{ ... }}` in prose is
parsed as a template action and fails the build:

```
ERROR parse of template failed: function "AI" not defined
```

This bit the prompt-composition popup, which documents the literal seam markers
`{{AI Answer}}`, `{{User Profile}}` and `{{User Short Term Memory}}`. Fix: write them as HTML
entities — `&#123;&#123;AI Answer&#125;&#125;`. They are injected via `innerHTML`, so the
browser decodes them back to `{{AI Answer}}` on screen.

Watch for this if the docs pass moves any prompt-template content into a **layout**. Markdown
under `content/` is not template-parsed, so it is safe there.

A reusable mermaid validator was built at `scratchpad/mval/valall.mjs` — it runs
`mermaid.parse()` from the real **mermaid 10.6.1** package under JSDOM against every
`<div class="mermaid">` block in the given files. Use the **full** `mermaid.parse()` API, not
the bare `flowDiagram-v2` parser: the latter does not strip `%%` comments and reports false
failures.
