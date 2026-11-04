---
name: verify-agentic-docs
description: Prove a change to the agentic docs site (the Hugo site under hugo_docs/ for the Tuntun Go agentic chatbot) in a real browser and a real production build, with evidence. Use after editing the home page template, popup data, style.css, static/diagram.html, theme overrides or docs content, and whenever a plan's Proof section names verify-agentic-docs. Every run serves its own snapshot of hugo_docs/ on its own loopback port. It never deploys, pushes, runs workflows, writes tracked files, or touches the owner's hugo server on :1313.
---

# verify-agentic-docs

This repo is a static site. "The app" is `hugo_docs/` rendered by Hugo: a hand-built home page
(`layouts/page/custom-home.html` plus 51 popups in `data/popups/*.yaml`), a standalone diagram
viewer (`static/diagram.html`), and the Stack theme's docs pages (`content/docs/**`). A user reads
it in a browser. So a run is a `hugo server` serving a per-run snapshot of the working tree, a
fenced headless Chromium that drives it, and a production build that runs the repo's own popup
harness and an internal link check.

The lever is one script. Never hand-write a `hugo server` line.

```sh
V=.claude/skills/verify-agentic-docs/scripts/verify.sh   # from the repo root (any worktree)
```

## Launch

```sh
$V up                 # prints RUN=, URL=http://localhost:PORT/agentic/, EVIDENCE=, MODE=cdn-cache
$V up --offline       # same, but the browser refuses the public CDNs (fault injection, see Gotchas)
$V up --port 24000    # pick the port yourself (refused if it is 1313 or taken)
```

`up` snapshots `hugo_docs/` from the **working tree**, so uncommitted edits count. It copies with
rsync into `$VERIFY_HOME/<run>/site`, minus `public/` and other generated files. It starts
`~/bin/hugo server` (needs >= 0.164) from that snapshot on a random free port in 20000-29999. It
returns only when the home page answers 200 with its `#architecture` section and `docs/` answers
200. If the first build fails, Hugo exits, and `up` prints the log tail and the template error and
fails. That is how a broken template shows up. The first `up` on a machine installs
`playwright@1.62.1` into `$VERIFY_HOME/.tools` (it uses the chromium-1234 already in
`~/.cache/ms-playwright`).

**Edited something after `up`?** Run `$V sync RUN`. It re-snapshots the working tree, waits for
Hugo's rebuild, and fails with Hugo's error if the rebuild failed (the server keeps serving the
last good build). A `sync` costs about 50 ms. Use it between edits instead of `down` + `up`.

## Doctor

Run `$V doctor RUN` before the first drive and after any surprise. It is read-only. Every line
starts with ok / FAIL / WARN / info:

- `process` / `port`: the run's process group is alive and owns its port (checked by process
  group, not by name).
- `site`: home and `docs/` answer 200.
- `code WARN ... stale snapshot`: you edited `hugo_docs/` since `up`/`sync`. Run `sync`.
- `build FAIL`: the latest rebuild failed, so the server is serving the build before it. Fix it,
  then `sync`.
- `owner info`: who holds :1313. Only reported. Never touched.
- `egress`: the run's environment refuses github.com through the dead proxy, and no template calls
  `GetRemote`/`getJSON` (so Hugo has no reason to go online).
- `cdn info`: how many CDN responses are cached for the browser (see the fence below).

## Drive

