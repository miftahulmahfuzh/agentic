# Architecture diagrams

## Sub-features

- Three "open in a new tab" buttons on the home page (`button.diagram-open`): `architecture`
  (System Architecture), `agents` (Multi-Agent Routing), `screener` (Stock Screener: one turn).
- `openDiagramTab(id)` puts the hidden `<script type="text/plain" class="diagram-code">` source
  into `localStorage["tuntun:diagram:<id>"]` and opens `diagram.html?d=<id>`.
- `static/diagram.html` waits for the IBM Plex Mono webfont, renders the diagram with mermaid
  10.6.1 into `#stage`, fits it, and offers zoom/fit controls. Without a payload it shows "No
  diagram to show". On a render error it shows "This diagram could not be drawn".

## How to get to it (user POV)

Home page, under System Architecture / Multi-Agent Routing / Stock Screener: click "Complete
architecture diagram" (or the matching button). A new tab opens with a pannable diagram.

## Driving it with verify.sh

```sh
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/diagrams.mjs                # all three
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/diagrams.mjs -- screener    # one
```

End state seen (evidence `02-ui-diagrams.txt`, one screenshot per tab):

```
diagram architecture: {"url":"/agentic/diagram.html?d=architecture","title":"System Architecture","nodes":22,"clusters":7,"empty":null}
diagram agents: {"url":"/agentic/diagram.html?d=agents","title":"Multi-Agent Routing","nodes":22,"clusters":3,"empty":null}
diagram screener: {"url":"/agentic/diagram.html?d=screener","title":"Stock Screener: one turn","nodes":28,"clusters":5,"empty":null}
result: PASS
```

A diagram edit that changes the node count shows up here. Quote the new counts in your evidence.

## Gotchas

- The viewer needs mermaid and the webfont from the CDN. The fence serves them from the cache.
  With `up --offline` the tab cannot draw. That is expected, and it is not this journey.
- The hand-over is `localStorage`, so the viewer opened directly (`page RUN diagram.html`) shows
  the empty state. Drive it from the home page button.
- `window.open(..., "noopener")`: the steps catch the tab through `context.waitForEvent('page')`.
