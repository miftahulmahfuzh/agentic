# Package: layouts

**Location**: `hugo_docs/layouts`
**Last Updated**: 2026-10-27

## Overview

Hugo template package for the Tuntun Go Agentic Chatbot documentation site. It owns
exactly two things: the standalone landing page (`page/custom-home.html`, a
self-contained ~1,600-line document that becomes the deployed `index.html`), and a
small set of partial overrides that bend the vendored `hugo-theme-stack` where its
defaults were wrong for this site.

This package is **authored**, unlike its sibling `hugo_docs/content/docs/`, which is
generated from the Go repo. Edits to the landing page are made here and nowhere else.

**Key Responsibilities:**
- Render the landing page — the canonical, highest-signal description of what the
  chatbot system is and how it behaves.
- Render the popup triggers and popup bodies from the data files under
  `hugo_docs/data/popup_cards/` and `hugo_docs/data/popups/`, and fail the build when
  that data is inconsistent.
- Carry the page's client runtime inline: section disclosures, the popup modal, and
  the hand-off to the standalone Mermaid diagram viewer.
- Override four theme partials so documentation pages advertise a link-preview image
  and lead with their revised date.

## Template Surface

Hugo selects templates by lookup order, so the "public API" of this package is the set
of paths Hugo will resolve, not a set of callable symbols.

### `page/custom-home.html`

Selected by `hugo_docs/content/_index.md` frontmatter:

```yaml
title: "Tuntun Go Agentic Chatbot"
layout: "custom-home"
type: "page"
```

Both `layout` and `type` are load-bearing — `type: "page"` is what sends Hugo into the
`page/` directory. A full `<!doctype html>` document: it defines no Hugo block and
inherits nothing from the theme's baseof. Everything — icon sprite, CSS link, Mermaid
script tag, markup, and the whole `<script>` runtime — lives in this one file.

Hugo variables consumed: `.Title`, `.Permalink`, `.Site.Title`,
`.Site.Params.description`, `hugo.Data.popup_cards`, `hugo.Data.popups`, and `absURL`
for `style.css`, `favicon.png`, `og-image.png`, `diagram.html`.

`hugo.Data` is used rather than `.Site.Data`: the latter is deprecated as of Hugo
v0.156.0 and logs a WARN.

### Popup data (build-time, top of `page/custom-home.html`)

Before a byte renders, a template preamble indexes the popup data and validates it.

**Inputs** (source of truth since phase 2 of popup-data-refactor; edit prose there,
not in the template):

| Directory | Files | Fields |
|---|---|---|
| `hugo_docs/data/popup_cards/<card-id>.yaml` | 10 | `section` (one of `agents`, `screener`, `features`), `heading`, `icon` (sprite id, e.g. `ic-database`), `order` |
| `hugo_docs/data/popups/<popup-id>.yaml` | 51 | `card` (a card id), `order` (within the card), `label` (trigger button text), `body` (modal HTML) |

The file basename is the id. One popup file carries both the trigger `label` and the
modal `body`, so a trigger without a body cannot be written down.

**Build guards** — each is an errorf call, which makes `hugo` exit non-zero:

| Guard | Fails when |
|---|---|
| G1 unknown card | a popup has no `card`, or names a card with no `popup_cards/<id>.yaml` |
| G2 orphan card | a card has no popups pointing at it |
| G3 order collision | two popups in one card share an `order` |
| G4 unknown section | a card's `section` is not `agents`, `screener` or `features` |
| content assertions | a card with empty `heading`/`icon` or missing `order`; a popup with missing `order` or empty `label`/`body`; a `body` containing a literal closing script tag (it would terminate its carrier early) |

**Rendering**: cards are sorted by `order` (id tie-break) and each of the three
feature grids ranges over the cards whose `section` matches, emitting a
`.feature-card` with its icon, heading, and one `<button class="popup-trigger"
onclick="showPopup('<popup-id>')">` per popup sorted by `order`. After the grids, one
inert carrier per popup is emitted from the same slice, sorted by id:

```html
<script type="text/html" class="popup-body" data-popup-id="<popup-id>">…body…</script>
```

`type="text/html"` is a non-JS script type, so Go's context-aware escaper leaves the
content alone and safeHTML emits it verbatim. Never rendered, never executed.

**Twelve sections**, in document order, each an `<section id="…">` the masthead can
target:

