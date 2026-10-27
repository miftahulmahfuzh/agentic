# Package: layouts

**Location**: `hugo_docs/layouts`
**Last Updated**: 2026-10-27

## Overview

Hugo template package for the Tuntun Go Agentic Chatbot documentation site. It owns
exactly two things: the standalone landing page (`page/custom-home.html`, a
self-contained 3,000-line document that becomes the deployed `index.html`), and a
small set of partial overrides that bend the vendored `hugo-theme-stack` where its
defaults were wrong for this site.

This package is **authored**, unlike its sibling `hugo_docs/content/docs/`, which is
generated from the Go repo. Edits to the landing page are made here and nowhere else.

**Key Responsibilities:**
- Render the landing page — the canonical, highest-signal description of what the
  chatbot system is and how it behaves.
- Carry the page's entire client runtime inline: section disclosures, the popup
  registry, and the hand-off to the standalone Mermaid diagram viewer.
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
`.Site.Params.description`, and `absURL` for `style.css`, `favicon.png`,
`og-image.png`, `diagram.html`.

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
function showPopup(type)   // one switch, 51 cases
function closePopup()
```

A single `switch (type)` assigns an HTML string to `popupContent`, which is written to
`#popup-content.innerHTML` and the modal shown. If the injected content contains
`.mermaid`, `mermaid.init()` is re-run after a 100ms timeout.

Focus is restored on close via a module-scoped `lastTrigger`, captured from
`document.activeElement` at open. Dismissal: click outside (`window.onclick`), or
Escape (`keydown` listener).

**Contract**: a trigger is `<button class="popup-trigger" type="button"
onclick="showPopup('<key>')">`. The key must match a `case` label. An unmatched key
falls through to `default`, which renders "Feature details not available" — a silent
failure with no console warning.

Key groups: `screener-*` (13), `agent-*`/routing/multimodal (11), plus cache,
queueing, resilience, observability and persistence keys.

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
      → public/index.html (gitignored build output)
        → browser:
            static/style.css              (all presentation)
            cdnjs mermaid 10.6.1          (#architecture renders inline)
            inline <script>               (popups, disclosures, rail)
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

There is no error surface — failures are silent by design:

- `showPopup` with an unknown key → `default` case, "Feature details not available".
- `openDiagramTab` with an unknown id, or markup missing `.diagram-code` → early
  `return`, no tab opens, nothing logged.
- `localStorage.setItem` throwing (private mode, blocked storage) → caught and ignored;
  the tab still opens and the viewer explains itself.
- A typo'd icon `href` (`#ic-…`) renders an empty `<svg>` with no warning.

Consequence: verification is visual. A Hugo build succeeding proves nothing about
whether a popup or diagram actually works.

## Performance

`page/custom-home.html` renders once at build time into a single ~3,000-line
`index.html`. All 51 popups ship as string literals in the initial payload whether or
not any is opened; all three Mermaid sources ship as hidden text. The page is heavy but
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

Add a `case "<key>":` to the `showPopup` switch, and a matching
`<button class="popup-trigger" onclick="showPopup('<key>')">`. Nothing else is wired —
there is no registry to update.

### Adding a diagram

Add the `.diagram-source` block and a `.diagram-open` button calling
`openDiagramTab('<id>')`. **Do not edit `openDiagramTab`** — it resolves by DOM query.

### Gotchas

- **`showPopup` has a duplicate `case "dark-launch"`** (lines ~1754 and ~2885). JS
  switch takes the first match, so the second block is unreachable dead code. Both
  triggers (in `#agents` and `#features`) render the first. Pre-existing; noted so an
  editor does not "fix" the live copy and leave the dead one.
- **51 cases, 51 triggers** — the counts match today, but nothing enforces it. An
  orphaned case is invisible; an orphaned trigger degrades silently to the `default`.
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
