---
title: "Custom Pipeline vs Frameworks"
date: 2026-07-09
lastmod: 2026-08-20
draft: false
---

This document answers a recurring, legitimate question: *"LangChain, LangGraph, and a
dozen agent frameworks already exist and are built by brilliant engineers. Why did we
hand-roll `tools/toolcore/{planner,pipeline,executor}` over years instead of adopting
one of them? Wouldn't a framework be simpler to maintain, especially for whoever inherits
this codebase?"*

It is a fair question and it deserves an honest answer, not a defensive one. This is not
a document that pretends frameworks are bad. Eino, Genkit, and LangGraph are genuinely
good software written by genuinely talented people. The conclusion here is narrower and
sharper than "frameworks bad, custom good":

> **The one thing our engine does — take a DAG that an LLM emits at runtime, repair it,
> resolve its data dependencies, and execute it with map/fan-out and direct streaming —
> is not something any Go framework gives you off the shelf. You would hand-roll the
> planner and the repair/resolution layer no matter which framework you adopted. So the
> "custom vs framework" choice is really "own a small execution substrate too, or bolt
> our unavoidable custom layer onto someone else's churning pre-1.0 API." For a
> production Go service that already works, owning it wins.**

Everything below is grounded in current source (`file:line`) and in a web-research pass on
the 2025–2026 state of Go orchestration frameworks. Where a claim comes from outside the
repo, it is cited.

---

## 1. What Our System Actually Is (Name the Pattern First)

You cannot evaluate a replacement until you can name what you built. Ours is the
**plan-and-execute / LLMCompiler pattern**: a single LLM call emits a full execution
graph as JSON up front, and a deterministic engine executes it. It is *not* a ReAct loop
(call tool → observe → let the LLM pick the next tool). We plan the whole DAG once, then
run it. That distinction is the whole game, and it is why generic "agent" frameworks —
most of which are ReAct or conversational-handoff machines — are the wrong shape.

Three subsystems, three jobs:

### 1a. `planner` — the LLM emits a plan, then we *repair* it (≈2,173 LOC, non-test)

`ClassifyAndPlan` (`tools/toolcore/planner/planner.go:202`) makes one LLM call using the
embedded prompt `tools/tooltypes/prompts/classify_and_plan_v1.txt`. The model returns JSON
declaring `mode` = `simple` / `pipeline` / `fixed_answer`. **The interesting part is
everything that happens *after* the model returns**, because an LLM's JSON is never
trustworthy enough to execute directly. We run a deterministic repair-and-validate gauntlet:

- `schema/enforce.go:EnforceCodeListSchema` and `schema/transform.go:transformCodeToCodes`
  — normalize the LLM's inconsistent `code` vs `codes` argument shapes.
- `validation/first.go:ValidatePipelineModeFirstStep` — enforce the IRON RULE that step_1
  of a pipeline must be a stock-code generator, and `convertToAggregationMode` when it isn't.
- `dependency/detect.go:HasStockCodeGenerator` + `dependency/remove.go:RemoveTool` — the iron
  rule in `postprocess.go`: strip `compare_stocks` from a plan that has no stock-code generator
  to feed it, converting the emptied step to an aggregation step. (A sibling rule that demoted
  "independent" pipelines to simple mode for parallelism was deleted on 2026-08-20, `P1-PL-A014`:
  it was unreachable, and `execution.BuildDependencyGraph` already runs in-degree-0 steps in the
  same level, so the flattening bought nothing.)
- `dependency/compare_stocks.go:EnforceCompareStocksWithMapStep` — guarantee `compare_stocks`
  is only ever wired to a real map step.
- `correction/parallel.go:EnforceEnableParallelMap` and
  `correction/transform.go:EnforceTransformAndDirectStreamRules` — fix map-parallelism and
  direct-stream flags the model set wrong.

This layer is pure Tuntun domain logic. It encodes *our* tools, *our* financial rules,
*our* prompt's failure modes. **No framework on earth ships this.** It is irreducibly ours.

### 1b. `pipeline` — the DAG engine (≈8,261 LOC, non-test)

`dag.go:BuildDependencyGraph` reads `from_step` / `field_path` references out of step
arguments (`extractArgumentDependencies`, `extractContextDependencies`) and builds a real
dependency graph. `execution/` runs steps by mode (`single.go`, `parallel.go`, `map.go`,
`modes.go`), and the crown jewel is the data-passing resolver in `ctx/`:

