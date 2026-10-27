# Plan: Home-page popups — from a JavaScript switch to Hugo data

**Slug:** `popup-data-refactor`
**Date:** 2026-10-27 10:53:13
**Analysis:** `20261027-105313-B7K2_code_analyzer.md`
**Worktree:** `/home/miftah/.worktrees/agentic/popup-data-refactor`
**Branch:** `feature/popup-data-refactor` (base: `origin/main` @ `d963643`)
**Phases:** 3
**Status:** phase 1/3 complete
**Coordinator:** —

> Artifacts sit at the worktree root, not under `docs/`. `/docs/` is gitignored in this repo, so a
> fresh worktree has none and the `/analyze` Step-4 table resolves to the root — which also means
> these two files survive the merge instead of dying with the worktree.

---

## Why

*The user's rationale, verbatim. This is the specification for what may and may not change.*

> Move the home page's popup content out of a JavaScript switch statement and into Hugo data, so
> that the trigger buttons and the modal bodies are generated from ONE source and cannot drift.
>
> The problem is not length, it is KIND. The popups are prose stored as JavaScript template
> literals. A stray backtick in an explanation breaks the whole switch. A literal `${` silently
> interpolates. No HTML tooling sees any of it. And a popup-trigger whose string has no matching
> case renders an EMPTY MODAL with no build error — a failure the page can ship.
>
> ONE MORE REASON THIS MATTERS: this repo is about to be worked by concurrent swarm phases. The
> swarm's ISOLATE verdict assumes "same file, disjoint regions merge cleanly" — but every phase
> that adds a page section appends cases to this ONE switch, so their edit regions are not
> disjoint, they are the same spot. One popup per data file turns those concurrent writes into
> writes to DIFFERENT files, and the collision stops existing rather than needing a merge.

---

## Requirements

| ID | What the user asked for | Phases |
|---|---|---|
| R1 | Replace the `showPopup` switch with Hugo data files, generating **both** trigger buttons and modal bodies from one source; a trigger without a body (or a body without a trigger) must become a build-time failure or a structural impossibility. Design and justify the data shape. | 1, 2, 3 |
| R2 | Resolve the duplicate `case "dark-launch":` (`:1754` live, `:2885` dead). Decide deliberately, record the choice and reasoning here, drop neither body silently. | 2 |
| R3 | Normalise the two indentation eras in the popup region (flat vs 8-space). | 2, 3 |

---

## The chosen data shape, and the argument for it

**Two sibling data trees, one file per thing.**

```
hugo_docs/data/popup_cards/<card-id>.yaml     # 10 files
    section: agents | screener | features
    heading: "Multimodal Processing"          # exact <h4> inner text, entities as-authored
    icon:    ic-database                      # <use href="#…">
    order:   20                               # position of the card within its section

hugo_docs/data/popups/<popup-id>.yaml         # 51 files — filename IS the popup id
    card:  multimodal-processing              # must name a popup_cards file
    order: 50                                 # position within that card
    label: "Dark-Launch Flag Discipline"      # exact trigger button text
    body: |2                                  # dedented raw HTML, <h2> included verbatim
      <h2>…</h2>
```

> **Count:** 50 popup ids exist today; decision D1 resurrects the dead `:2885` body as a
> 51st (`feature-flags`), so the data tree is **51 popups + 10 cards = 61 files**. Where
> this plan says "all 50 ids" it means the 50 that render today — the ones invariant I1
> pins against the pre-refactor switch. `feature-flags` has no pre-refactor rendered
> counterpart; it is checked against the dead case body in the baseline instead.

**Why one file per popup, and not a single `popups.yaml`:**

1. **It is the requirement.** The user's swarm argument is explicit: concurrent phases that each
   add a page section currently append to one `switch`, so their edit regions are the same spot.
   One file per popup makes those concurrent writes land in *different files* and the collision
   stops existing. A single `popups.yaml` would merely relocate the collision into YAML.
2. **It makes drift structurally impossible, not merely checkable.** One file carries *both* the
   `label` (which becomes the button) and the `body` (which becomes the modal). The template
   emits both from the same iteration. A trigger with no body cannot be written down.
3. **Card membership lives in the popup, not in a card manifest.** A manifest listing ids per card
   would be a second shared file every new section must append to — reintroducing the collision at
   one remove. With `card:` + `order:` inside each popup file, adding a popup to an existing card
   is *exactly one new file and zero edits to any shared data file*.
