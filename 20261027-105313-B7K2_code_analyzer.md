# Code Analysis: Home-page popup content (`showPopup` switch → Hugo data)

**Type:** Refactoring
**Date:** 2026-10-27 10:53:13
**Session ID:** 20261027-105313-B7K2
**Plan:** `POPUP_DATA_REFACTOR_PLAN.md` (3 phases)
**Worktree:** `/home/miftah/.worktrees/agentic/popup-data-refactor` — branch `feature/popup-data-refactor` (base `origin/main` @ `d963643`)

> Artifacts live at the **worktree root**, not `docs/analyzer/` + `docs/plans/`. `/docs/` is
> gitignored in this repo (anchored, `.gitignore:3`), so a fresh worktree has no `docs/` and the
> Step-4 table resolves to the root. This is the better outcome here: plans written under
> `docs/plans/` in this repo have historically died with the worktree, never surviving the merge.

---

## User Input

### Original User Request

```
popup-data-refactor refactor

Move the home page's popup content out of a JavaScript switch statement and into Hugo data, so
that the trigger buttons and the modal bodies are generated from ONE source and cannot drift.

MEASURED STATE (hugo_docs/layouts/page/custom-home.html, as of this commit — verify it yourself):
  - 3,011 lines total
  - `function showPopup(type)` at :1490, `function openDiagramTab(id)` at :2943 — so the switch is
    ~1,453 lines, 48% of the file
  - 50 unique `case` labels, 50 unique `showPopup('...')` triggers, and they pair 1:1
  - `hugo_docs/data/` already exists and is EMPTY — Hugo data files have a home already
  - `resources/_gen/` IS committed (so it is a real generated-but-tracked artifact in this repo)

WHY (the rationale, which is the specification for what may and may not change):

The problem is not length, it is KIND. The popups are prose stored as JavaScript template literals.
A stray backtick in an explanation breaks the whole switch. A literal ${ silently interpolates. No
HTML tooling sees any of it. And a popup-trigger whose string has no matching case renders an EMPTY
MODAL with no build error — a failure the page can ship.

R1 — Replace the switch with Hugo data files, and generate BOTH the feature-card trigger buttons
AND the modal bodies from that same data. Generating only the bodies is half the job: the whole
point is that trigger and content stop being two things that must be kept in agreement. After this,
a popup with no trigger, or a trigger with no popup, should be a BUILD-TIME failure or a structural
impossibility — not something a human or a checklist catches.

Design the data shape yourself (one file per popup under data/popups/, a single popups.yaml, or
page-bundle resources are all plausible). Argue for the one you pick. Constraints that should
inform it: the popups carry rich HTML (h2, p, code, strong, ul, hr); they are grouped into
feature-cards with headings and an icon each; and ordering within a card is meaningful and must be
preserved exactly.

R2 — Resolve a live bug this refactor surfaces. `case "dark-launch":` is declared TWICE, at :1754
and :2885. In a JS switch the second is unreachable, so only the first has ever rendered. THE TWO
BODIES ARE DIFFERENT:
  :1754 "Dark-Launch Flag Discipline" — narrow, about ENABLE_IMAGE_PROCESSING and the
        mechanically-proven off-path contract. This is what users see today.
  :2885 "Dark-Launch Feature Flags" — broader, covers ENABLE_IMAGE_PROCESSING, ENABLE_CS_MANAGER,
        ENABLE_USER_SHORT_TERM_MEMORY, USE_BOWL, DYNAMIC_AUTH, PRODUCTION_MODE, and the
        "gate at the edge, then prove the off-path is unchanged" framing. Dead since it was written.
Someone very likely edited the page believing it had shipped. Decide deliberately what the single
surviving popup says — keep one, or merge them — and RECORD the choice and its reasoning in the
plan's Decisions table. Do not silently drop either body. Per this command's own rules, decide it;
do not end the session holding a question about it.

R3 — The file has two eras of popup authoring and the indentation shows it: flat at roughly
:1324-1597, 8-space-indented from roughly :2055. The duplicate in R2 happened across that seam.
Normalising this is in scope precisely because the refactor deletes the region anyway.

NOT IN SCOPE, and this is a decision already made, not an open question:

Do NOT split the page markup into partials. The sections have no reuse and no parameters — a
one-call-site partial is an #include with extra steps, and it makes cross-cutting edits (nav link +
section + popup + catalog row) ten file-opens instead of one grep, which is worse for agents, not
better. The markup stays in custom-home.html. This refactor touches the popup content and the code
that renders it, nothing else.

Also out of scope: hugo_docs/content/docs/** (generated from the Go repo's docs/ via
/update-hugo-docs — never hand-edited here), hugo_docs/public/** (gitignored, CI-built), themes/,
resources/, and the ~/agentic_golang repo.

THE VERIFICATION PROPERTY — state it precisely in the plan, because a loose version of it is
useless. It is NOT "public/index.html is byte-identical": the trigger markup and the script block
both legitimately change shape. What must hold is:

  (a) For each of the 50 popup ids, the HTML that ends up inside #popup-content is
      CHARACTER-IDENTICAL to what the current switch produces for that id — with exactly one
      sanctioned exception, the dark-launch body R2 decides on.
  (b) The rendered feature-card trigger lists are byte-identical: same buttons, same labels, same
      order, same classes, same onclick behaviour.
  (c) `hugo` builds clean and every popup still opens and closes in a browser.

Build the (a) check as a SCRIPT, committed with the work — extract all 50 bodies from the
pre-refactor file, extract all 50 from the post-refactor render, diff them. A refactor of 1,453
lines of prose verified by eye is a refactor verified by nothing.

BUILD NOTES (measured, do not rediscover): use ~/bin/hugo — it is v0.164.0 extended.
/usr/bin/hugo is v0.123.7 and dies on the Stack theme. NEVER pass --gc: it deletes the committed
resources/_gen/.

ONE MORE REASON THIS MATTERS, for the plan's Why: this repo is about to be worked by concurrent
swarm phases. The swarm's ISOLATE verdict assumes "same file, disjoint regions merge cleanly" —
but every phase that adds a page section appends cases to this ONE switch, so their edit regions
are not disjoint, they are the same spot. One popup per data file turns those concurrent writes
into writes to DIFFERENT files, and the collision stops existing rather than needing a merge.
```