- `ctx/resolver.go:ResolveFieldPath` — JSONPath over step outputs (`output.result[0].stock_codes`, `output[*]`).
- `ctx/resolver.go:resolveTemplateString` — `{{code}}` template substitution per map iteration.
- `ctx/resolver.go:transformFormatAsCodeExplanation` — the `format_as_code_explanation`
  transform that feeds `compare_stocks`, including multi-sector context tagging.
- `ctx/manager.go` — typed accessors (`GetStockCodes`, `GetStockRankMap`, `GetSectorName`)
  that carry semantic meaning a generic string-blob context could not.

### 1c. `executor` — the thin façade (≈358 LOC, non-test)

`executor.go:ExecuteFromPlan` → `routeByExecutionMode` → `plan.ToPipelinePlan()`
(`executor.go:110`). The single most important architectural decision in the whole
subsystem lives here: **simple mode is not a separate path. It is converted into a
one-step pipeline and flows through the exact same engine.** One execution path, not two.

Keep these three numbers in mind, because they decide the entire argument:

| Subsystem | Non-test LOC | Nature | Could a framework replace it? |
|---|---:|---|---|
| `planner` | 2,173 | Domain repair/validation of LLM JSON | **No** — pure Tuntun logic |
| `pipeline` | 8,261 | DAG build + execution + JSONPath/template/transform resolver | Partially — the *mechanics*, not the domain wiring |
| `executor` | 358 | Façade unifying simple→pipeline | Trivially — but it's 358 lines |
| _tests_ | 7,320 | Proof it works | You'd rewrite these against the framework |

The part a framework could plausibly replace is a *slice* of the 8,261-LOC pipeline —
the generic "run a typed node graph with fan-out and stream merging" mechanics. The
2,173-LOC planner and the domain-aware resolver stay ours regardless. We would be trading
away the best-tested, most-stable, least-churning code we own to import a dependency, and
keeping every part that actually changes month to month.

---

## 2. The Central Finding: No Go Framework Does This Out of the Box

The web research pass was explicit and unanimous on the one question that matters:

> **Is there any Go framework that natively implements "LLM emits a DAG plan → engine
> executes it with dependency resolution + map/fan-out + JSONPath data-passing"?**
>
> **No.** Across Eino, Genkit-Go, trpc-agent-go, LangChainGo, and the swarm/wrapper
> libraries, the DAG is *always author-defined in Go code at compile time* — not emitted
> by the LLM at runtime and executed by a generic engine. Even in Python, LangGraph's
> LLMCompiler is a **tutorial pattern you assemble yourself**, not a turnkey engine.

This is the load-bearing fact. Every framework gives you `graph.AddNode()` /
`graph.AddEdge()` — *you*, the programmer, draw the graph at compile time. Our entire
premise is the opposite: **the LLM draws the graph at request time**, and a generic engine
executes whatever valid shape comes back. That runtime-planned-DAG capability — the thing
`classify_and_plan_v1.txt` + `planner` + `dag.go` deliver together — is exactly the piece
that does not exist off the shelf in Go.

So the honest framing is not "custom engine vs. free engine." It is: **"custom engine, or
(custom planner + custom repair + custom JSONPath wiring) bolted onto a framework's node
runtime."** In the second world you still write the hard 2,173 lines *and* you inherit a
third party's release cadence, abstractions, and breaking changes. That trade is bad.

---

## 3. The 2025–2026 Go Framework Landscape (Honest Scorecard)

Balanced verdicts — these are good projects; they just don't fit our pattern.

| Framework | Backing | Maturity | Orchestration model | Verdict for us |
|---|---|---|---|---|
| **Eino** (cloudwego) | ByteDance | ~12.2k★, v0.9.x, pre-1.0, ~210 releases | Chain/Graph/Workflow, **compile-time** DAG, best-in-class streaming | Closest Go analogue. Still code-defined graph. We'd keep the planner. Pre-1.0 → will break. |
| **trpc-agent-go** | Tencent | New (2025), stars unverified | GraphAgent "≈ LangGraph for Go", Chain/Parallel/Cycle/Graph, MCP/A2A, OTel | Most feature-complete Go harness. Youngest. Graph still code-defined. |
| **Genkit-Go** | Google | **1.0 GA (Sep 2025)** — the one with a stability guarantee | Code-defined imperative **flows** + tool calling, great Dev UI/observability | No runtime DAG planning. Strong for observability, not our engine. |
| **LangChainGo** | Community (≈1 maintainer) | ~9.5k★, v0.1.x, pre-1.0 | LLM clients + chains + ReAct agents; no graph engine | **Already our dependency** — as an LLM client only. Not orchestration. |
| swarmgo / go-llms / agency | Individuals | Small/experimental | Handoffs or thin LLM wrappers | Not a fit. No planning/dependency layer. |
| mcp-go / official Go MCP SDK | Community / Google | v1.x | Tool transport protocol | Relevant only if we go MCP-native for tools. Not orchestration. |
| Temporal / Restate / Inngest | Vendors | Production-mature | Durable execution substrate | Sits *under* our engine (crash-recovery/replay), never replaces it. |

