# Todos: layouts

**Package Path**: `hugo_docs/layouts`

**Package Code**: HL

**Last Updated**: 2026-10-27 12:00:00

**Total Active Tasks**: 1

## Quick Stats
- P0 Critical: 0
- P1 High: 0
- P2 Medium: 1
- P3 Low: 0
- P4 Backlog: 0
- Blocked: 0
- Completed: 1

---

## Active Tasks

### [P0] Critical
*No critical tasks.*

### [P1] High
*No high priority tasks.*

### [P2] Medium
- [ ] **P2-HL-A002** Phase 3: Rewire the template, delete the switch
  - **Difficulty**: HARD
  - **Type**: Refactor
  - **Context**: Owns `hugo_docs/layouts/page/custom-home.html` only. Exit criteria: `popups_verify.py` exits 0 — property (a) reports `PASS 51` (the 50 ids that render today, plus `feature-flags` checked against the dead `:2885` body) and property (b) reports all 10 cards PASS; `~/bin/hugo` builds clean with no `--gc` and `hugo_docs/resources/` is untouched; `grep -c 'case "' custom-home.html` is 0 and the file is ~1,400 lines shorter (3,011 → ~1,604); each of G1, G2, G3, G4 and the content assertions **fails the build** when violated — demonstrated and recorded, and the build returns to exit 0 on restore; manual browser check confirms property (c): popups open, close three ways, restore focus, and the 13 Mermaid bodies render their diagrams.
  - **Status**: open
  - **Plan Set**: `/home/miftah/agentic/.workflows/orchestration/popup-data-refactor/PLAN.md` (phase 3 of 3)
  - **Satisfies**: R1, R3 — R1: Replace the `showPopup` switch with Hugo data files, generating **both** trigger buttons and modal bodies from one source; a trigger without a body (or a body without a trigger) must become a build-time failure or a structural impossibility. Design and justify the data shape.; R3: Normalise the two indentation eras in the popup region (flat vs 8-space).
  - **Depends on**: P2-HD-A001
  - **Plan**: `.workflows/plan/popup-data-refactor/phase-3.md` (repo root). Not copied under `hugo_docs/layouts/`: Hugo parses every file there as a template, and this plan's Go-template samples fail the build.

### [P3] Low
*No low priority tasks.*

### [P4] Backlog
*No backlog tasks.*

### 🚫 Blocked
*No blocked tasks.*

---

## Completed Tasks

- [x] **P1-HL-A001** Phase 1: Stock Screener home-page section, diagram and catalog cross-link
  - **Difficulty**: NORMAL
  - **Type**: Feature
  - **Context**: Owns every edit to `hugo_docs/layouts/page/custom-home.html` and the additive block appended to `hugo_docs/static/style.css`. Does not touch `content/docs/**`, `public/**`, `themes/`, `resources/`, any file under `~/agentic_golang`, and every pre-existing section, diagram, popup case and CSS rule. Exit criteria: (a) `<section id="screener">` exists between the `agents` and `features` sections, with an eyebrow, an `<h2>`, a `lede`, a `.diagram-open` button, a hidden diagram source and feature cards; (b) clicking the diagram button opens `diagram.html?d=screener` in a new tab and the Mermaid renders; (c) every new `popup-trigger` opens a populated modal; (d) the Tool catalog's **Screening, Rankings & Curated Selections** list has a `stock_picker` row whose term is clickable and scrolls `#screener` into view; (e) `hugo` builds clean and the rendered `public/index.html` carries all of the above.
  - **Status**: completed
  - **Plan Set**: `docs/plans/HOME_STOCK_SCREENER_SECTION_PLAN.md` (phase 1 of 1)
  - **Satisfies**: R1, R2, R3 — R1: Find where the Hugo home page lives — the file that becomes the deployed `index.html`; R2: Learn the v2.4.0 stock screener (`stock_picker`, T-240009) from `~/agentic_golang`, then add a new home-page section below **Multi-Agent Routing & Multimodal Input**, with a Mermaid diagram that opens in a new tab exactly like the agents diagram; R3: Add a clickable **stock screener** entry under **Tool catalog → Screening, Rankings & Curated Selections** that auto-scrolls to the new section
  - **Depends on**: —
  - **Plan**: `.workflows/plan/P1-HL-A001.md`
  - **Completed**: 2026-10-27 08:39
  - **Method**: /do
  - **Files**: hugo_docs/layouts/page/custom-home.html, hugo_docs/static/style.css, hugo_docs/layouts/.workflows/todos.md, hugo_docs/layouts/.workflows/plan/P1-HL-A001.md

---

## Archive

*Nothing archived yet.*