| id | Heading |
|---|---|
| `overview` | hero |
| `architecture` | System Architecture |
| `agents` | Multi-Agent Routing & Multimodal Input |
| `screener` | Multi-Turn Stock Screening |
| `features` | Core Engineering & Features |
| `tools` | Tool catalog |
| `api` | API Endpoints |
| `installation` | Installation & Setup |
| `configuration` | Configuration |
| `usage` | Usage & Testing |
| `development` | Development |
| `documentation` | Documentation |

The masthead links a subset: Architecture, Agents, Screener, Tools, API, plus an
external link to `docs/`.

### Theme partial overrides

| Path | Overrides | Why |
|---|---|---|
| `partials/head/custom.html` | theme head hook | Emits a fallback `og:image` only when the page declares no featured image. Avoids the theme's `params.defaultImage`, which double-applies the baseURL path and yields `/agentic/agentic/og-image.png`. |
| `partials/article/components/details.html` | article header | Leads with the revised date. |
| `partials/article/components/footer.html` | article footer | Date moved to the header, so the footer no longer repeats it. |
| `partials/article-list/compact.html` | section index row | Shows `Lastmod` (falling back to `Date`) as a bare date — no "Updated" label, since every row in a section index would carry it. |
| `_default/list.html` | section list page | Section card with count, title, description. |

## Client Runtime

All of it is inline in `page/custom-home.html`, under one `<script>`. There is no
bundler, no module system, and no external JS beyond Mermaid from cdnjs.

### `showPopup(type)` / `closePopup()`

```js
function showPopup(type)   // ~30 lines, no per-popup code
function closePopup()
```

Looks up the carrier `.popup-body[data-popup-id="<type>"]` and writes its
`textContent` to `#popup-content.innerHTML`, then shows the modal. Script elements are
raw text, so `textContent` is the authored HTML byte-for-byte with entities
undecoded. If the injected content contains `.mermaid`, `mermaid.init()` is re-run
after a 100ms timeout. (The former 1,174-line `switch` with 51 inline HTML-string
cases is gone.)

Focus is restored on close via a module-scoped `lastTrigger`, captured from
`document.activeElement` at open. Dismissal: click outside (`window.onclick`), or
Escape (`keydown` listener).

**Contract**: the key is a `hugo_docs/data/popups/<key>.yaml` basename. Triggers and
carriers are both generated from that data, so they match by construction. Should a
carrier still be missing, `showPopup` logs `console.error` and does not open the modal
(there is no "Feature details not available" fallback any more).

Key groups: `screener-*` (13), agent/routing/multimodal (11), plus cache, queueing,
resilience, observability and persistence keys.

### `openDiagramTab(id)`

```js
function openDiagramTab(id)
```

Resolves the diagram by **live DOM query** — `[data-diagram-id="<id>"]` — so adding a
diagram requires no edit to this function. Reads the sibling `.diagram-code`
`textContent`, writes `{title, code}` to `localStorage` under
`tuntun:diagram:<id>`, then opens `diagram.html?d=<id>` in a new tab.

Returns silently if the host or `.diagram-code` is absent. `localStorage` failures are
swallowed; the viewer tab renders its own explanation.

**Contract** — markup that must sit next to the button:

```html
<div class="diagram-source" data-diagram-id="<id>"
     data-diagram-title="<title>" hidden>
  <script type="text/plain" class="diagram-code">
graph TD
    ...
  </script>
</div>
```

`type="text/plain"` keeps the browser from executing it; `hidden` keeps Mermaid from
rendering it a second time in place.

Three diagrams are registered: `architecture`, `agents`, `screener`.

### `toggleSection(head)`

Toggles `.expanded` on the enclosing `.disclosure` and its `.disclosure__body`, and
syncs `aria-expanded` on the head. A delegated listener on
`.masthead__nav a[href^="#"]` auto-expands a target section's disclosure on
navigation, so a masthead link never lands on collapsed content.

### `initRail()` (IIFE)

Request-lifecycle rail. On `mouseenter`/`focusin` over a `.rail__node`, moves the
`rail__node--hot` class and writes the node's `data-note` into `.rail__note`. Reverts
to `.rail__node--hot` (or the first node) on `mouseleave` of the flow.

## Data Flow

