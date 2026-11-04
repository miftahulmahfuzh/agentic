# Feature map: agentic docs site

One file per reader-facing feature. Each lists what a reader does, the `verify.sh` recipe that
proves it, and the end state that recipe produced on a real run. No drive costs money: the site
has no paid dependency (see SKILL.md, Gotchas).

| Feature | File | Surfaces | Steps / command | State (after the offline fix) |
|---|---|---|---|---|
| Home page navigation: masthead, disclosures, request rail | [home-navigation.md](home-navigation.md) | ui, page | `steps/sections.mjs` | pass |
| Architecture diagrams in the viewer tab | [architecture-diagrams.md](architecture-diagrams.md) | ui | `steps/diagrams.mjs` | pass |
| Feature popups (51, from `data/popups/`) | [feature-popups.md](feature-popups.md) | ui, build | `steps/popups.mjs`, `build` | pass |
| Documentation pages (theme-rendered) | [docs-pages.md](docs-pages.md) | ui, page | `steps/docs.mjs` | pass |
| Production build, popup harness, link check | [production-build.md](production-build.md) | build | `build` | **fails**: 16 broken links |
| Home page without the CDN (fault injection) | [offline-cdn.md](offline-cdn.md) | ui (`up --offline`) | `steps/offline.mjs` | pass (failed before the fix: 6 of 7 broken) |

A change that alters what a reader sees updates its entry here in the same change. Steps files
live in `steps/`. Run them from the repo root as
`$V ui RUN .claude/skills/verify-agentic-docs/features/steps/<name>.mjs`.
