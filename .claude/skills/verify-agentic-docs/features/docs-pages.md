# Documentation pages

## Sub-features

- The docs list (`/agentic/docs/`, 5 sections) and one list per section: architectures (11),
  caller_insights (4), frequently_asked (2), general_go (6), python_stuff (2). These pages are
  rendered by hugo-theme-stack with the repo's overrides (`layouts/_default/list.html`,
  `layouts/partials/article-list/compact.html`, `partials/article/components/*`).
- 25 articles generated from `~/agentic_golang/docs/` (do not hand-edit them, see CLAUDE.md):
  title, reading time, body, code highlighting (dracula).
- ```` ```mermaid ```` blocks: `layouts/partials/head/custom.html` swaps
  `code.language-mermaid` for `div.mermaid` and loads mermaid after the webfonts. It redraws in
  the dark palette when `data-scheme` flips (the theme's `#dark-mode-toggle`). 5 diagrams on 3
  pages: v230_api_versioning_and_dual_agent (3), concurrent_caller (1), rag_stream (1).
- Fallback `og:image` for pages without their own image (same partial).

## How to get to it (user POV)

Masthead "Docs", or `/agentic/docs/`. Pick a section, then an article. The sidebar toggle at the
bottom switches the theme.

## Driving it with verify.sh

```sh
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/docs.mjs        # every docs URL in sitemap.xml
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/docs.mjs -- docs/caller_insights/rag_stream/
$V page RUN docs/general_go/generics/ 60                                    # visible text, no browser
```

End state seen (fresh run 1104-091520-1566285, evidence `04-ui-docs.txt`):

```
pages: 31
list docs/: "Documentation" 5 entries
list docs/architectures/: "Architectures" 10 entries
article docs/architectures/circuit_breaker/: "Circuit Breaker Pattern" 14743 chars, 14 headings, toc 0, 0 diagram(s)
article docs/architectures/v230_api_versioning_and_dual_agent/: "V2.3.0 & the v1/v2 Split" 14514 chars, 11 headings, toc 0, 3 diagram(s)
scheme flip on docs/architectures/v230_api_versioning_and_dual_agent/: {"scheme":"light","fill":"rgb(251, 251, 249)"} -> {"scheme":"dark","fill":"rgb(22, 24, 28)"}
article docs/caller_insights/concurrent_caller/: "Concurrent Caller" 13252 chars, 13 headings, toc 0, 1 diagram(s)
...
result: PASS
```

A content sync (`/update-hugo-docs`) is proven by driving the synced section's pages by path and
by `build`'s link check. The page count in `pages:` changes when a sync adds or removes a doc.

## Gotchas

- The architectures list shows 10 entries on its first page because the theme paginates at 10.
  `docs/architectures/page/2/` holds the 11th.
- `toc 0` everywhere: `params.article.toc = true` in `hugo.toml` has no effect, because the
  theme renders the TOC only as a right-sidebar widget and `params.widgets.page` is empty (theme
  default). The steps log the count and do not assert it. This is a site observation; turning
  the TOC on is a product decision.
- The list pages render the section title (`.section-term`), not the `_index.md` body.
- Docs pages also pull PhotoSwipe and node-vibrant from cdn.jsdelivr.net (theme `data/external.yaml`)
  and Lato from Google Fonts. The fence caches them. Under `--offline` these pages lose those
  extras and mermaid, but they have no inline-script crash like the home page.