4. **Ordering is explicit and stable.** Hugo iterates maps in key order, which is alphabetical and
   therefore wrong; sorting by `(order, id)` is deterministic and reproduces the current order
   exactly. Orders are assigned in tens (10, 20, 30 …) so an insertion needs no renumbering —
   and so two concurrent phases are unlikely to collide on a number, with the `id` tie-break
   making even a collision deterministic rather than arbitrary.
5. **Rich HTML is carried literally.** A YAML literal block scalar (`|2`) holds `h2/p/code/strong/
   ul/hr/pre/div.mermaid` with no escaping whatsoever — no backtick hazard, no `${`, no entity
   mangling. Editors syntax-highlight it; the `<pre>` blocks keep their internal whitespace.

> **Why `|2` and not a bare `|`.** Measured in phase 2: `norm()` leaves 15 of the 51 bodies
> with residual leading indentation, because each contains a block already at column 0 in the
> source (the 13 mermaid sources and the 2 `<pre><code>` blocks), so their longest common
> non-blank prefix is empty. A plain `body: |` whose first content line begins with a space
> is a YAML error or, worse, a silent misparse. The generator therefore always emits an
> explicit indentation indicator — never a bare `|`, never a case-by-case choice.

**Why not page-bundle resources:** `custom-home.html` is a layout, not a page bundle; routing
content through `content/` would collide with the out-of-scope rule on `content/docs/**` and give
every popup a frontmatter header it does not need.

### How the HTML reaches the browser

