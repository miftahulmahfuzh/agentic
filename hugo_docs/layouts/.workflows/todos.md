# Todos: layouts

**Package Path**: `hugo_docs/layouts`

**Package Code**: HL

**Last Updated**: 2026-10-27 08:39:00

**Total Active Tasks**: 0

## Quick Stats
- P0 Critical: 0
- P1 High: 0
- P2 Medium: 0
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
*No medium priority tasks.*

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
