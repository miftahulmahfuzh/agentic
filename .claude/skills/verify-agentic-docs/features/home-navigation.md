# Home page navigation

## Sub-features

- Masthead (`nav[aria-label=Primary]`): Architecture, Agents, Screener, Tools and API jump to
  their sections. Tools and API land on a collapsed disclosure, which the click expands
  (`custom-home.html`, masthead auto-expand handler). Docs (a relative `docs/` link) opens the docs
  list.
- Six disclosures (`.disclosure__head`): Tool catalog, Endpoint reference, Install & run,
  Annotated .env, Test suites & how to run them, Project structure & extending. All collapsed on
  load, toggled by click, `aria-expanded` kept in sync.
- The request-lifecycle rail in the hero (`.rail__node`, 4 nodes). Hover or focus makes a node
  hot and swaps `.rail__note` to its `data-note`.
- The hero copy and the stat strip (50 concurrent requests, 5 LLM stream workers, ...).

## How to get to it (user POV)

Open the site root. The masthead sits at the top, the rail is in the hero, and the disclosures
sit under Tools, API, Installation, Configuration, Usage and Development further down.

## Driving it with verify.sh

```sh
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/sections.mjs
```

End state seen (run 1104-090515, evidence `05-ui-sections.txt`):

```
masthead Architecture -> #architecture: {"top":72,"inView":true,"expanded":null}
masthead Tools -> #tools: {"top":72,"inView":true,"expanded":"true"}
masthead API -> #api: {"top":72,"inView":true,"expanded":"true"}
disclosure "Tool catalog": open {"aria":"true","cls":"disclosure__body expanded","h":3422.7} shut {"aria":"false","h":0}
... 6 disclosures toggled
rail node 0 "Entry Admission authz · limits · cache k": hot=true note-matches=true   (x4)
docs link -> /agentic/docs/ "Documentation"
result: PASS
```

`top: 72` is the `scroll-margin-top` under the fixed masthead. A different value means the
masthead height or the margin changed.

Text-only check of the copy, with no browser:

```sh
$V page RUN '' 80        # visible text: masthead, hero, stats, rail labels, section headings
```

## Gotchas

- `scroll-behavior: smooth`: the steps wait for the section's position to settle, not for the
  hash. Removing that wait makes the first anchor read `inView: false`.
- On a fresh load every disclosure must start collapsed. The steps reload before toggling, because
  the masthead pass leaves Tools and API open.
- None of this works when the mermaid CDN is unreachable, except the disclosures. See
  [offline-cdn.md](offline-cdn.md).