Two things jump out:

1. **We already made the smart framework call.** `go.mod` pins
   `github.com/tmc/langchaingo v0.1.13`. We use it for exactly the right thing — a
   multi-provider LLM client and `llms.Tool` schema — and nothing more. We took the part
   of a framework worth taking (the client) and refused the part that would own us (the
   orchestration). That is not "not-invented-here syndrome"; it is a deliberate, correct
   seam.

2. **Every Go orchestration option except Genkit-Go is pre-1.0.** Eino (v0.9.x, ~210
   releases) and LangChainGo (v0.1.x) *will* break under you. Adopting them means trading
   our controlled internal API — one we can refactor on our own schedule — for someone
   else's churning one. More on churn in §6.

### Deep dive: Eino, the strongest contender — and why "closest" still isn't "adopt"

Eino is legitimately excellent. Its self-description ("The ultimate LLM/AI application
development framework in Go") is earned in one area especially: **streaming**. It
"automatically handles streaming throughout orchestration: concatenating, boxing, merging,
and copying streams" — which is the genuinely hard part of streaming a DAG, and a place
where our own code has bled (see `docs/architectures/prestream_deadlock.md`). Its design
philosophy even matches ours: *"orchestration should be a clear layer above business logic
— do not blend business logic into orchestration."*

And yet: Eino's graph is `graph.AddXXXNode()` / `graph.AddEdge()` defined **in Go at
compile time**. There is no "LLM emits JSON, engine runs it." To use Eino we would build
our planner on top (still 2,173 lines), translate the LLM's JSON plan into Eino graph
construction calls at runtime, re-express our JSONPath resolver in Eino's typed
field-mapping, rewrite 7,320 lines of tests against Eino's abstractions, and pin our
production financial service to a pre-1.0 ByteDance dependency releasing every few days.
The prize for all that work is: we delete a slice of `pipeline/execution/` and inherit
Eino's stream engine. That is a real benefit — Eino's streaming is better than ours — but
it is not remotely worth the migration cost or the loss of control for a system that ships
today. If we were greenfield in Go *right now* with no existing engine, Eino (or
trpc-agent-go) would be the first thing to evaluate. We are not greenfield. We have a
Batmobile that runs.

---

## 4. The Python Question: Why LangGraph Is a Hard No

LangGraph is the reference implementation of *our exact pattern*. Its LLMCompiler tutorial
is literally "a Planner that streams a DAG of tasks, a Task Fetching Unit that schedules
and executes tasks as soon as they are executable, and a Joiner" — the closest public
description of what our `planner` + `dag.go` do. It reached 1.0 in October 2025 with real
enterprise adoption. If we were choosing a language-agnostic design to *study*, LangGraph
is the syllabus.

But adopting it means **coming back to Python**, and that door was welded shut for reasons
this company paid for in full. See `docs/python_stuff/python_vs_go.md` — the entire
motivation for burning the original Python chatbot to the ground and rebuilding in Go. The
core argument there is not stylistic; it is about surviving concurrent load:

> "Python is crippled by the Global Interpreter Lock (GIL). This means **only one thread
> can execute Python bytecode at a time**, regardless of the number of CPU cores. For any
> CPU-bound work (prompt formatting, token counting, JSON manipulation), the 'concurrent'
> workers were effectively standing in a single-file line."
> — `docs/python_stuff/python_vs_go.md`

Our workload is *precisely* concurrent, CPU-touching, fan-out-heavy work: parse an LLM's
plan, repair its JSON, resolve JSONPath across steps, run a map step that fires N tool
calls in parallel, merge N streams. `python_vs_go.md` documents that we rebuilt this in Go
specifically to get true parallelism (goroutines across all cores), static typing that
catches plan-wiring errors at compile time, first-class `context` cancellation, real
circuit breakers (`gobreaker`), and a janitor that reaps stuck requests. Adopting LangGraph
would drag the single most concurrency-sensitive subsystem in the product back under the
GIL — undoing the exact migration `python_vs_go.md` calls "the price of admission to
building a professional, resilient service." That document ends with: *"The Python code was
a script. This Go ecosystem is an industrial-grade weapon."* Re-hosting our orchestration
core in Python to get a framework would be handing back the weapon and picking up the
script. It is a non-starter, and not because Python is bad — because *our* history with
Python under concurrent load is documented and settled.

The research confirms the structural point too: for "a low-latency, high-concurrency
financial chatbot with direct streaming, Go's concurrency and type story is the stronger
production foundation," at the cost of a smaller ecosystem and thinner observability
tooling — a cost we already mitigate with our own zerolog→Loki→Grafana pipeline
(`python_vs_go.md` §6).

---

## 5. What A Framework Would Actually Save — And Why It's Not Enough

Be precise about the upside, or the argument is dishonest. A framework (say Eino) would let
us delete roughly:

- Part of `pipeline/execution/` — the generic step-runner and parallel/map plumbing.
- Our hand-rolled stream merging (Eino's is better).
- Some of the `executor` façade (all 358 lines of it).

A framework would **not** touch:

- `planner` (2,173 LOC) — the LLM-JSON repair gauntlet. Ours forever.
- The domain resolver in `ctx/` — JSONPath, `{{code}}` templates,
  `format_as_code_explanation`, sector tagging, `GetStockRankMap`. Ours forever.
- Every tool implementation, `compare_stocks` direct streaming, cancellation, queue,
  cache fast-lane, circuit breakers. Ours forever.
- 7,320 lines of tests — you rewrite them against the framework's API, net-negative.

So the maximal prize is "delete a well-tested slice of the most stable subsystem, inherit a
better stream engine, and take on a pre-1.0 dependency." Weigh that against a multi-month
rewrite of the core request path with real regression risk across financial tools. The ROI
is negative. This is Joel Spolsky's "never rewrite working code" instinct with numbers
attached.

---

## 6. Framework Churn: The Maintenance Argument Cuts the Other Way

The strongest *pro-framework* intuition is "it'll be easier to maintain." The evidence says
the opposite for this class of framework.

- **LangChain/LangGraph are the cautionary tale.** Per the research: "LangChain went through
  major API restructurings across v0.1, v0.2, and v0.3 from 2023 through 2024, and for many
  teams the migration cost to reach v1.0 is comparable to just rewriting to raw SDKs."
  Abstractions are "powerful but leaky" with concrete footguns (chaining `.bind(tools=...)`
  then `.with_structured_output(...)` silently dropping tools). Even *post*-1.0, a breaking
  `langgraph-prebuilt==1.0.2` shipped without version constraints (Issue #6363, Oct 2025).
- **The Go options are pre-1.0 too.** Eino (~210 releases, v0.9.x) and LangChainGo (v0.1.x)
  will break under you. Only Genkit-Go (1.0 GA, Sep 2025) offers an explicit stability
  guarantee — and Genkit doesn't do our pattern.

"Easier for the next engineer to maintain" is not free with a framework. That engineer must
still learn our prompt, our tools, our domain repair rules — **and now also** the framework's
mental model, its leaky edges, and its breaking-change history. With the custom engine, the
churning API is *ours*: we refactor it on our schedule, and it never breaks unless we break it.

---

## 7. Industry Sentiment Backs "Own Your Orchestration"

This is not a lone-wolf position. The most-cited primary source is Anthropic's *Building
Effective Agents*:

> "We suggest that developers start by using LLM APIs directly: many patterns can be
> implemented in a few lines of code." Frameworks "often create extra layers of abstraction
> that can obscure the underlying prompts and responses, making them harder to debug… If you
> do use a framework, ensure you understand the underlying code."
> — Anthropic, *Building Effective Agents*

Octomind's widely-shared "Why we no longer use LangChain" (ran it in production 12+ months,
removed it when its inflexibility blocked lower-level control) and a broad wave of "raw SDK
migration" essays reinforce it. The structural driver: provider SDKs absorbed
function-calling, structured output, and tool orchestration by 2025, shrinking the problem
frameworks originally solved. A Go team already running a custom engine in production sits
squarely in the camp the primary sources endorse: **own your orchestration, lean on thin
libraries for the LLM client and observability.** Which is exactly what our `langchaingo`
usage already does.

---

## 8. What We *Should* Adopt (This Isn't Dogma)

Owning the engine does not mean rejecting everything external. Concretely:

1. **Keep `langchaingo` as the LLM client.** Correct seam, already in place. Don't reinvent
   provider abstractions.
2. **Steal Eino's streaming ideas, not its dependency.** Our stream handling has cost us
   (`prestream_deadlock.md`). Eino's "concatenate/box/merge/copy streams automatically" is
   worth reading and borrowing patterns from, in our own code.
3. **Consider MCP for tool transport** (official Go MCP SDK) *if and when* we want external
   tool interop — it's a protocol under our tools, orthogonal to the planner/engine.
4. **Consider a durable-execution layer (Temporal) only if** crash-recovery/replay across
   restarts becomes a hard requirement. It sits *beneath* our engine; it is not a
   replacement for it.

None of these touch the planner or the runtime-DAG execution model, because nothing
off-the-shelf does that job for us.

---

## 9. Conclusion

The question "is there a framework close to our pipeline that could replace it?" has a
precise answer: **conceptually yes (LangGraph's LLMCompiler), practically no.** No Go
framework executes an LLM-emitted DAG out of the box — you hand-roll the planner and the
domain resolver regardless — so a framework would replace only the most stable, best-tested
slice of our engine while leaving the hard 2,173-line domain layer entirely ours. The Python
option that *does* match our pattern is barred by the very concurrency history documented in
`python_vs_go.md`: we already burned that ship to escape the GIL, and re-hosting our most
concurrency-sensitive subsystem in Python would undo the migration that made this service
production-grade. Meanwhile the frameworks that would tempt us are pre-1.0 and churning,
while our own API is one we control.

The real risk this codebase faces was never "custom vs framework." It is **bus factor** —
the next engineer having to learn bespoke subsystems. The correct mitigation is this
document and its siblings in `docs/architectures/`: name the pattern (plan-and-execute /
LLMCompiler), map the three subsystems, and point every claim at a `file:line`. A new hire
who learns "this is LLMCompiler, implemented in Go for GIL-free concurrency" can map our
code to public literature in an afternoon — far cheaper, and far less risky, than betting a
working financial chatbot on a framework's release notes.

Leave the framework. Take the binary.

---

## Appendix: Sources

Repo (verified `file:line`): `tools/toolcore/planner/planner.go:202`;
`tools/toolcore/planner/{schema,validation,dependency,correction}/*.go`;
`tools/toolcore/executor/executor.go:68,96,110`;
`tools/toolcore/pipeline/execution/dag.go:17`;
`tools/toolcore/pipeline/ctx/{manager,resolver}.go`;
`tools/tooltypes/prompts/classify_and_plan_v1.txt`; `go.mod` (`langchaingo v0.1.13`,
`gobreaker v1.0.0`, `zerolog v1.33.0`, `go 1.25.7`). LOC via `wc -l` on non-test `.go` files.

Related internal docs: `docs/python_stuff/python_vs_go.md` (the Python→Go migration
rationale), `docs/architectures/jsonless.md` (compile-time-asset philosophy),
`docs/architectures/design_pattern.md`, `docs/architectures/prestream_deadlock.md`.

Web research (2025–2026 landscape), primary sources fetched:
- Eino — https://github.com/cloudwego/eino ; https://www.cloudwego.io/docs/eino/core_modules/chain_and_graph_orchestration/
- Genkit-Go 1.0 — https://developers.googleblog.com/en/announcing-genkit-go-10-and-enhanced-ai-assisted-development/
- LangChainGo — https://github.com/tmc/langchaingo
- Anthropic, *Building Effective Agents* — https://www.anthropic.com/engineering/building-effective-agents
- LangGraph 1.0 — https://www.langchain.com/blog/langchain-langgraph-1dot0 ; LLMCompiler tutorial (Planner→Task-Fetch→Joiner); Plan-and-Execute — https://www.langchain.com/blog/planning-agents
- LangGraph post-1.0 breaking change — https://github.com/langchain-ai/langgraph/issues/6363
- trpc-agent-go — https://github.com/trpc-group/trpc-agent-go
- Official Go MCP SDK — https://github.com/modelcontextprotocol/go-sdk ; mark3labs/mcp-go — https://github.com/mark3labs/mcp-go
- Durable execution — https://temporal.io/blog/of-course-you-can-build-dynamic-ai-agents-with-temporal

Caveats (per research): exact star counts for trpc-agent-go and the swarm projects were not
independently verified; Genkit's repo star figure is multi-language, not Go-specific; the
Octomind "Why we no longer use LangChain" quotes are relayed from search snippets, not a
direct page fetch.
