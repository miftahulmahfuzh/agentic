# Package: scripts

**Location**: `hugo_docs/scripts`
**Last Updated**: 2026-10-27

## Overview

Standalone Python 3 maintenance scripts for the Hugo documentation site. None of them
run during a Hugo build. A person or an agent runs them by hand (`python3 <script>`,
mode 0644, never `+x`) to produce or check files that the site then commits. There is
no `__init__.py`. The only import between scripts is `popups_verify.py` importing
`popups_extract.py`.

**Key Responsibilities:**
- Draw the Open Graph link-preview card `static/og-image.png` (`gen_og_image.py`).
- Sync one `content/docs/<section>/` from its anchor directory in the Go repo
  (`sync_anchor_docs.py`, which `/update-hugo-docs` drives).
- Freeze the landing page's pre-refactor popups into a baseline and check the
  rendered page against it (`popups_extract.py`, `popups_verify.py`,
  `popups_baseline.json`). This is the tooling for phase 1 of the popup-data refactor.

## Files

| File | Role | Writes |
|---|---|---|
| `gen_og_image.py` | Renders the 1200x630 OG card with Pillow, using the real webfonts | `static/og-image.png`, `scripts/.fontcache/` (gitignored) |
| `sync_anchor_docs.py` | Anchor-to-Hugo doc sync: drops the H1, prepends frontmatter, rewrites `../x.md` links, takes dates from the anchor's git log | `content/docs/<section>/*.md` |
| `popups_extract.py` | Parses the `showPopup` switch and the feature-card trigger lists out of `layouts/page/custom-home.html`. Owns `norm()` and every shared contract | `scripts/popups_baseline.json` |
| `popups_verify.py` | Builds the site into a temp directory, reads bodies and triggers back out of the rendered `index.html`, and diffs them against the baseline | nothing |
| `popups_baseline.json` | Frozen popup data from before the refactor. Committed, and generated only | — |

## Exported API (popups_extract.py)

`popups_extract.py` is the single owner of everything the popup refactor compares
through. Its siblings import these names and must not define their own copies.
`popups_verify.py` imports them today. `popups_emit.py` (phase 2, planned in
`hugo_docs/data/.workflows/plan/P2-HD-A001.md`) will import them too.

### Functions

#### norm
```python
def norm(s: str) -> str
```
The one normalisation used throughout the refactor (plan invariant I1). It:
1. converts CRLF and bare CR to LF,
2. empties whitespace-only lines,
3. removes the longest leading-whitespace prefix that all non-blank lines share,
4. strips leading and trailing blank lines,
5. ends the result with exactly one newline.

It is idempotent. Step 3 removes only the shared prefix. It does not strip each line,
so relative indentation is kept. 15 bodies contain a block that already starts at
column 0 (Mermaid sources, `<pre><code>`), so they keep a residual indent: 9 at
4 spaces, 6 at 16. This is correct, `--self-test` pins it in `RESIDUAL_INDENTS`, and
it must not be "fixed".

#### js_unescape
```python
def js_unescape(raw: str, where: str) -> str
```
Turns template-literal source text into the string the browser sees, using the
`JS_ESCAPES` table. An unknown escape raises `ExtractError` instead of guessing. Today
the page has exactly one escape: `alerting` at :2842, where `"\\n"` renders as a single
backslash followed by `n`.

#### read_page
```python
def read_page(page: Path, rev: str | None) -> str
```
Returns the page text from the worktree, or with `rev` set, from
`git show <rev>:hugo_docs/layouts/page/custom-home.html`. `--rev` keeps `--check`
usable after phase 3 has rewritten the page.