### User-Provided Context

Build notes (verified below): `~/bin/hugo` is v0.164.0 extended; `/usr/bin/hugo` is v0.123.7 and
dies on the Stack theme; never pass `--gc` because it deletes the committed `resources/_gen/`.

### User-Provided Files

None marked `@`. The named file is `hugo_docs/layouts/page/custom-home.html`.

### Requirement IDs

| ID | What the user asked for |
|---|---|
| R1 | Replace the `showPopup` switch with Hugo data files, and generate **both** the feature-card trigger buttons **and** the modal bodies from that one source, so a trigger without a body (or a body without a trigger) becomes a build-time failure or a structural impossibility. Design and justify the data shape. |
| R2 | Resolve the duplicate `case "dark-launch":` (`:1754` live, `:2885` dead). Decide deliberately what survives, record the choice and reasoning in the plan's Decisions table, and drop neither body silently. |
| R3 | Normalise the two indentation eras in the popup region (flat vs 8-space), in scope because the refactor deletes the region anyway. |

---

## Verification of the Measured State

Every number in the user's prompt was re-measured. All confirmed, with **three corrections**:

| Claim | Verdict | Measured |
|---|---|---|
| 3,011 lines total | ✅ | `wc -l` = 3011 |
| `showPopup` at :1490 | ✅ | `:1490` |
| `openDiagramTab` at :2943 | ✅ | `:2943` (`closePopup` at `:2927`) |
| switch ≈ 1,453 lines, 48% of file | ✅ | switch body `:1497`–`:2914`; case bodies `:1496`–`:2910` |
| `data/` exists and is empty | ✅ | `hugo_docs/data/` — 0 entries |
| `resources/_gen/` committed | ✅ | tracked; `.gitignore` covers only `/docs/`, `hugo_docs/public/`, `hugo_docs/scripts/.fontcache/` |
| **50 unique `case` labels** | ⚠️ correction | 50 unique, but **51 `case` statements** — `dark-launch` twice |
| **50 unique triggers** | ⚠️ correction | 50 unique, but **51 `showPopup(...)` call sites** — `dark-launch` twice |
| **"they pair 1:1"** | ⚠️ **correction** | True of the *sets*; **false of the occurrences**. See below. |
| dark-launch duplicated at :1754 / :2885 | ✅ | both confirmed, bodies differ as described |
| two indentation eras | ✅ but interleaved | not a single seam — see R3 section |

### The correction that reshapes R2