Measured, not assumed (see the analysis's *Empirical finding*):

```go-html-template
{{ range $p := sort $all "id" }}    <script type="text/html" class="popup-body" data-popup-id="{{ $p.id }}">{{ $p.body | safeHTML }}</script>
{{ end }}
```

`$all` is the one slice phase 3 builds from `hugo.Data.popups` at the top of the template, **the
same slice the three feature grids iterate**. Emitting both sites from one slice is what makes the
trigger ⇔ body correspondence visible in the template rather than argued about.

`type="text/html"` is a non-JS script type, so Go's context-aware escaper leaves the content
alone and `safeHTML` emits it verbatim — a backtick, a `${x}`, a quote, a backslash and
`&amp;`/`&lt;` entities all survive byte-for-byte in Hugo v0.164.0. Script elements are raw-text,
so `textContent` returns exactly those bytes with entities *undecoded*. `showPopup` becomes a
`querySelector` plus `content.innerHTML = el.textContent`, which makes property (a) true **by
construction** rather than by care. The page already uses this idiom for Mermaid sources
(`<script type="text/plain" class="diagram-code">`, `:171`/`:290`/`:420`).


> **Use `hugo.Data`, never `.Site.Data`.** Measured on this exact binary: `.Site.Data` was
> deprecated in Hugo v0.156.0 and v0.164.0 logs
> `WARN deprecated: .Site.Data ... Use hugo.Data instead`. The site currently builds with no
> such warning, so `.Site.Data` would violate invariant I3. All three phases use `hugo.Data`.

### How referential integrity becomes a build-time failure (R1)

Four guards in the template, each an `errorf` that **fails `hugo`**:

| Guard | Fires when |
|---|---|
| G1 — unknown card | a popup's `card:` names no `popup_cards/<id>.yaml` — no grid iterates it, so its carrier would have no trigger |
| G2 — orphan card | a `popup_cards` entry has zero popups pointing at it — an empty `<ul>` ships |
| G3 — order collision | two popups in the same card share an `order` — both render, in an order nobody chose |
| G4 — unknown section | a card's `section:` is not one of `agents`/`screener`/`features` — the card renders nowhere while its popups still emit carriers |

Plus the presence/non-empty assertions: a card's `heading`, `icon` and `order`; a popup's `order`,
`label` and `body`; and a `body` containing `</script>` (which would terminate its own carrier
element). A trigger with no body is not caught by a guard because it **cannot be expressed** — one
file emits both. **G1 and G4 are the two halves of the mirror case, a body with no trigger**; with
structural impossibility on the other side, the trigger ⇔ body correspondence is total. (G4 was
added by phase 3 after the draft; it closes R1's other half rather than widening scope.)

`order` is asserted for **presence** (`isset`), never for type: Hugo decodes a positive YAML integer
as `uint64`, so a `"%T" == "int"` assertion fires on all 61 files. The sort key runs the value
through `int`, which normalises `uint64`, `int` and a quoted `"20"` alike and itself fails the build
on a non-numeric value. No script in phases 1 or 2 makes an `int`-type assumption about `order`
either — phase 1 never sees the field, and phase 2 compares PyYAML-decoded Python ints to its own.

---

## Scope

**In scope**
- `hugo_docs/layouts/page/custom-home.html` — delete `:1497`–`:2914`, regenerate trigger markup at
  `:369`–`:620`, emit body blocks, rewrite `showPopup` as a lookup.
- `hugo_docs/data/popups/` (51 new) and `hugo_docs/data/popup_cards/` (10 new).
- `hugo_docs/scripts/popups_extract.py`, `popups_verify.py`, `popups_baseline.json` (new, phase 1).
- `hugo_docs/scripts/popups_emit.py` (new, phase 2 — the YAML-emitting half, a sibling module so
  that phase 1's file has exactly one owner). It imports `norm` and the four decision-D1 constants
  from `popups_extract` and declares none of its own.

**Out of scope** — decisions already made, not open questions
- **No partials.** The sections have no reuse and no parameters; the markup stays in
  `custom-home.html`. This refactor touches popup content and the code that renders it, nothing else.
- `hugo_docs/content/docs/**` (generated from the Go repo via `/update-hugo-docs`).
- `hugo_docs/public/**` (gitignored, CI-built), `themes/`, `resources/`, `~/agentic_golang`.
- `closePopup()`, `openDiagramTab()`, `DIAGRAM_VIEWER`, `#popup-modal`/`#popup-content` markup,
  the Mermaid re-init block, and all non-popup page sections.

---

## Invariants

Rules every phase must hold.

**I1 — The verification property (a), stated precisely.**
For each popup id, let `B_before(id)` be the string assigned to `#popup-content.innerHTML` by the
pre-refactor switch, and `B_after(id)` the string assigned by the post-refactor page. Define

```
norm(s) = s with (1) CRLF→LF,
              (2) every fully-blank line emptied,
              (3) the longest common leading-whitespace prefix of all non-blank lines removed,
              (4) leading and trailing blank lines stripped,
              (5) one trailing newline enforced.
```

Then **`norm(B_after(id)) == norm(B_before(id))` byte-for-byte, for all 50 ids**, with exactly one
sanctioned exception (Decision D1). `norm` is applied identically to both sides by the same
function in `popups_verify.py`. It removes only *uniform* leading indentation, so every content
byte — every word, tag, entity, inline space — and all *relative* indentation inside the two
`<pre><code>` blocks is preserved. This is the strictest property simultaneously satisfiable with
R3; see Decision D2.

**I2 — The verification property (b).** The rendered feature-card region must be byte-identical
to the pre-refactor render after normalising leading indentation per line **and disregarding blank
lines between cards** (Decision D6): same `<div class="feature-grid">`/`<div class="feature-card">`/
`<h4>`+icon structure, same buttons with the same `class`, `type`, `onclick` and label text, in the
same order, in the same cards, in the same sections. The one sanctioned change is the `onclick` id
on the System Observability dark-launch button (Decision D1). `popups_verify.py` checks this
mechanically, and does so *structurally* — it parses the rendered cards into records and diffs
reconstructed `<li>` lines, so neither leading indentation nor an inter-card blank line can reach
the comparison. That is precisely the latitude R3 needs.

**I3 — The build is clean, every phase.** `~/bin/hugo` (v0.164.0 extended) exits 0 with no
`ERROR`/`WARN` newly introduced. **Never pass `--gc`** — it deletes the committed
`hugo_docs/resources/_gen/`. `/usr/bin/hugo` is v0.123.7 and dies on the Stack theme; do not use it.

**I4 — Every phase leaves the site shippable.** Phases 1 and 2 add files only; the page keeps
rendering from the switch until phase 3 swaps it.

**I5 — No prose is edited.** Bodies and labels move; their words do not change. The sole content
decision is D1.

**I6 — Nothing outside the Scope list is touched.** In particular no partial is created, and
`content/docs/**`, `public/**`, `themes/`, `resources/` are not modified.

---

## Phases

| # | Title | Satisfies | Package | Files | Depends on | Difficulty | Plan | TaskID | Card |
|---|-------|-----------|---------|-------|-----------|------------|------|--------|------|
| 1 | [x] Extraction & verification tooling | R1 | `hugo_docs/scripts` | 3 | — | NORMAL | `.workflows/plan/popup-data-refactor/phase-1.md` | P2-HS-A001 | — |
| 2 | Generate the popup data tree | R1, R2, R3 | `hugo_docs/data` | 62 | 1 | NORMAL | `.workflows/plan/popup-data-refactor/phase-2.md` | P2-HD-A001 | — |
| 3 | Rewire the template, delete the switch | R1, R3 | `hugo_docs/layouts` | 1 | 2 | HARD | `.workflows/plan/popup-data-refactor/phase-3.md` | P2-HL-A002 | — |

**File counts, spelled out.** Phase 1: 3 new files, all under `hugo_docs/scripts/`. Phase 2: **62**
= 61 data files (51 `popups/*.yaml` + 10 `popup_cards/*.yaml`) **plus one new script**,
`hugo_docs/scripts/popups_emit.py`. Phase 3: 1 — `custom-home.html`, modified. No file is written by
two phases.

Strictly sequential — `1 → 2 → 3`. No phase pair is independent: 2 consumes the extractor 1 writes,
3 consumes the data 2 writes and is gated by the verifier 1 writes. The orchestrator will run three
waves of one.

### Phase 1 — Extraction & verification tooling
**Satisfies:** R1
**Owns:** `hugo_docs/scripts/popups_extract.py`, `hugo_docs/scripts/popups_verify.py`,
`hugo_docs/scripts/popups_baseline.json`.
**Does not touch:** `custom-home.html`, `hugo_docs/data/`, `hugo_docs/scripts/popups_emit.py`
(phase 2's file — named in `popups_extract.py`'s docstring, never imported, so phase 1 stands alone
with phase 2 absent).
**Key work:** parse the 51 cases and 51 trigger call sites out of `custom-home.html` at
`origin/main`; **unwind JS template-literal escapes** (the lone `"\\n"` at `:2842` must become one
backslash — an extractor that copies source text verbatim gets this body wrong); apply `norm` from
I1; freeze all 51 bodies + all 51 triggers into `popups_baseline.json` — each card with its
`section`, `heading` and `icon`, and its triggers **in trigger order**, which is the order that
renders and is where phase 2 derives every `order:` from. Write `popups_verify.py`, which builds
with `~/bin/hugo`, extracts bodies from `<script type="text/html" data-popup-id>` blocks and
triggers from the rendered cards, applies the same `norm`, and diffs against the baseline —
reporting per-id pass/fail and a unified diff on mismatch, exit non-zero on any.
**Interface contract it publishes (phases 2 and 3 must honour):** the body-carrier markup
`<script type="text/html" class="popup-body" data-popup-id="<id>">`, the trigger markup
`<li><button class="popup-trigger" type="button" onclick="showPopup('<id>')">LABEL</button></li>`,
the single `norm()` the whole set compares through, and the five decision-D1 constants
(`SPLIT_ID`, `SPLIT_NEW_ID`, `SPLIT_CARD`, `SPLIT_CARD_HEADING`, `SPLIT_OCCURRENCE`) — declared
here once and **imported** by phase 2's emitter, never re-declared.
**It also owns the blank-line question (D6):** the verifier parses the rendered cards into records
and diffs reconstructed `<li>` lines, so blank lines between cards are invisible to it by
construction. Phase 3 may therefore emit one uniform convention.
**Exit criteria:** `popups_extract.py` run against the current page emits 51 bodies and 51
triggers; `popups_baseline.json` is committed and contains all of them; `popups_verify.py` runs
end-to-end against the *current* (pre-refactor) build and reports all 51 ids as `MISSING` — proving
the render-side extractor runs and that the check is not yet vacuously green. Tree builds clean.

### Phase 2 — Generate the popup data tree
**Satisfies:** R1, R2, R3
**Owns:** `hugo_docs/data/popups/*.yaml` (51), `hugo_docs/data/popup_cards/*.yaml` (10), the new
`hugo_docs/scripts/popups_emit.py`, and the dark-launch split (D1).
**Does not touch:** `custom-home.html`; **`popups_extract.py` — not one byte** (it is phase 1's
file; this phase imports from it and never edits it); `popups_verify.py`; `popups_baseline.json`.
**Key work:** generate the data tree from the baseline with `popups_emit.py emit`; apply D1 (the
`dark-launch` / `feature-flags` split), taking the dead occurrence by phase 1's `SPLIT_OCCURRENCE`
rather than a local literal; confirm every body round-trips — `norm(yaml_body) ==
norm(baseline_body)` for all 50 unchanged ids *and* for `feature-flags`, asserted by
`popups_emit.py check`, not by eye. Every `body:` is emitted as a `|2` block scalar with an explicit
indentation indicator. R3 is realised here as **one uniform carrier shape** — identical header,
identical block-scalar indent, the same `norm` applied to every body regardless of era — not as one
uniform column: 15 bodies legitimately keep a residual 4- or 16-space indent because they contain a
block already at column 0, and flattening those further would break I1.
**Exit criteria:** 61 data files exist (51 popups + 10 cards) plus `popups_emit.py`; the round-trip
assertion passes for all 51 ids; the resurrected `feature-flags` body matches the dead `:2885` case
after `norm`; `~/bin/hugo` builds clean (the data is present but not yet consumed); the rendered
page is **unchanged** — still driven by the switch, and the whole output tree is byte-identical to
the pre-phase build (I4).

### Phase 3 — Rewire the template, delete the switch
**Satisfies:** R1, R3
**Owns:** `hugo_docs/layouts/page/custom-home.html` only.
**Does not touch:** data files, scripts, the baseline, any other page section, `closePopup`,
`openDiagramTab`, the modal markup, the Mermaid re-init block. **Creates no partial.**
**Key work:** replace the three `feature-grid` blocks (`:368`, `:526`, `:572`) with a generated
loop over `hugo.Data.popup_cards` filtered by section and sorted by `order`, each card looping its
popups sorted by `(order, id)` via a single `printf "%012d|%s"` sort key; emit the 51 body
`<script type="text/html">` blocks from the **same** `$all` slice the grids iterate; add guards
**G1–G4** plus the `</script>` and presence assertions as build-failing `errorf`; delete
`:1497`–`:2914` (the switch and its `default:`); rewrite `showPopup` to look up the carrier by
`data-popup-id` and assign `textContent` to `innerHTML`, keeping the `lastTrigger` capture and the
Mermaid re-init verbatim, and replacing the `default:` empty-modal fallback with a `console.error`
that refuses to open. R3 completes: the two indentation eras are gone with the region, and the
inter-card blank line becomes uniform across all three grids (D6).
**Exit criteria:** `popups_verify.py` exits 0 — property (a) reports `PASS 51` (the 50 ids that
render today, plus `feature-flags` checked against the dead `:2885` body) and property (b) reports
all 10 cards PASS; `~/bin/hugo` builds clean with no `--gc` and `hugo_docs/resources/` is untouched;
`grep -c 'case "' custom-home.html` is 0 and the file is ~1,400 lines shorter (3,011 → ~1,604);
each of G1, G2, G3, G4 and the content assertions **fails the build** when violated — demonstrated
and recorded, and the build returns to exit 0 on restore; manual browser check confirms property
(c): popups open, close three ways, restore focus, and the 13 Mermaid bodies render their diagrams.

---

## Reconciliation Log

The three phase planners ran in parallel. Phase 2 was written first; phases 1 and 3 had phase 2's
plan as input, but phase 3 did not have phase 1's. Every row below was resolved **by editing the
plan files**, not by noting it here.

| Conflict | Phases | Resolution |
|---|---|---|
| **File collision.** Phase 2's Step 5 appended ≤6 lines to `popups_extract.py` — phase 1's file — conditional on phase 1 reserving an emit seam. | 1 ↔ 2 | **Struck.** Phase 1's CLI names no seam (`--page/--rev/--out/--check/--self-test/--report` and nothing else), so the condition is false permanently and must not be left for a 3am session to evaluate. Phase 2's Step 5 is now a struck notice quoting phase 1's answer; the conditional row is gone from its Files table, and the `git checkout -- popups_extract.py` line is gone from its Rollback. One owner per file (rule 3). |
| **Duplicate definition.** Phase 1 exports `SPLIT_ID`/`SPLIT_NEW_ID`/`SPLIT_CARD`/`SPLIT_CARD_HEADING`/`SPLIT_OCCURRENCE`; phase 2's `popups_emit.py` re-declared three of them locally and hard-coded `nth = 1` for the fourth. Values identical today. | 1 ↔ 2 | **Collapsed to phase 1's copy.** `popups_emit.py` now does `from popups_extract import SPLIT_CARD, SPLIT_ID, SPLIT_NEW_ID, SPLIT_OCCURRENCE, norm` (it already imported `norm` from there) and `nth = SPLIT_OCCURRENCE`. Phase 1's §2(ii) and its Handoffs now record the names as a real published interface rather than an optional tidy-up. Two copies of the constant that decides which body `feature-flags` gets is the exact drift this refactor exists to delete. |
| **Unmet assumption (claimed).** Phase 2's `_pick` "tolerant adapter" was flagged for alignment with phase 1's real baseline schema. | 1 ↔ 2 | **Verified a no-op, left in place.** Every key phase 2 tries *first* is exactly the key phase 1 emits: `occurrences`/`id`/`body`/`line` and `cards`/`section`/`heading`/`icon`/`triggers`/`id`/`label`. Phase 1's extra keys (`close_line`, `indent`, `line` on cards and triggers) are ignored harmlessly. Phase 2's assumption A5 now records the verification; the adapter stays as a loud failure mode for a future re-shaped baseline. |
| **Contract drift / unowned behaviour.** Phase 3 adds 3 blank lines to the `features` grid (one uniform inter-card convention, R3) and asked phase 1 to "confirm the verifier ignores the inter-card blank line, or strip blank lines in `norm` on the trigger side". Each plan assumed the other handled it. Invariant I2 was at stake. | 1 ↔ 3 | **Decided: phase 1 owns it, and it is already blind to blank lines — by construction, not tolerance.** `extract_cards` is a line classifier (a blank line matches none of its six patterns and is never recorded) and `compare_cards` diffs `<li>` strings it *reconstructs* from the parsed model, so whitespace between records cannot reach the diff; `norm()` touches bodies only. Phase 1's Interface Contract §3 now states this as an owned guarantee; phase 3's flagged block is rewritten as resolved; I2's wording now says "and disregarding blank lines between cards". Recorded as **Decision D6**. Verified against the source: `:573`/`:585`/`:597`/`:609` are contiguous, so the 3 added lines are real — and outside what is compared. |
| **Gap in the index.** The guards table listed G1–G3; phase 3 builds a fourth, G4 (unknown section) — a card whose `section` is not one of the three renders nowhere while its popups still emit carriers. | 3 → index | **G4 added to the index's R1 table** with its one-line description, plus the note that G1 and G4 are the two halves of "a body with no trigger". Not scope creep: it closes the other half of the correspondence R1 demands. Phase 2's handoff now says G1–G4 and records that `integrity()` needs no G4 analogue — `load_baseline()` already validates `section` against `SECTIONS` before a file is written. |
| **Cross-phase type assumption (`order`).** Phase 3 found Hugo decodes positive YAML ints as `uint64`, so an `int` type assertion fires on all 61 files; it uses `isset` + `int` instead. Could phase 1 or 2 independently assume `int`? | 1, 2, 3 | **Checked: no.** Phase 1 never sees `order` (the baseline carries trigger *position*; phase 2 derives `order` from it). Phase 2 compares PyYAML-decoded Python ints to its own plan records and never inspects a type name. Nothing to align. Recorded in phase 2's Interface Contract and in the index's guards section so nobody re-adds a type check. |
| **Gap in the index's Scope.** `popups_emit.py` — a new seventh file — was in no Scope list (the analysis's Impact Points attribute "writes the data tree" to `popups_extract.py`, which the plans split in two). | 2 → index | **Added to In scope**, attributed to phase 2, with the reason the emitter is a sibling module. The index's phase-2 **Owns** now names it and **Does not touch** now says "`popups_extract.py` — not one byte". |
| **File count drift.** The index's Phases table said phase 2 touches 61 files, counting only data. | 2 → index | **62**: 61 data files + `popups_emit.py`. A "File counts, spelled out" line was added under the table so the three numbers (3 / 62 / 1) cannot be re-derived wrong. |
| **Stale prose, phase 2.** Its handoff repeated the old deletion range `:1497`–`:2896` and "guards G1–G3"; its "About Phase 3" assumption used the deprecated `.Site.Data`; its Count-reconciliation section argued against index wording the analyst had already fixed. | 2, 3 | All three corrected in place: `:1497`–`:2914`, G1–G4, `hugo.Data` (with the I3 reason), and the count section rewritten to say the index now agrees. |
| **Contract drift, phase 3.** Its Interface Contract placed the 51 carriers at "`:1449`–`:1456` (post-edit numbering)" — eight lines for 51 elements, and inconsistent with its own Step 5, which inserts after `:1460` pre-edit. | 3 | Rewritten to name the pre-edit anchor and the bottom-up application order, which is what the steps actually do. |
| **Count drift, phase 3 exit criteria.** Said the verifier must report "all 50 pre-existing ids matching", one short of what phase 1's verifier actually prints. | 1 ↔ 3 | Both the Verification section and exit criterion 1 now say `PASS 51` — the 50 ids that render today plus `feature-flags`, tagged by the verifier as checked against the dead case. The index's phase-3 exit criteria say the same. |
| **Post-phase-3 tooling trap.** After the switch is deleted, `popups_extract.py` run against the worktree page finds zero cases and exits 2. | 1 ↔ 3 | Phase 1 already pinned the re-check form (`--rev d963643`); phase 3's Assumptions now state the consequence explicitly, so a session re-running the extractor after landing does not read exit 2 as a regression. |
| **Stale "flagged for the reconciler" markers.** Phases 1, 2 and 3 each carried handoffs asking for index/analysis prose fixes the analyst had already applied (counts 50→51 / 60→61, `body: \|` → `\|2`, `.Site.Data` → `hugo.Data`, the `:2914`/`:2911`/`:2916`/`:2919` line numbers, the era-8 case shape, the "all 51 ids MISSING" criterion). | 1, 2, 3 | Every one rewritten to **DONE**, with what it now says. A plan that still asks for a fix already made sends the executing session looking for a discrepancy that is not there. |

**Checked and clean:** no deleted-then-used symbol (the only deletion in the set is the switch, in
the last phase, and `--rev` keeps the baseline re-derivable forever); every `Requires` is satisfied
by an earlier phase (2 ← 1's `norm` + baseline; 3 ← 2's data, gated by 1's verifier); no phase
leaves the tree unbuildable (1 and 2 are purely additive and I4 is measured); every Reference-List
entry and Impact Point is owned. The analysis's Impact Point 4 attributes the data-tree write to
`popups_extract.py`; the plans split that across `popups_extract.py` (baseline) and
`popups_emit.py` (tree), which is a refinement of the analysis, not a gap in the plans.

---

## Decisions

| Fork | Chosen | Rung |
|---|---|---|
| **D1** — R2: the duplicate `dark-launch`. User framed it as "keep one, or merge them", but the duplication is on **both** sides: two *trigger buttons* in two different cards (`:388` Multimodal Processing "Dark-Launch Flag Discipline", `:617` System Observability "Dark-Launch Feature Flags"), both resolving to the live `:1754` body. Keeping one body forces deleting one button, which breaks verification property (b). | **Split into two popups.** `dark-launch` keeps the narrow `:1754` body in Multimodal Processing. The dead `:2885` body is resurrected as a new id **`feature-flags`** in System Observability, where its button already sits and already says "Dark-Launch Feature Flags". Nothing is dropped; both cards become correct; property (b) holds except the one `onclick` id — the single sanctioned exception the user allowed. | 5: the user's raw input — *"Do not silently drop either body"* is the stated reason behind the fork, and splitting is the only branch that drops nothing. Reinforced by evidence the user did not have: `git log -S` puts **both bodies and both buttons in the same commit** (`5f32106`, 2026-07-25), so the author deliberately wrote two entries for two cards and collided the id. It was never a stale edit over a shipped page. **Departs from the literal phrase "the single surviving popup"** — flagged here so it can be overturned in one commit: to instead merge, delete `data/popups/feature-flags.yaml`, fold its content into `dark-launch.yaml`, and drop the `:617` button. |
| **D2** — I1 (bodies "CHARACTER-IDENTICAL") vs R3 (normalise indentation). The bodies' internal indentation *is* the indentation R3 names, so the two cannot both hold literally. | **Character-identical after `norm`** (I1), with `norm` applied identically to both sides of the diff by one shared function. It strips only *uniform* leading indentation, so every content byte and all relative whitespace — including inside the two `<pre><code>` blocks — must still match exactly. | 1: a stated plan invariant, chosen because R3 explicitly sanctions re-indenting this region and leading indentation between block tags has no rendering effect. The looser reading ("roughly the same prose") is rejected outright: the user said a loose version is useless. |
| **D3** — where card membership and ordering live: a shared `cards.yaml` listing ids per card, versus `card:`/`order:` fields inside each popup file. | **Fields inside each popup file**, with `popup_cards/<card>.yaml` holding only card metadata. | 4: the index's Why — the swarm rationale is the stated point of the refactor, and a shared id-list manifest would be a second file every new section must append to, reintroducing the collision at one remove. Cost accepted: ordering is distributed, mitigated by orders in tens, an `(order, id)` tie-break, and build-failing guard G3. |
| **D4** — how bodies reach the browser: a `jsonify`'d JS map, hidden `<template>` elements, or `<script type="text/html">` carriers. | **`<script type="text/html">` carriers**, read via `textContent`. | 1: invariant I1. Measured in a throwaway Hugo v0.164.0 build: `safeHTML` into a non-JS script type emits the prose verbatim, and raw-text parsing returns it byte-exact with entities undecoded — so I1 holds *by construction*. `jsonify` works but re-encodes as `<` and puts prose back inside JS; `<template>` re-serialises through the HTML parser, which I1 cannot assume is byte-stable. |
| **D5** — where the plan artifacts live, given `/docs/` is gitignored. | **Worktree root.** | 6: surrounding convention — `/analyze`'s own Step-4 table resolves to the root when the worktree has no `docs/`, and here that also means the plan survives the merge rather than dying with the worktree. |
| **D6** *(added at reconciliation)* — the inter-card blank line. The page today puts a blank line between feature-cards in the `agents` and `screener` grids but **not** in the `features` grid (`:573`/`:585`/`:597`/`:609` are contiguous). R3 forces one convention, so the two live branches were: phase 3 emits the blank line everywhere (the `features` grid gains 3 lines), **or** phase 1 strips blank lines in `norm` on the trigger side so a raw-byte comparison survives. Phase 3 asked phase 1 to confirm; phase 1 never saw the question. Left unresolved, each plan assumes the other handles it. | **Phase 3 emits the blank line uniformly in all three grids; phase 1 changes nothing.** Phase 1's verifier is blind to blank lines *by construction*: `extract_cards` is a line classifier (a blank line matches none of its six anchored patterns and is never recorded) and `compare_cards` diffs `<li>` strings it reconstructs from the parsed model, so whitespace between records cannot reach the comparison. `norm()` is applied to bodies only and gains no blank-line rule. I2's wording is amended to say so. Phase 1's Interface Contract §3 now states this as an owned guarantee rather than an accident of implementation. | 1: a stated invariant — I2 names `popups_verify.py` as the thing that checks property (b) and then enumerates it structurally (same structure, same buttons, same `class`/`type`/`onclick`/label, same order, same cards, same sections). A blank line is in none of that enumeration. Reinforced by the exit criteria (rung 2): phase 1's criterion 5 shows the verifier already passing 9 of 10 cards against the *current* render, which it could not do if inter-record whitespace mattered. The losing branch — teaching `norm` about blank lines on the trigger side — is edited out of both plans; it would have added a second normalisation rule to protect a comparison nothing performs. |

---

## Open Questions

*None.* Every fork — in the draft and in reconciliation — was decided on the ladder and recorded in
**Decisions**; every requirement id has at least one phase serving it (R1 → 1, 2, 3; R2 → 2;
R3 → 2, 3). Nothing in this refactor has a branch that is irreversible, which is the only thing
that may be parked here.

D1 is the one worth a human's glance in the morning — it departs from the literal wording of R2 to
honour its stated reason, and the Rung column spells out how to overturn it in one commit. D6 is
the reconciliation-time fork and needs no glance: both branches were behaviour-preserving and the
chosen one requires no code on either side.

---

## Rollback

**Per phase.** Each phase is one commit on `feature/popup-data-refactor`; `git revert <sha>` backs
it out. Phases 1 and 2 are additive — reverting either leaves the page rendering from the switch,
because nothing consumes the new files until phase 3.

**As a whole.** `git checkout main -- hugo_docs/layouts/page/custom-home.html` restores the switch;
`git rm -r hugo_docs/data/popups hugo_docs/data/popup_cards hugo_docs/scripts/popups_*` removes the
rest. Nothing outside the worktree is touched, no CI or config changes, and `main` is never written.

**If D1 is overturned**, see its Rung cell: one commit, three file operations.

---

## Next

Execute the phases one at a time, starting at phase 1:

    /implement -f POPUP_DATA_REFACTOR_PLAN.md --phase 1

Or run the whole set as a swarm — a session per phase, concurrent wherever `Depends on` allows,
resumable on any machine:

    /analyze-orchestrator -f POPUP_DATA_REFACTOR_PLAN.md

Or put them on the board first (GitHub repos only):

    /create-task --from-plan POPUP_DATA_REFACTOR_PLAN.md
