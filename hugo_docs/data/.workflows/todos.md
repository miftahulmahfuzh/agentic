# Todos: data

**Package Path**: `hugo_docs/data`

**Package Code**: HD

**Last Updated**: 2026-10-27 12:00:00

**Total Active Tasks**: 1

## Quick Stats
- P0 Critical: 0
- P1 High: 0
- P2 Medium: 1
- P3 Low: 0
- P4 Backlog: 0
- Blocked: 0
- Completed: 0

---

## Active Tasks

### [P0] Critical
*No critical tasks.*

### [P1] High
*No high priority tasks.*

### [P2] Medium
- [ ] **P2-HD-A001** Phase 2: Generate the popup data tree
  - **Difficulty**: NORMAL
  - **Type**: Refactor
  - **Context**: Owns `hugo_docs/data/popups/*.yaml` (51), `hugo_docs/data/popup_cards/*.yaml` (10), the new `hugo_docs/scripts/popups_emit.py`, and the dark-launch split (D1). Exit criteria: 61 data files exist (51 popups + 10 cards) plus `popups_emit.py`; the round-trip assertion passes for all 51 ids; the resurrected `feature-flags` body matches the dead `:2885` case after `norm`; `~/bin/hugo` builds clean (the data is present but not yet consumed); the rendered page is **unchanged** — still driven by the switch, and the whole output tree is byte-identical to the pre-phase build (I4).
  - **Status**: open
  - **Plan Set**: `/home/miftah/agentic/.workflows/orchestration/popup-data-refactor/PLAN.md` (phase 2 of 3)
  - **Satisfies**: R1, R2, R3 — R1: Replace the `showPopup` switch with Hugo data files, generating **both** trigger buttons and modal bodies from one source; a trigger without a body (or a body without a trigger) must become a build-time failure or a structural impossibility. Design and justify the data shape.; R2: Resolve the duplicate `case "dark-launch":` (`:1754` live, `:2885` dead). Decide deliberately, record the choice and reasoning here, drop neither body silently.; R3: Normalise the two indentation eras in the popup region (flat vs 8-space).
  - **Depends on**: P2-HS-A001
  - **Plan**: `.workflows/plan/P2-HD-A001.md`

### [P3] Low
*No low priority tasks.*

### [P4] Backlog
*No backlog tasks.*

### 🚫 Blocked
*No blocked tasks.*

---

## Completed Tasks

*No completed tasks yet.*

---

## Archive

*Nothing archived yet.*