`dark-launch` is duplicated on **both** sides of the pairing, not just in the switch:

| | Line | Card | Button label |
|---|---|---|---|
| trigger A | `:388` | `agents` → Multimodal Processing | `Dark-Launch Flag Discipline` |
| trigger B | `:617` | `features` → System Observability | `Dark-Launch Feature Flags` |
| case A (live) | `:1754` | — | `<h2>Dark-Launch Flag Discipline</h2>` |
| case B (dead) | `:2885` | — | `<h2>Dark-Launch Feature Flags</h2>` |

Because the switch takes the first match, **both buttons open body A**. The System Observability
card's button says "Dark-Launch Feature Flags" and opens "Dark-Launch Flag Discipline" — a
user-visible mismatch, not merely dead code.

`git log -S` places **both bodies and both buttons in the same commit**, `5f32106`
*"docs(home): rewrite homepage against the current agentic architecture"* (2026-07-25). The author
wrote two deliberately different entries for two different cards in one sitting and collided the
id. It was never a stale edit layered on top of a shipped page. This is the evidence the R2
decision rests on (see the plan's Decisions table).

---

## Detailed Requirements Understanding

**Problem statement.** 1,453 lines (48%) of `custom-home.html` are English prose stored as
JavaScript template literals inside one `switch`. Three consequences follow, and they are about
*kind*, not length:

1. **Fragility with no compiler.** A raw backtick terminates the literal; a literal `${` silently
   interpolates. *(Measured: the region currently contains zero of each — the hazard is latent,
   not active. It contains exactly one escape, `"\\n"` at `:2842`, which is itself proof the layer
   exists and must be unwound on migration.)*
2. **No tooling.** No formatter, linter, or editor sees the HTML as HTML.
3. **Silent failure.** A trigger whose string matches no `case` falls to `default:` and renders
   *"Feature details not available."* — shippable, with no build error. The dark-launch collision
   is the live instance of the same class.

**What must change.** Popup prose moves to Hugo data. One source produces the trigger button and
the modal body, so they cannot disagree. Referential integrity becomes a build-time error.

**Success criteria.**
- `~/bin/hugo` builds clean, no `--gc`.
- Verification property (a): all 50 bodies character-identical after a stated normalisation (the
  plan's Invariant 1 defines it precisely), with exactly one sanctioned dark-launch exception.
- Verification property (b): trigger lists byte-identical — same buttons, labels, order, classes.
- Verification property (c): popups open and close in a browser.
- The (a) check is a committed, re-runnable script.
- An id referenced by a card but having no body (or vice versa) **fails the build**.

**Key considerations / assumptions.**
- **Normalisation vs character-identity.** R3 (normalise indentation) and property (a)
  (character-identical) are in direct tension: the bodies' internal indentation *is* the
  indentation R3 names. Resolved in the plan's Decisions table as common-prefix dedent applied
  identically to both sides of the diff, which preserves every content byte and all *relative*
  whitespace (so the two `<pre>` blocks are safe).
- **One escape to unwind.** `:2842` contains `"\\n"` inside a template literal, which evaluates to
  `\n` (backslash + n) in the rendered HTML. The data file must hold a *single* backslash. An
  extractor that copies source text verbatim will get this one body wrong.
- **`<script type="text/html">` is the right carrier.** Empirically verified below.
- The out-of-scope list is a decision already made, not an open question: no partials, no
  `content/docs/**`, no `public/**`, no `themes/`, no `resources/`, no `~/agentic_golang`.

---

## Analysis Scope

### Explicitly Mentioned Files
- `hugo_docs/layouts/page/custom-home.html` (3,011 lines) — the entire blast radius.

### Discovered Related Files
- `hugo_docs/data/` — empty; destination for the new data tree.
- `hugo_docs/scripts/` — `gen_og_image.py`, `sync_anchor_docs.py`. Establishes that
  `hugo_docs/scripts/` is where this repo keeps Python build/maintenance tooling.
- `.gitignore` — `/docs/` (anchored), `hugo_docs/public/`, `hugo_docs/scripts/.fontcache/`.
- `.github/workflows/deploy.yml` — the only workflow; builds and deploys on push to main.
- `hugo_docs/resources/_gen/` — committed; the reason `--gc` is forbidden.

### Confirmed absent
`grep -rn showPopup` across `layouts/`, `assets/`, `static/`, `content/` returns **nothing outside
`custom-home.html`**. No theme override, no external JS, no deep-link handler, no `content/docs/`
page references a popup id. The refactor's reference list is closed inside one file.

---

## Current Dataflow

### Entry Point: `showPopup(type)`

**Location:** `hugo_docs/layouts/page/custom-home.html:1490`
**Trigger:** inline `onclick="showPopup('<id>')"` on 51 `<button class="popup-trigger">` elements
(`:372`–`:617`).
**Input:** one string id.

```
onclick="showPopup('cache-fastlane')"
        │
        ▼
showPopup(type)                                    :1490
  lastTrigger = document.activeElement              ← focus restore target
  modal   = #popup-modal                            :1455
  content = #popup-content                          :1458
  switch (type) { … 51 cases … }                    :1497–:2914
      popupContent = `…HTML…`                       ← JS template literal
  default: "<h2>Feature Details</h2><p>Feature details not available.</p>"   :2911
  content.innerHTML = popupContent                  :2916  ← the join point
  modal.style.display = "block"
  if (content.querySelector(".mermaid")) setTimeout(() => mermaid.init(), 100)
```

**Exit:** `#popup-content.innerHTML` is replaced; modal shown; Mermaid re-initialised when the body
contains a `.mermaid` div (13 of the 50 bodies do).

**`content.innerHTML = popupContent` at `:2916` is the contract surface.** Verification property
(a) is exactly a statement about the string assigned here, per id. Any replacement that assigns the
same string per id satisfies (a) by construction.

### `closePopup()` — `:2927`

Hides the modal and returns focus to `lastTrigger`. Bound at `:1457` (close button), `:2981`
(backdrop click), `:2990` (Escape). **Untouched by this refactor** — it reads no popup content.

### Switch structure — uniform, which is what makes extraction mechanical

Every one of the 51 cases has the same five-line shape, with one era-dependent wrinkle:

```
<indent>case "<id>":
<indent+2>popupContent = `
<body lines…>
<close>`;
<brk>break;
```

where the **terminator indentation differs by era** — measured, and a parser that assumes one
shape silently drops 13 bodies:

| era | `case` | `popupContent` | `` `; `` | `break;` |
|---|---|---|---|---|
| era-0 (38 cases) | 0 | 2 | **0** | **0** |
| era-8 (13 cases) | 8 | 10 | **12** (`indent+4`) | **10** (`indent+2`) |

Counts (whole file): `case "…":` = 51 · `popupContent = \`` = 51 · `` `; `` = 51 · `break;` = 51.
A `perl -0777` regex over that shape recovers all 51 ids and `<h2>` titles cleanly — verified.

### Trigger markup — uniform

All 51 triggers are a single line of the identical shape:

```html
<li><button class="popup-trigger" type="button" onclick="showPopup('<id>')"><label></button></li>
```

Only the leading indentation varies (16 spaces or 6 spaces — see R3).

---

## Key Data Structures

### The card → popup map (the ordering R1 must preserve exactly)

10 cards across 3 sections. **Order within each card is the source order below.**

| § | Card heading | Icon | Popup ids, in order |
|---|---|---|---|
| `agents` | Multi-Agent System | `ic-architecture` | `agent-roster`, `server-owned-routing`, `classify-and-plan`, `ustm`, `evidence-based-memory`, `prompt-composition` |
| `agents` | Multimodal Processing | `ic-database` | `image-pipeline`, `file-assets`, `multimodal-transport`, `image-cache-fingerprint`, **`dark-launch`** |
| `screener` | The Lock | `ic-shield` | `screener-lock`, `screener-no-invented-numbers`, `screener-content-is-routing` |
| `screener` | Planning a Turn | `ic-sliders` | `screener-turn-modes`, `screener-lexicon`, `screener-relaxation` |
| `screener` | The Measured API | `ic-activity` | `screener-measured-api`, `screener-one-query-matrix`, `screener-display-vs-raw` |
| `screener` | Shape of the Tool | `ic-architecture` | `screener-import-dag`, `screener-payload-not-answer`, `screener-kill-switch`, `screener-not-built` |
| `features` | Performance &amp; Architecture | `ic-bolt` | `cache-fastlane`, `cache-promotion`, `plan-and-execute`, `parallel-map-execution`, `fifo-queue`, `stateful-conversation`, `data-driven-tools` |
| `features` | Resource Management | `ic-shield` | `bowl-resume`, `e2e-cancellation`, `janitors`, `stale-while-revalidate`, `consul-discovery`, `circuit-breakers`, `usage-limits` |
| `features` | Data Handling &amp; Integrity | `ic-database` | `context-aware-caching`, `summarisation-cache`, `citations`, `file-asset-integrity`, `automated-indexing`, `async-logging`, `structured-persistence` |
| `features` | System Observability | `ic-activity` | `structured-logging`, `observability-stack`, `status-tracking`, `alerting`, `prompt-versioning`, **`dark-launch`** |

**Note:** the card order in `Resource Management` is *not* the switch order — triggers run
`bowl-resume, e2e-cancellation, janitors, stale-while-revalidate, consul-discovery,
circuit-breakers, usage-limits` while the switch runs `bowl-resume, circuit-breakers,
consul-discovery, stale-while-revalidate, janitors, e2e-cancellation, usage-limits`. **Card order
is authoritative** — it is what renders. Any data shape must take its ordering from the trigger
lists, never from the switch.

### Trigger label ≠ popup `<h2>`

They differ for at least one popup and must stay separate fields:

| id | trigger label | body `<h2>` |
|---|---|---|
| `screener-content-is-routing` | `Content Is the Routing` | `Content Is the Routing; the Label Only Lies` |

The `<h2>` therefore stays **inside the body HTML verbatim**; the trigger label is its own field.
Reconstructing `<h2>` from a title field would break property (a) for this id.

### Content inventory of the 50 bodies

| Tag | Count | Notes |
|---|---|---|
| `<code>` | 656 | |
| `<p>` | 270 | |
| `<li>` | 251 | |
| `<strong>` | 199 | |
| `<br>` | 73 | |
| `<ul>` | 64 | |
| `<h2>` | 51 | one per body |
| `<hr>` | 50 | |
| `<em>` | 48 | |
| `<div class="mermaid">` | 13 | requires `mermaid.init()` after injection |
| `<pre><code>` | 2 | `:2212`, `:2725` — **whitespace-significant** |
| `<h3>` | 2 | `:2411`, `:2419` |
| `<sup>` | 1 | |

Hygiene across `:1496`–`:2910`: **0 tabs**, **0 trailing-whitespace lines**, 111 blank lines,
UTF-8 with em-dashes. **0 occurrences of `${`**, **0 unescaped or escaped backticks**, **0
`</script>`**, and exactly **1 backslash** (`:2842`).

---

## R3: the indentation eras are interleaved, not a single seam

The user described "flat at roughly :1324-1597, 8-space from roughly :2055". Measured, the two eras
**alternate four times**:

| Case range | Indent | Popups |
|---|---|---|
| `:1498`–`:2228` | 0 | `agent-roster` … `data-driven-tools` (31) |
| `:2271`–`:2486` | 8 | `bowl-resume` … `usage-limits` (7) |
| `:2505`–`:2699` | 0 | `context-aware-caching` … `structured-persistence` (7) |
| `:2718`–`:2885` | 8 | `structured-logging` … `dark-launch` (6) |

The same split shows in the **trigger markup**: cards at `:369`/`:381`/`:527`–`:554`/`:597` are
10-space indented; cards at `:573`/`:585`/`:609` sit at column 0. The dark-launch collision spans
the boundary (`:388` 16-space / `:617` 6-space; `:1754` flat / `:2885` 8-space), which is how two
people — or one person in two passes of one commit — missed it.

Both eras disappear: the data files carry dedented bodies, and the template emits a single uniform
indentation.

---

## Empirical finding: how Hugo must carry the HTML

The central design risk — whether Go's context-aware `html/template` mangles raw HTML emitted into
a `<script>` element — was **tested**, not assumed. A throwaway Hugo v0.164.0 site with a data file
containing a backtick, a `${x}`, a double quote, a backslash escape and `&amp;`/`&lt;` entities:

| Template expression | Result |
|---|---|
| `<script type="text/html">{{ .body \| safeHTML }}</script>` | **verbatim** — backtick, `${x}`, `"`, `\n`, `&amp;`, `&lt;` all survive untouched |
| `<script type="text/html">{{ .body }}</script>` | fully entity-escaped (`&lt;h2&gt;`) — unusable |
| `var P = {{ … \| jsonify \| safeJS }}` | works, but re-encodes as `<h2>` and puts prose back inside JS |

**Conclusion.** `type="text/html"` is a non-JS script type, so Go's escaper leaves the content
alone; `safeHTML` is required. Raw prose lands in the document as text, `textContent` returns it
byte-exact (script elements are raw-text — entities are *not* decoded), and there is no escaping
layer to get wrong. This is the same idiom the page already uses for Mermaid sources:
`<script type="text/plain" class="diagram-code">` at `:171`, `:290`, `:420`.

The one hazard is a body containing `</script>`; there are zero today, and the plan makes it a
build-time assertion.

---

## Dependencies

**Build:** `~/bin/hugo` v0.164.0+extended (`/usr/bin/hugo` is v0.123.7 and dies on the Stack
theme). Never `--gc` — it deletes the committed `hugo_docs/resources/_gen/`.
**Runtime:** Mermaid (already loaded) for the 13 diagram-bearing bodies.
**Config:** none. No env vars, no external services, no DB.
**CI:** `.github/workflows/deploy.yml` builds and deploys on push to main.

---

## Reference List

Every site that touches the thing being changed.

| Symbol / key | File:line | Kind | Phase |
|---|---|---|---|
| `showPopup(type)` definition | `custom-home.html:1490` | def | 3 |
| `switch (type) { … }` | `custom-home.html:1497`–`:2914` | def | 3 |
| 51 × `case "<id>":` + body | `custom-home.html:1498`–`:2909` | def | 2 (extract) → 3 (delete) |
| `default:` empty-modal fallback | `custom-home.html:2911`–`:2913` | def | 3 |
| `content.innerHTML = popupContent` | `custom-home.html:2916` | def | 3 |
| Mermaid re-init after injection | `custom-home.html:2919`–`:2924` | def | 3 |
| 51 × `onclick="showPopup('<id>')"` | `custom-home.html:372`–`:617` | call | 3 |
| 10 × `<div class="feature-card">` + `<h4>` + icon | `custom-home.html:369`–`:620` | call | 3 |
| 3 × `<div class="feature-grid">` | `custom-home.html:368`, `:526`, `:572` | call | 3 |
| `#popup-modal` / `#popup-content` | `custom-home.html:1455`, `:1458` | def | — unchanged |
| `closePopup()` + its 3 bindings | `custom-home.html:2927`, `:1457`, `:2981`, `:2990` | def | — unchanged |
| `openDiagramTab(id)` + `DIAGRAM_VIEWER` | `custom-home.html:2943`, `:2941` | def | — unchanged |
| `<script type="text/plain" class="diagram-code">` | `custom-home.html:171`, `:290`, `:420` | ref | — precedent only |
| `hugo_docs/data/` (empty) | — | config | 2 (populated) |
| `hugo_docs/scripts/` | `gen_og_image.py`, `sync_anchor_docs.py` | ref | 1 (new siblings) |
| `hugo_docs/resources/_gen/` | committed | config | — must survive (no `--gc`) |
| `.github/workflows/deploy.yml` | — | config | — unchanged |

**No references exist outside `custom-home.html`.** Verified by `grep -rn showPopup` over
`layouts/`, `assets/`, `static/`, `content/`.

---

## Impact Points (files that WILL need changes)

1. **`hugo_docs/layouts/page/custom-home.html`** — the only existing file edited. Delete
   `:1497`–`:2914` (the switch and its `default:`); replace `:372`–`:617` trigger `<li>`s and
   `:369`–`:620` card wrappers with generated markup; emit 50 body `<script type="text/html">`
   blocks; rewrite `showPopup` as a lookup. *Phase 3.*
2. **`hugo_docs/data/popups/<id>.yaml`** × 50 — new; `card`, `order`, `label`, `body`. *Phase 2.*
3. **`hugo_docs/data/popup_cards/<card>.yaml`** × 10 — new; `section`, `heading`, `icon`, `order`.
   *Phase 2.*
4. **`hugo_docs/scripts/popups_extract.py`** — new; parses the switch and trigger lists off a
   given revision of the page, JS-unescapes, dedents, writes the data tree + baseline. *Phase 1.*
5. **`hugo_docs/scripts/popups_verify.py`** — new; the committed property-(a)/(b) check: diffs the
   rendered page against the baseline. *Phase 1.*
6. **`hugo_docs/scripts/popups_baseline.json`** — new; the frozen pre-refactor snapshot of all 51
   bodies and all 51 triggers. The thing the verifier diffs against, forever. *Phase 1.*

**This document describes. The plan files prescribe.**