| Command | What it does | Evidence |
|---|---|---|
| `$V page RUN PATH [MAX_LINES]` | GET a URL. PATH is relative to `/agentic/` (`''` = home, `docs/general_go/generics/`, `sitemap.xml`), or absolute from the origin (`/agentic/nope/`) | `NN-page-*.txt` holds the status, the content type and the **visible text** with `[aria-labels]`. The full HTML sits beside it as `.html`. Binaries go to `.bin` with size + sha256 |
| `$V ui RUN STEPS.mjs [-- ARGS]` | Fenced headless Chromium (1400x900, Asia/Jakarta, no permissions, service workers blocked) runs a steps module | `NN-ui-*.txt` transcript, screenshots, `.webm` video. **FAILS on any console error, page error or blocked request** the steps did not `allow()` |
| `$V build RUN` | Production build of the snapshot (`hugo --minify`, `HUGO_ENVIRONMENT=production`, as `deploy.yml` does, minus `--gc`), then `scripts/popups_verify.py`, `scripts/popups_emit.py check` and `links.py` | `NN-build-production.txt` with each tool's output and exit code. Exits 1 if any of them fails |
| `$V sync RUN` | Re-snapshot plus rebuild (see Launch) | a line in `LOG.md` |
| `$V note RUN "text"` | Append to `evidence/LOG.md`, the summary of what you proved | |

Steps modules export `async ({ page, context, base, shot, log, args, allow }) => {}`. `base` ends
in `/agentic/`. `shot(name, tab?)` screenshots `page` or another tab. `allow(/re/)` marks an
expected console error or blocked request. The repo's own journeys are in `features/steps/`.
Examples, one per surface:

```sh
$V ui RUN .claude/skills/verify-agentic-docs/features/steps/popups.mjs -- cache-fastlane circuit-breakers
$V page RUN docs/architectures/circuit_breaker/ 40
$V build RUN
```

A minimal steps file of your own (write it in the scratchpad, not the repo):

```js
export default async ({ page, base, shot, log }) => {
  await page.goto(base, { waitUntil: 'networkidle' })
  await page.locator(`button.popup-trigger[onclick="showPopup('janitors')"]`).click()
  await page.locator('#popup-modal').waitFor({ state: 'visible' })
  log(await page.locator('#popup-content h2').textContent())
  await shot('janitors')
}
```

Stable handles: `button.popup-trigger[onclick="showPopup('<id>')"]` (id = the YAML file name),
`#popup-modal`, `#popup-content`, the `Close` button, `.popup-body[data-popup-id]`,
`button.diagram-open[onclick="openDiagramTab('<id>')"]`, `.disclosure__head`, `.rail__node`, the
`Primary` navigation, and on docs pages `.article-title`, `.article-content`, `.mermaid`,
`#dark-mode-toggle`.

**The browser fence** (`scripts/ui.mjs`, applied to every tab in the context):

- The run's own origin passes.
- GETs to `cdnjs.cloudflare.com`, `fonts.googleapis.com`, `fonts.gstatic.com` and
  `cdn.jsdelivr.net` are fetched once and cached in `$VERIFY_HOME/.cdn-cache`. Later runs get the
  cached copy and never go online for them. These carry mermaid 10.6.1, the webfonts, and the
  theme's PhotoSwipe/Vibrant. With `--offline` they are aborted instead.
- Everything else is aborted and logged as `blocked:` and fails the drive. That covers the
  owner's :1313, GitHub, and every outbound link a step might click.

## Evidence

Evidence goes to `~/.local/state/agentic-docs-verify/<run>/evidence/`. It is outside the repo and
survives `down` and worktree deletion. Files are numbered in drive order. `down` copies
`server.log` in.

- Use the real reader path: the rendered page in a browser, or the built HTML. Never assert on
  YAML or the template source when the page can be read.
- Capture the action and the state after it. For a popup that means the modal visible, the
  content equal to its carrier, and focus back on the trigger. For a template change, the
  production build as well as the dev server: `--minify` and `HUGO_ENVIRONMENT=production` are
  what ships.
- For a bug fix, show the failure first: drive the base (`git stash`, `sync`), then the fix
  (`git stash pop`, `sync`), on the same run. Keep both transcripts.
- A step that could not be driven is `inconclusive`, with the reason. Never weaken a journey to
  make it pass.
- `note` what each drive proved.

## Cleanup

`$V down RUN` (or `$V down --all`) kills the run's process group, waits until it is gone, copies
the server log into evidence, and deletes the snapshot, the cache, the build and HOME. Evidence
stays. `$V ls` lists runs with state, CDN mode and evidence count.

## Feature map