```
content/_index.md (layout: custom-home, type: page)
  → Hugo lookup → layouts/page/custom-home.html
    → template execution: .Title, .Permalink, .Site.Params.description, absURL
        data/popup_cards/*.yaml + data/popups/*.yaml (hugo.Data)
          → guards G1-G4 + content assertions (errorf fails the build)
          → feature-card triggers + script.popup-body carriers
      → public/index.html (gitignored build output)
        → browser:
            static/style.css              (all presentation)
            cdnjs mermaid 10.6.1          (#architecture renders inline)
            inline <script>               (popup modal, disclosures, rail)
            showPopup(id) → .popup-body[data-popup-id=id].textContent → modal
            openDiagramTab → localStorage → static/diagram.html?d=<id>
```

Documentation pages take a separate path: theme `baseof` → theme partials, with this
package's four overrides substituted by lookup order.

## Dependencies

### Themes
- `hugo-theme-stack` (vendored at `hugo_docs/themes/`) — supplies baseof, article and
  list templates, and the `helper/image` partial the overrides call with
  `partialCached`.

### External (CDN, runtime)
- `mermaid` 10.6.1 via cdnjs — diagram rendering, both on-page and in the viewer tab.
- Google Fonts: Space Grotesk, IBM Plex Sans, IBM Plex Mono.

### Sibling assets (`hugo_docs/static/`)
- `style.css` — every rule the landing page uses. The package ships no inline `<style>`.
- `diagram.html` — standalone viewer; reads `tuntun:diagram:<id>` from `localStorage`
  under the `STORE_PREFIX` constant. The prefix is duplicated in both files and must be
  kept in sync.
- `og-image.png` — link-preview card, generated by `scripts/gen_og_image.py`;
  regenerate after changing the headline or quoted metrics. Must be ≥1200×627 or
  LinkedIn downgrades to the small square card.
- `favicon.png`.

### Data (`hugo_docs/data/`)
- `popup_cards/*.yaml` and `popups/*.yaml` — popup content and card layout, read via
  `hugo.Data`. Generated once by `hugo_docs/scripts/popups_emit.py` (phase 2) and now
  hand-edited as the source of truth.

### Tooling (`hugo_docs/scripts/`)
- `popups_verify.py` — verifies the built page against `popups_baseline.json`
  (51 popups, 10 cards).
- `popups_emit.py check` — re-asserts the data files against the baseline.
- `popups_extract.py` — phase-1 extractor from the old `switch`; historical.

### Config (`hugo_docs/hugo.toml`)
- `params.description` — feeds `<meta name="description">` and `og:description`. Keep
  under ~200 chars; LinkedIn and Slack both truncate past that.
- `baseURL` carries a path (`/agentic/`), which is why `absURL` is used throughout and
  why the theme's own image hook was replaced.

## Reverse Dependencies

- `hugo_docs/content/_index.md` — the sole consumer of `page/custom-home.html`, by
  frontmatter.
- `hugo_docs/content/docs/**` — rendered through the theme, picking up the four partial
  overrides. Generated from the Go repo's `docs/<section>/`; never hand-edited here.
- `hugo_docs/public/**` — build output. Gitignored, produced by CI from source.

## Concurrency

Not applicable. Hugo template execution is build-time; the client runtime is
single-threaded DOM event handling. The only async work is Mermaid's own rendering and
the 100ms `setTimeout` before `mermaid.init()` on freshly-injected popup content.

## Error Handling

Popup data errors are build failures (see guards G1-G4 and the content assertions
under Template Surface). The rest of the client runtime fails silently:

- `showPopup` with an id that has no carrier → `console.error`, modal not opened.
  Unreachable by construction.
- `openDiagramTab` with an unknown id, or markup missing `.diagram-code` → early
  `return`, no tab opens, nothing logged.
- `localStorage.setItem` throwing (private mode, blocked storage) → caught and ignored;
  the tab still opens and the viewer explains itself.
- A typo'd icon `href` (`#ic-…`) renders an empty `<svg>` with no warning.

Consequence: a successful Hugo build proves every popup trigger has a body, but not
that the body reads correctly or that a diagram works; run
`hugo_docs/scripts/popups_verify.py` and check visually.

## Performance

`page/custom-home.html` renders once at build time into a single large `index.html`.
All 51 popup bodies ship as inert `script.popup-body` carriers in the initial payload
whether or not any is opened (the payload is unchanged by the data refactor; only the
template source shrank); all three Mermaid sources ship as hidden text. The page is heavy but
has no runtime fetches — the cost is download size, not latency.

