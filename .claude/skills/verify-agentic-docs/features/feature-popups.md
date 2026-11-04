# Feature popups

## Sub-features

- 51 trigger buttons in 10 cards across three sections (agents, screener, features). Each is
  built from one `hugo_docs/data/popups/<id>.yaml` (`card`, `order`, `label`, `body`), and the
  cards come from `data/popup_cards/*.yaml`.
- Each body ships as an inert `<script type="text/html" class="popup-body" data-popup-id>`.
  `showPopup(id)` copies it into `#popup-content` and shows `#popup-modal`. 13 bodies contain a
  `.mermaid` diagram, which `mermaid.init()` draws after 100 ms.
- Closing: the Close button, Escape, or a click on the backdrop. Focus returns to the trigger.
- Build-time guards G1-G4 in the template (unknown card, orphan card, order collision, unknown
  section) fail the build. `popups_verify.py` checks the rendered bodies and triggers against
  the frozen `popups_baseline.json` (decision D1 adds `feature-flags`).

## How to get to it (user POV)

Home page, Agents / Screener / Core Engineering sections: click any bullet in a card. A modal
opens with the explanation. Escape closes it.

## Driving it with verify.sh

```sh
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/popups.mjs                    # all 51
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/popups.mjs -- janitors bowl-resume
$V build RUN                                                                              # popups_verify + emit check
```

End state seen (evidence `03-ui-popups.txt`):

```
triggers: 51 on the page, driving 51
popup agent-roster | card "Multi-Agent System" | "Agent Roster & Personas" | 1469 chars | 0 diagram(s) | closed by button
popup server-owned-routing | card "Multi-Agent System" | "Server-Owned Routing" | 4899 chars | 1 diagram(s) | closed by escape
...
popup feature-flags | card "System Observability" | "Dark-Launch Feature Flags" | 2342 chars | 0 diagram(s) | closed by backdrop
popups: 51 opened, rendered and closed
result: PASS
```

and from `build`:

```
property (a) -- popup bodies, 51 expected
  -> PASS 51  FAIL 0  MISSING 0  EXTRA 0
OK  (0 failures)
checked 10 cards + 51 popups; failures: 0
```

**A new popup** (one new YAML file) shows up as `triggers: 52`. Drive it by id.
`popups_verify.py` then reports `EXTRA <id>` and exits 1, and so does `build`, because the
baseline froze the refactor's 51 bodies and counts an extra id as a failure. Expect exactly that
one EXTRA line (property (b) will also differ for its card). Quote it in the evidence. Do not
edit the frozen baseline to make it pass; `popups_emit.py check` is the check that still has to
be green.

## Gotchas

- Close methods are cycled per popup (button, Escape, backdrop), so each method is exercised
  about 17 times. A single-id drive uses only the Close button.
- The content check compares `#popup-content` with a parse of the carrier (element count plus
  the first 200 characters of text). Mermaid replaces `.mermaid` text with an SVG, which is why
  the check is not a byte comparison.
- `popups_emit.py check` prints one `note:` (label != `<h2>` for screener-content-is-routing).
  It is informational, and it is on the base.
- Without the mermaid CDN, popups still open and close (see [offline-cdn.md](offline-cdn.md)),
  but their diagrams stay as source text, so drive this journey on a `cdn-cache` run.
