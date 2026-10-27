# Package: data (Hugo data tree)

**Location**: `hugo_docs/data`
**Last Updated**: 2026-10-27

## Overview

`hugo_docs/data` is the Hugo site's data directory. It holds no Go code. Right now it holds one dataset: the home page's popup content, split into one YAML file per feature card and one per popup. The files were generated once by `hugo_docs/scripts/popups_emit.py` from the phase-1 baseline. From now on the YAML is the source of truth and is edited by hand.

**Key Responsibilities:**
- Hold the text of every home-page popup (51 popups) and the metadata of every feature card (10 cards), so the 1,174-line `showPopup` switch in `layouts/page/custom-home.html` can be removed.
- Provide one source for both a card's trigger buttons (`label`, `order`) and the matching modal bodies (`body`). That is what makes "a trigger without a body" impossible by construction (requirement R1).
- Record decision D1, the dark-launch split. Both bodies are kept and neither is dropped silently.

**Status**: dark data. Hugo loads these files, but no template reads them yet. The rendered page still comes from the inline switch. Phase 3 of the popup-data-refactor plan connects the template to this data and deletes the switch.

## Data Schema (the "API surface")

Hugo exposes these files to templates as the data maps `popup_cards` and `popups`, keyed by file stem. The file name is the id.

### `popup_cards/<card-id>.yaml` (10 files)

| Field     | Type   | Meaning |
|-----------|--------|---------|
| `section` | string | Home-page section the card renders in: `agents`, `screener` or `features`. |
| `heading` | string | Card `<h4>` text **exactly as authored, HTML entities included** (for example `"Performance &amp; Architecture"`). Double-quoted. |
| `icon`    | string | Icon class (for example `ic-database`, `ic-bolt`). |
| `order`   | int    | Position inside its section: 10, 20, 30, ... |

Cards by section:
- `agents`: `multi-agent-system` (10), `multimodal-processing` (20)
- `screener`: `the-lock` (10), `planning-a-turn` (20), `the-measured-api` (30), `shape-of-the-tool` (40)
- `features`: `performance-architecture` (10), `resource-management` (20), `data-handling-integrity` (30), `system-observability` (40)

Card ids are **pinned** in `CARD_IDS` in `popups_emit.py`, and each one is checked against `slugify(heading)`. A new card needs an entry there.

### `popups/<popup-id>.yaml` (51 files)

| Field   | Type   | Meaning |
|---------|--------|---------|
| `card`  | string | Id of the owning card. Must match a file in `popup_cards/` (guard G1). |
| `order` | int    | Trigger position inside the card: 10, 20, ... (trigger order, **not** switch order). Unique per card (G3). |
| `label` | string | Trigger button text. Double-quoted, entities as authored. |
| `body`  | string | Raw modal HTML, written as a literal block scalar with an explicit indent indicator: `body: \|2`. |

Popups per card: data-handling-integrity 7, performance-architecture 7, resource-management 7, multi-agent-system 6, system-observability 6, multimodal-processing 5, shape-of-the-tool 4, planning-a-turn 3, the-lock 3, the-measured-api 3.

Each file starts with a two-line `#` header saying it was generated once and is now the source of truth.

### Decision D1: dark-launch split

The old switch declared `case "dark-launch":` twice. The first case was live and the second was dead, because it could never be reached.
- `popups/dark-launch.yaml` keeps the **live** body ("Dark-Launch Flag Discipline") in `multimodal-processing`, order 50.
- `popups/feature-flags.yaml` is the **dead** body brought back under a new id ("Dark-Launch Feature Flags") in `system-observability`, order 60. That card already had a trigger button with this label.

The split constants (`SPLIT_ID`, `SPLIT_NEW_ID`, `SPLIT_CARD`, `SPLIT_OCCURRENCE`) are defined only in `scripts/popups_extract.py`. The emitter and the verifier import them from there.

## Data Flow

```
layouts/page/custom-home.html (showPopup switch + card markup)
   -> scripts/popups_extract.py        (phase 1)  -> scripts/popups_baseline.json
   -> scripts/popups_emit.py emit      (phase 2)  -> data/popup_cards/*.yaml, data/popups/*.yaml
   -> Hugo data maps popup_cards / popups
   -> custom-home.html range over the data   (phase 3, not yet wired)
```

`popups_emit.py` subcommands (run from the repo root):
- `python3 hugo_docs/scripts/popups_emit.py emit [--force]`: writes the tree from the baseline. **Refuses to overwrite** existing YAML unless `--force` is passed. Only use `--force` to bootstrap again on purpose, because it throws away hand edits.
- `python3 hugo_docs/scripts/popups_emit.py check`: read-only. Requires PyYAML. Checks that the file set on disk matches the plan, that every card field and popup field matches, and that each `norm(body)` is byte-identical to the baseline. Also runs the integrity checks G0-G3 and confirms there is exactly one label/`<h2>` mismatch (`screener-content-is-routing`, which is intentional). Exit code is 0 on success, 1 on failure, 2 if the baseline or PyYAML is missing. Current result: `checked 10 cards + 51 popups; failures: 0`.

The integrity checks that phase 3 turns into build guards:
- **G0**: no duplicate popup id (that would be a file-name collision).
- **G1**: every popup's `card` names an existing card.
- **G2**: every card has at least one popup.
- **G3**: no two popups in a card share an `order`.
- Also enforced: labels and bodies are non-empty, and no body contains `</script>`.

## Dependencies

- **Producer**: `hugo_docs/scripts/popups_emit.py`, which imports `norm` and the D1 constants from `popups_extract.py` and reads `popups_baseline.json`. There must be only one `norm()`. A second copy would let the emitter and the checker drift apart without anyone noticing.
- **Consumer**: none yet. Phase 3: `hugo_docs/layouts/page/custom-home.html`.
- **Tooling**: PyYAML is needed only for `check`, at dev time. Hugo's own parser is the final word on whether the YAML is valid. Build with `~/bin/hugo`, because `/usr/bin/hugo` is too old for the theme. Never pass `--gc`.

## Concurrency

This package is static data and is not designed for concurrent use. Hugo reads it once at build time.

## Gotchas

- **Keep `|2`, not `|`.** 15 of the 51 bodies start with leading whitespace (mermaid and `<pre>` blocks). With a bare `|`, YAML guesses the indent from the first line and gets it wrong. The explicit indicator makes the parse independent of the content.
- Bodies end in exactly one newline (clip chomping). Do not add trailing blank lines, and do not use tabs.
- Entities stay encoded (`&amp;`) in `heading` and `label`, and nothing is decoded. The template must output them as-is.
- `label` is not always the same as the body's `<h2>`. `screener-content-is-routing` is the one intentional case, and `check` fails if a second case appears.
- Renaming a file renames the popup id. Update the `card:` references and any trigger ids at the same time.
- Never put Hugo template files or plan documents under `hugo_docs/layouts/`, because Hugo parses everything there as a template and the build breaks.

## Notes

Documentation Created: 2026-10-27, after P2-HD-A001 (phase 2 of 3, popup-data-refactor). Plan: `.workflows/plan/P2-HD-A001.md`. Plan set: `/home/miftah/agentic/.workflows/orchestration/popup-data-refactor/PLAN.md`.
