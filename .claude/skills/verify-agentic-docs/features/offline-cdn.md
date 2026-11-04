# Home page without the CDN (fault injection)

## Sub-features

- The home page loads mermaid 10.6.1 from cdnjs and its webfonts from Google Fonts. A reader on a
  network that blocks either (a corporate proxy, a strict firewall, a CDN outage) gets the page
  without them.
- What must survive that, since none of it draws a diagram: popups opening and closing, the
  disclosures, the request rail, and the masthead's auto-expand.

## How to get to it (user POV)

Open the home page with cdnjs.cloudflare.com unreachable.

## Driving it with verify.sh

```sh
$V up --offline        # MODE=cdn-offline: the fence aborts the four CDN hosts
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/offline.mjs
```

End state before the fix (base 1c061f1, runs 1104-091041 and 1104-092151, evidence
`01-ui-offline.txt`):

```
pageerror: Cannot access 'lastTrigger' before initialization
popup opens: BROKEN
popup closes by Close button / Escape / backdrop click: BROKEN
disclosure toggles: ok
rail answers hover: BROKEN: node not hot after hover
masthead link auto-expands #tools: BROKEN: aria-expanded=false
result: FAIL 6 behaviour(s) broken without the CDN
```

Cause: the inline `<script>` at the end of `hugo_docs/layouts/page/custom-home.html` began with
an unguarded `mermaid.initialize({...})`. With no mermaid it threw a ReferenceError and the rest
of the script never ran. `let lastTrigger` stayed in its temporal dead zone, so every hoisted
`showPopup()` threw, and the rail, backdrop, Escape and masthead handlers were never registered.

End state after the fix (both mermaid calls guarded with `window.mermaid`; same run 1104-092151,
after `sync`, evidence `02-ui-offline.txt`):

```
popup opens: ok
popup closes by Close button: ok
popup closes by Escape: ok
popup closes by backdrop click: ok
disclosure toggles: ok
rail answers hover: ok
masthead link auto-expands #tools: ok
result: PASS
```

## Gotchas

- Run it on a run started with `--offline`. On a `cdn-cache` run, mermaid loads and the journey
  proves nothing about the fault. The transcript's `base: ... cdn: offline` line says which mode
  it ran in.
- The steps `allow()` the resource-load failures and `mermaid is not defined`, because those are
  the injected fault. They do not allow `lastTrigger`: that error is the bug.
- Diagrams cannot render offline, by nature. A popup with a diagram opens and shows the
  diagram's source text instead, so `popups.mjs` (which waits for every popup diagram's `<svg>`)
  times out on such a popup under `--offline`. Drive `popups.mjs` on a `cdn-cache` run only.