Only the `#architecture` diagram renders Mermaid on page load. The `agents` and
`screener` diagrams defer entirely to the viewer tab, which is the reason for the
hidden-source indirection.

## Usage

### Adding a section

1. Insert `<section id="…">` in `page/custom-home.html` at the right document position
   (section order is literal document order).
2. Lead with `<p class="eyebrow">`, then `<h2>`, then `<p class="lede">`.
3. Add an `<a href="#…">` to `.masthead__nav` if it deserves top-level navigation.
4. Reuse existing CSS classes. Append to `static/style.css` only for genuinely new
   idioms.

### Adding a popup

Create `hugo_docs/data/popups/<key>.yaml` with `card`, `order` (unique within the
card), `label` and `body` (HTML, as a YAML block scalar). The trigger and carrier are
generated; do not touch the template or `showPopup`. A new card is a
`hugo_docs/data/popup_cards/<card-id>.yaml` with `section`, `heading`, `icon`,
`order`, and needs at least one popup or G2 fails the build.

### Adding a diagram

Add the `.diagram-source` block and a `.diagram-open` button calling
`openDiagramTab('<id>')`. **Do not edit `openDiagramTab`** — it resolves by DOM query.

### Gotchas

- **No double curly braces in prose under `hugo_docs/layouts/`.** Hugo parses every
  file there as a Go template, including this README and `todos.md`; a stray pair
  breaks the build.
- **Popup body HTML must not contain a closing script tag** — it would end the carrier
  early. The build guard rejects it.
- The old duplicate `dark-launch` case is resolved: the `#features` trigger is now its
  own popup, `feature-flags`, in card `system-observability`.
- **`content/docs/**` is generated.** Fix prose in the Go repo's `docs/` and run
  `/update-hugo-docs <section> <anchor_dir>`. Frontmatter dates come from the anchor's
  git log. Only `_index.md` and a page `title` belong to this repo.
- **`public/**` is gitignored build output** — never edit, never commit.
- **`/usr/bin/hugo` is too old for the vendored theme**, and `--gc` must never be
  passed. Build locally only with a known-good Hugo.
- The `tuntun:diagram:` localStorage prefix is written here and read in
  `static/diagram.html`. Changing it means changing both.
- `type: "page"` in `content/_index.md` is as load-bearing as `layout:` — dropping it
  silently falls back to the theme's home template.

## Notes

**Documentation Created**: 2026-10-27, following task **P1-HL-A001** (Stock Screener
home-page section).

### Recent Changes

**2026-10-27 — P2-HL-A002** (popup-data-refactor phase 3, "Rewire the template, delete
the switch"):
- The 1,174-line `showPopup` `switch` is deleted; `showPopup` now reads the
  `script.popup-body` carrier for its id.
- Feature-card markup in `#agents`, `#screener` and `#features` and all popup bodies
  are rendered from `hugo_docs/data/popup_cards/` and `hugo_docs/data/popups/` via
  `hugo.Data`.
- Build guards G1-G4 plus content assertions fail the Hugo build on inconsistent data.
- `page/custom-home.html` went from 3,011 to 1,604 lines. Verified with
  `hugo_docs/scripts/popups_verify.py`: 51/51 popups and 10/10 cards PASS.

**2026-10-27 — P1-HL-A001**, purely additive, no existing behaviour changed:
- New `<section id="screener">` ("Multi-Turn Stock Screening") between `#agents` and
  `#features`: eyebrow, `h2`, lede, `.diagram-open` button, a hidden 102-line Mermaid
  source under `data-diagram-id="screener"`, and four feature cards — The Lock,
  Planning a Turn, The Measured API, Shape of the Tool.
- 13 new `showPopup` cases, all `screener-*` prefixed (count went 38 → 51).
- `Screener` masthead link, after `Agents`.
- A `stock_picker` row as the first `<li>` of the Tool catalog's "Screening, Rankings &
  Curated Selections" deflist, its term an `<a href="#screener">`.
- `static/style.css` gained one appended rule block (`.deflist .term a` and `:hover`,
  +18 lines) — the first and only linked `.term` on the page. Styled with the same
  dotted underline the popup triggers use, so the page keeps one "this goes somewhere"
  idiom rather than gaining a second. Scoped to `.deflist .term a` so no other deflist
  row and none of the `#api`-scoped overrides are affected.
- `openDiagramTab` was **not** edited: the new diagram resolves through the existing
  DOM query.
