# Todos: scripts

**Package Path**: `hugo_docs/scripts`

**Package Code**: HS

**Last Updated**: 2026-10-27 12:52:58

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

- [x] **P2-HS-A001** Phase 1: Extraction & verification tooling
  - **Difficulty**: NORMAL
  - **Type**: Refactor
  - **Context**: Owns `hugo_docs/scripts/popups_extract.py`, `hugo_docs/scripts/popups_verify.py`, `hugo_docs/scripts/popups_baseline.json`. Exit criteria: `popups_extract.py` run against the current page emits 51 bodies and 51 triggers; `popups_baseline.json` is committed and contains all of them; `popups_verify.py` runs end-to-end against the *current* (pre-refactor) build and reports all 51 ids as `MISSING` — proving the render-side extractor runs and that the check is not yet vacuously green. Tree builds clean.
  - **Status**: completed
  - **Plan Set**: `/home/miftah/agentic/.workflows/orchestration/popup-data-refactor/PLAN.md` (phase 1 of 3)
  - **Satisfies**: R1 — R1: Replace the `showPopup` switch with Hugo data files, generating **both** trigger buttons and modal bodies from one source; a trigger without a body (or a body without a trigger) must become a build-time failure or a structural impossibility. Design and justify the data shape.
  - **Depends on**: —
  - **Plan**: `.workflows/plan/P2-HS-A001.md`
  - **Completed**: 2026-10-27 12:52
  - **Method**: /do
  - **Files**: hugo_docs/scripts/popups_extract.py, hugo_docs/scripts/popups_verify.py, hugo_docs/scripts/popups_baseline.json, hugo_docs/scripts/.workflows/todos.md, hugo_docs/scripts/.workflows/plan/P2-HS-A001.md, hugo_docs/data/.workflows/todos.md, hugo_docs/data/.workflows/plan/P2-HD-A001.md, hugo_docs/layouts/.workflows/todos.md, hugo_docs/layouts/.workflows/plan/P2-HL-A002.md
  - **Decided**:
    - script file mode -> 0644, not +x (rung 6: sibling scripts gen_og_image.py/sync_anchor_docs.py are 0644; invoked as python3 <script>)
    - commit the Step-3 bookkeeping (todos.md + adopted plans for all 3 phases) with phase 1 -> yes (they are this session's own files; leaving them dirty in the shared worktree invites a later phase to commit them under its message)

---

## Archive

*Nothing archived yet.*