`features/README.md` indexes one file per reader-facing feature, each with proven recipes and the
end states they produced. A change that alters what a reader sees updates its feature entry in the
same change.

## Gotchas

- **Never driven, no flag turns it on.** `git push` and commits (a push to `main` runs
  `.github/workflows/deploy.yml` and **publishes the live site** at
  miftahulmahfuzh.github.io/agentic). `workflow_dispatch` of that workflow. Any GitHub Pages
  call. `sync_docs.py`, `scripts/sync_anchor_docs.py` and `/update-hugo-docs` (they rewrite tracked
  `content/docs/` from `~/agentic_golang`). `scripts/gen_og_image.py` (it overwrites the tracked
  `static/og-image.png` and fetches fonts). `popups_emit.py emit` and `popups_extract.py` (they
  rewrite the data tree and the frozen baseline). `hugo --gc` (it deletes the committed
  `resources/_gen/`). `verify.sh` runs only `popups_verify.py` (in the snapshot) and
  `popups_emit.py check`. Both are read-only.
- **This site has no paid or messaging dependency.** No LLM, no data API, no database, no
  email/chat bot. `generativelanguage.googleapis.com` in `data/popups/consul-discovery.yaml` is
  prose, not a call. So there is no budget and no `--real` flag. If one ever appears (a search
  API, an analytics beacon), classify it before driving.
- **The owner's port is 1313 and is never ours.** CLAUDE.md pins no port, so Hugo's default
  `hugo server` port is treated as the owner's (their memory notes say they preview at
  `localhost:1313/agentic/`). The picker skips it, `--port 1313` is refused, `up` never stops or
  reuses whatever holds it, `doctor` only reports the holder, and the fence aborts browser requests
  to it. Runs live on 20000-29999 and are tracked by process group.
- **Nothing is written into the checkout.** Hugo runs only inside the snapshot, with
  `--renderToMemory --noBuildLock` and the run's own `--cacheDir`. A `hugo server` in the real
  `hugo_docs/` would rewrite the tracked `assets/jsconfig.json` and the `resources/_gen` mtimes
  (seen in the snapshot). That is why `sync`, `doctor` and the tree hash ignore those paths.
  `popups_verify.py` builds with `cwd` = its own `hugo_docs`, so it is run from the snapshot copy
  with `TMPDIR` under the run.
- **`popups_verify.py --index` cannot read a minified page.** Fed the `--minify` build it reports
  all 51 popups MISSING. `build` lets it do its own unminified build of the snapshot instead.
- **Every file under `layouts/` is parsed as a template**, including
  `layouts/.workflows/*.md`. A plan with `{{ ... }}` in it there breaks `up`, `sync` and CI the
  same way. Read the error's path before blaming the template you edited.
- **Egress is best effort.** Hugo and Python get a dead `HTTP(S)_PROXY`/`ALL_PROXY` with a
  loopback-only `NO_PROXY`. The browser is fenced by Playwright routing. WebSockets are not routed
  (live reload is off, and the site opens none). A raw socket from a native tool would slip past.
  The `ui` node process itself has no proxy, because `route.fetch()` fills the CDN cache.
- **The CDN cache is shared across runs** (`$VERIFY_HOME/.cdn-cache`). That is fine because those
  URLs are version-pinned. To refetch, delete the directory.
- **`docs/` list pages do not render `_index.md` bodies**, only the title. Assert a section's
  copy through its title.
- **Smooth scrolling.** `style.css` sets `scroll-behavior: smooth`, so after a masthead click,
  wait for the section's position to settle, not for `location.hash`.
- **Known on the base:** `build` exits 1 on 16 broken links in
  `docs/architectures/circuit_breaker/` (see production-build.md). Compare counts against that
  before calling a failure yours.
- **Name clash.** `~/agentic_golang` has its own `verify-agentic` skill and owns
  `~/.local/state/agentic-verify`. This one is `verify-agentic-docs`, state in
  `~/.local/state/agentic-docs-verify`. Do not mix their scripts.
- The Bash tool's shell is zsh: quote any URL or path argument containing `?` or `*`.
