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

End state seen on the base, e2efe79 (run 1104-091041, evidence `01-ui-offline.txt`). **This is a
product bug, so the journey fails:**

```
typeof mermaid: undefined
pageerror: Cannot access 'lastTrigger' before initialization
popup opens: BROKEN
popup closes by Close button / Escape / backdrop click: BROKEN
disclosure toggles: ok
rail answers hover: BROKEN: node not hot after hover
pageerror: mermaid is not defined (allowed)
masthead link auto-expands #tools: BROKEN: aria-expanded=false
result: FAIL 6 behaviour(s) broken without the CDN
```

Root cause: the inline `<script>` near the end of `hugo_docs/layouts/page/custom-home.html`
starts with an unguarded `mermaid.initialize({...})`. With no mermaid this throws a
ReferenceError, and the rest of the script never runs. `let lastTrigger` stays in its temporal
dead zone, so every `showPopup()` (hoisted, still callable from `onclick`) throws on its first
line. The rail IIFE, `window.onclick`, the Escape listener and the masthead handlers are never
registered. Only `toggleSection` survives, because it is a hoisted function with no `let`
dependency. Fix: guard the call (`if (window.mermaid) mermaid.initialize(...)`) and the
`mermaid.init()` in `showPopup`. After the fix this journey should pass with all seven checks
`ok`.

## Gotchas

- Run it on a run started with `--offline`. On a `cdn-cache` run, mermaid loads and the journey
  proves nothing about the fault. The transcript's `base: ... cdn: offline` line says which mode
  it ran in.
- The steps `allow()` the resource-load failures and `mermaid is not defined`, because those are
  the injected fault. They do not allow `lastTrigger`: that error is the bug.
- Diagrams cannot render offline, by nature. The viewer tab and popup diagrams are out of scope
  here.