#### extract_cases
```python
def extract_cases(lines: list[str]) -> list[dict]
```
Returns every `case "<id>": popupContent = \`...\`; break;` in source order, as
`{id, line, close_line, indent, body}` with `body` already unescaped and normalised.
It finds the closing `` `; `` by scanning, because the closing indent differs between
the 38 older cases and the 13 newer ones. A body that contains a backtick or `${`, or
that is empty, is fatal.

#### extract_cards
```python
def extract_cards(lines: list[str]) -> list[dict]
```
Returns the feature cards in source order, as `{section, line, icon, heading,
triggers: [{id, label, line}]}`. It only looks inside `<div class="feature-grid">`
blocks within `<section id=...>`, and `section` must be one of `SECTIONS`. Headings and
labels keep their HTML entities exactly as written (`&amp;`). It parses the source page
and the rendered page equally well, which is why the verifier reuses it.

#### build_baseline / dumps
```python
def build_baseline(text: str) -> dict
def dumps(baseline: dict) -> str
```
`build_baseline` runs both extractors and checks the expected counts, that the case-id
set equals the trigger-id set, and that `dark-launch` is the only duplicated id on both
sides. Any failure raises one combined `ExtractError`. The result deliberately has no
absolute path and no revision string: `source_sha256` pins the input. `dumps` produces
deterministic JSON (sorted keys, indent 2, `ensure_ascii=False`, trailing newline).

### Constants (the contracts)

| Name | Value / meaning |
|---|---|
| `N_OCCURRENCES`, `N_UNIQUE_IDS`, `N_CARDS`, `N_TRIGGERS` | 51, 50, 10, 51. These are assertions, not configuration. Change them in the same commit that re-freezes the baseline |
| `SECTIONS` | `("agents", "screener", "features")` |
| `SPLIT_ID`, `SPLIT_NEW_ID` | `"dark-launch"`, `"feature-flags"`. Decision D1 |
| `SPLIT_CARD`, `SPLIT_CARD_HEADING` | `"system-observability"` (phase-2 `popup_cards/` basename), `"System Observability"` |
| `SPLIT_OCCURRENCE` | `1`, the zero-based index of the dead second `dark-launch` case (:2885) |
| `TRIGGER_RE`, `TRIGGER_LINE` | The exact `<li><button class="popup-trigger" type="button" onclick="showPopup('<id>')">label</button></li>` shape. Leading whitespace is the only thing allowed to vary |
| `CARD_OPEN_LINE`, `H4_LINE` | The card wrapper and the `<h4><svg class="ic"><use href="#icon"/></svg> heading</h4>` line that phase 3 must render |
| `CARRIER_OPEN`, `CARRIER_RE` | `<script type="text/html" class="popup-body" data-popup-id="<id>">body</script>`, the element that carries a popup body after the refactor |
| `HUGO_ROOT`, `PAGE`, `PAGE_REL`, `BASELINE` | Paths anchored on `Path(__file__).parent.parent` |

`ExtractError(RuntimeError)` is raised for any structural surprise. It is always fatal
and never worked around.

## popups_verify.py

Turns the refactor's two verification properties into a command anyone can run:

- **(a)** For each popup id, the rendered carrier body, after `norm()`, matches the
  baseline body byte for byte. Each id keeps the body of its *first* case occurrence,
  because a JS switch takes the first match.
- **(b)** Card list (section, heading, icon) and each card's trigger `<li>` lines are
  unchanged and in the same order.

The only allowed difference is D1. `feature-flags` is a new id, checked against the
*dead* `dark-launch` body, and the System Observability button's onclick moves to it.
The script prints this exception by name every run.

Key functions:
- `expected(baseline)` builds the post-refactor bodies and cards from the baseline
  with D1 applied.
- `rendered(index)` reads carrier bodies verbatim and does not decode entities,
  because `<script>` is raw text.
- `compare_bodies` and `compare_cards` report PASS, FAIL, MISSING or EXTRA per id or
  card, with unified diffs.
- `build(binary, keep)` refuses Hugo older than v0.164.0 (`MIN_HUGO`), builds into
  `tempfile.mkdtemp()`, and never passes `--gc` or writes `public/`.

## Data Flow

```
custom-home.html (worktree or --rev)
  -> read_page -> extract_cases + extract_cards -> build_baseline -> dumps
  -> popups_baseline.json (committed)
                                 |
hugo build (temp dir) -> index.html -> rendered()   expected() <- baseline
                                          \            /
                                compare_bodies / compare_cards -> exit 0|1|2
```

The baseline is the fixed point. The page changes over phases 2 and 3, and the
baseline does not.

## Usage

```sh
python3 hugo_docs/scripts/popups_extract.py              # (re)write the baseline from the worktree page
python3 hugo_docs/scripts/popups_extract.py --rev d963643 --check   # drift check against the pre-refactor revision
python3 hugo_docs/scripts/popups_extract.py --self-test  # norm() unit cases, dedent split, JS unescape
python3 hugo_docs/scripts/popups_extract.py --report     # human summary, writes nothing
python3 hugo_docs/scripts/popups_verify.py               # build with ~/bin/hugo, check (a) and (b)
python3 hugo_docs/scripts/popups_verify.py --index /path/to/index.html   # check an existing build
```

Exit codes for both popup scripts: `0` ok, `1` failed check, self-test or mismatch,
`2` usage, parse or build error.

## Dependencies

- `popups_*`: standard library only (`argparse`, `difflib`, `hashlib`, `json`, `re`,
  `subprocess`, `tempfile`, `pathlib`). They also need the external `git` binary for
  `--rev`, and Hugo v0.164.0 or newer at `~/bin/hugo` for `popups_verify.py`.
- `gen_og_image.py`: Pillow. It downloads webfonts over the network on first run.
- `sync_anchor_docs.py`: standard library plus `git` (it reads dates from the anchor
  repo's log).

## Reverse Dependencies

- `popups_verify.py` imports `CARRIER_RE`, `SPLIT_*`, `TRIGGER_LINE`, `ExtractError`,
  `extract_cards` and `norm` from `popups_extract.py`, and reads `popups_baseline.json`.
- `popups_emit.py` (phase 2, not yet written) will read the baseline and the D1
  constants to write `hugo_docs/data/popups/*.yaml` and
  `hugo_docs/data/popup_cards/*.yaml`.
- Phase 3 (`hugo_docs/layouts/.workflows/plan/P2-HL-A002.md`) must render markup that
  matches `TRIGGER_RE`, `H4_LINE` and `CARRIER_RE`.
- `.claude/commands/update-hugo-docs.md` drives `sync_anchor_docs.py`. The
  `custom-home.html` header comment names `gen_og_image.py` as the source of
  `og-image.png`.

## Concurrency

Not designed for concurrent use. These are single-threaded scripts. Two
`popups_verify.py` runs can safely happen at once, because each builds into its own
temp directory. Two writers of `popups_baseline.json` cannot.

## Error Handling

- `ExtractError` (extract) and `VerifyError` (verify) are `RuntimeError` subclasses.
  `main()` catches them and turns them into exit code 2. Nothing panics on purpose.
- Problems are collected and reported together (`build_baseline`), or diffed
  (`--check`, `compare_*`). None is silently skipped.

## Gotchas

- Before the refactor, `popups_verify.py` is supposed to fail. It reports all 51 ids
  as MISSING and exits 1, which proves the render-side extractor really runs.
- After phase 3 rewrites the page, run `--check` only with `--rev <pre-refactor sha>`,
  because the worktree page no longer has a switch to extract.
- Do not hand-edit `popups_baseline.json`. Re-freeze it with `popups_extract.py` and
  move the `N_*` constants in the same commit.
- Do not add a second normaliser anywhere. With two, a byte-for-byte comparison
  quietly stops being byte-for-byte.
- Card and trigger order come from the button lists, not the switch. They disagree
  for Resource Management.
- Use `~/bin/hugo`, not `/usr/bin/hugo` (too old for the Stack theme), and never pass
  `--gc` (it deletes the committed `resources/_gen/`).

## Notes

Documentation Created: 2026-10-27 (task P2-HS-A001, phase 1 of 3 of the popup-data
refactor; plan set `/home/miftah/agentic/.workflows/orchestration/popup-data-refactor/PLAN.md`).
At creation, `--check` against the worktree page was byte-identical and `--self-test`
passed: 10 norm cases, 36 bodies flattened to column 0 and 15 with a residual indent,
and the one `alerting` backslash confirmed.
