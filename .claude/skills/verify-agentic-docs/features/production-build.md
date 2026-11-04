# Production build, popup harness, link check

## Sub-features

- What ships: CI (`.github/workflows/deploy.yml`) runs `hugo --gc --minify` with
  `HUGO_ENVIRONMENT=production` on every push to main. `build` reproduces that from the run's
  snapshot, minus `--gc`, with the run's baseURL.
- Template guards in `custom-home.html` (G1-G4, missing fields, a `</script>` inside a body) fail
  that build.
- `scripts/popups_verify.py`: rendered popups vs `popups_baseline.json`, in its own unminified
  build of the snapshot.
- `scripts/popups_emit.py check`: the data tree vs the baseline, plus referential integrity.
- `links.py` (this skill): every internal `href`/`src` in the build resolves to a file, and every
  `#fragment` matches an id on its target page. External links are listed by host and never
  fetched.

## How to get to it (user POV)

A reader never sees the build. They see its result at miftahulmahfuzh.github.io/agentic after a
push. This is the gate before that push.

## Driving it with verify.sh

```sh
$V build RUN          # exit 0 only if all four sections pass
```

End state seen on the base, e2efe79 (evidence `09-build-production.txt` and the re-run on the
fresh run, see the report):

```
### hugo --minify ...  Pages 45 ... exit 0
### popups_verify.py ...  -> PASS 51  FAIL 0  MISSING 0  EXTRA 0   OK (0 failures)  exit 0
### popups_emit.py check  checked 10 cards + 51 popups; failures: 0  exit 0
### links.py
pages       45
internal    431 links/assets checked
broken      16
  docs/architectures/circuit_breaker/index.html: <a href='../../core/services.go'> -> /agentic/docs/core/services.go (no file)
  ... (6x core/services.go, 4x core/model.go, 3x db/redis.go, 2x db/arango.go, 1x tools/toolnonbe/equity_research.go)
anchors     0 missing
exit 1
build FAILED
```

So on the base, `build` fails on links alone. A change is clean when it leaves the hugo,
popups_verify and emit sections green and does not raise `broken` above 16 or `anchors` above 0.

To prove a guard fires, break it in the working tree, then `sync` (and `build`), then revert and
`sync` again:

```sh
echo '{{ .Broken ' >> hugo_docs/layouts/_default/list.html
$V sync RUN     # -> ERROR Rebuild failed: ... unclosed action started at list.html:92 ; exit 1
git checkout -- hugo_docs/layouts/_default/list.html
$V sync RUN     # -> verify: rebuilt (Total in 18 ms) ; exit 0
```

## Gotchas

- The 16 dead links come from the Go repo's `docs/architectures/circuit_breaker.md`, which links
  Go source files relatively (`../../core/services.go`). `scripts/sync_anchor_docs.py` already
  flags them as "source file, no page on this site to point at" and still copies them
  unchanged, so they 404 on the live site. The fix belongs in `~/agentic_golang/docs/` (or as a
  rewrite rule in the sync), never in `content/docs/` here.
- Never add `--gc`: it deletes the committed `resources/_gen/` (in the real tree; in the snapshot
  it would only hide that problem).
- `popups_verify.py --index` on the minified build reports all 51 MISSING. `build` does not use
  `--index`, for that reason.
