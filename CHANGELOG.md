# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v0.4.0] - 2026-06-18

### Added
- Portfolio-grade revamp of the landing page (`layouts/page/custom-home.html`) to a control-plane design.
- Interactive System Architecture diagram with a direct-open modal and a hoverable request-lifecycle rail.
- Enhanced cache metadata, detailed tool logging, and real-time status tracking on the home page.
- `CLAUDE.md` describing the home page and documentation structure.
- Tools documentation section.
- Cache fast-lane documentation, architecture diagram, and comprehensive test suite (semaphore-bypass validation, FIFO/eviction tests, performance benchmarks, integration coverage).
- Priority-dispatch documentation and test section.
- Circuit breaker pattern documentation.
- Stream broadcaster documentation and E2E stream-broadcasting/cancellation coverage.
- Sauron observability documentation.
- Design-pattern, `four_pigs`, `baba_yaga`, and additional narrative documentation.
- `python_vs_go`, `python_workers`, and concurrency-vs-parallelism documentation.
- Janitor and optimization documentation sections.
- Documentation for the `GET /chat/status/:id` endpoint.

### Changed
- Aligned endpoint-reference descriptions to a fixed column on the home page.
- Refreshed System Architecture, cache fast-lane, and priority-dispatch diagrams.
- Updated Usage & Testing, Performance, and project-structure sections.
- Regenerated `public/` as a production build.

### Fixed
- Restored reverted landing-page interactivity and rebuilt for production.
- Direct-open architecture modal, hoverable lifecycle rail, and header alignment.

### Removed
- Stopped tracking `hugo_docs/public/` in git (built by CI, not served from the repo).
- Removed unused documentation pages.

[v0.4.0]: https://github.com/miftahulmahfuzh/agentic/releases/tag/v0.4.0
