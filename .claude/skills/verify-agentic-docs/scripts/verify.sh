#!/usr/bin/env bash
# verify.sh: launch, drive and tear down a throwaway Hugo server for the agentic docs site.
#
# Every run serves its own snapshot of hugo_docs/ (rsync of the working tree, so uncommitted edits
# count) on its own loopback port, with its own HOME and Hugo cache. Nothing is written into the
# checkout, nothing is built into hugo_docs/public/, and nothing is deployed or pushed. The owner's
# `hugo server` on :1313 is never used, stopped or reused. Evidence lives under
# $VERIFY_HOME/<run>/evidence and survives `down`.
#
#   verify.sh up [--offline] [--port N]  start a server from the current checkout; prints RUN= URL= EVIDENCE=
#                                        --offline: the browser refuses the public CDNs (mermaid, fonts)
#   verify.sh doctor RUN                 is this run worth driving? (read-only)
#   verify.sh sync RUN                   re-snapshot the working tree into the run; waits for the rebuild
#   verify.sh page RUN PATH [MAX_LINES]  GET a page (PATH relative to /agentic/, or /absolute); html + visible text saved
#   verify.sh ui RUN STEPS.mjs [-- ARGS] drive the site in a fenced headless Chromium (video + screenshots)
#   verify.sh build RUN                  production build of the snapshot + popup checks + internal link check
#   verify.sh note RUN "TEXT"            append a line to the run's evidence log (what you proved)
#   verify.sh down RUN|--all             stop what `up` started, drop run state; evidence stays
#   verify.sh ls                         runs with state, port, mode and evidence count
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VERIFY_HOME="${VERIFY_HOME:-$HOME/.local/state/agentic-docs-verify}"
TOOLS="$VERIFY_HOME/.tools"
CDN_CACHE="$VERIFY_HOME/.cdn-cache"
HUGO_BIN="${VERIFY_HUGO:-$HOME/bin/hugo}"
HUGO_MIN=0.164.0
OWNER_PORT=1313          # `hugo server`'s default: the owner's dev server. Never ours.
PLAYWRIGHT_VERSION=1.62.1
DEAD_PROXY=http://127.0.0.1:9
PY="$(command -v python3 || true)"
NODE="$(command -v node || true)"

die() { echo "verify: $*" >&2; exit 1; }

repo_root() {
  local r
  r="$(git rev-parse --show-toplevel 2>/dev/null)" || die "run from inside an agentic (docs) checkout"
  [ -f "$r/hugo_docs/hugo.toml" ] || die "$r has no hugo_docs/hugo.toml; not the agentic docs repo"
  echo "$r"
}

run_dir() {
  local run=${1:-}
  [ -n "$run" ] || die "missing RUN id (see: verify.sh ls)"
  [ -d "$VERIFY_HOME/$run" ] || die "no run $run under $VERIFY_HOME"
  echo "$VERIFY_HOME/$run"
}

meta() { sed -n "s/^$2=//p" "$1/meta" | tail -1; }

# Numbered evidence: evidence/NN-<kind>-<slug>.txt; 00- files (written by up) are not counted.
next_evidence() {
  local dir=$1/evidence kind=$2 slug=$3 n
  n=$(find "$dir" -maxdepth 1 -type f -name '[0-9][0-9]-*.txt' ! -name '00-*' | wc -l)
  printf '%s/%02d-%s-%s.txt' "$dir" $((n + 1)) "$kind" "$(printf %s "$slug" | tr -c 'a-zA-Z0-9_.-' '_' | cut -c1-48)"
}

# Content hash of the source the snapshot copies. resources/, public/ and assets/jsconfig.json are
# excluded: any `hugo server` (the owner's, or ours inside the snapshot) rewrites them, and that is
# not a source change. Hugo regenerates jsconfig.json on start, so the snapshot never copies it.
tree_hash() {
  (cd "$1/hugo_docs" && find . \( -path ./public -o -path ./resources -o -path ./scripts/.fontcache \
    -o -name .hugo_build.lock -o -path ./assets/jsconfig.json \) -prune -o -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum | sha256sum | cut -c1-16)
}

snapshot() {
  rsync -a --checksum --delete --itemize-changes \
    --exclude /public/ --exclude /scripts/.fontcache/ --exclude /.hugo_build.lock --exclude /assets/jsconfig.json --exclude __pycache__/ \
    "$1/hugo_docs/" "$2/site/"
}

# The environment of every process the run owns: nothing from the caller's shell, a per-run HOME,
# and a dead proxy so Go's net/http (hugo) and Python refuse anything that is not loopback.
run_env() {
  local dir=$1
  echo env -i \
    PATH="$(dirname "$HUGO_BIN"):$(dirname "$PY"):$(dirname "$NODE"):/usr/bin:/bin" \
    HOME="$dir/home" LANG=C.UTF-8 TZ=Asia/Jakarta \
    HTTP_PROXY=$DEAD_PROXY HTTPS_PROXY=$DEAD_PROXY ALL_PROXY=$DEAD_PROXY \
    http_proxy=$DEAD_PROXY https_proxy=$DEAD_PROXY all_proxy=$DEAD_PROXY \
    NO_PROXY=localhost,127.0.0.1 no_proxy=localhost,127.0.0.1 \
    HUGO_CACHEDIR="$dir/cache"
}

port_free() { [ -z "$(ss -ltnH "sport = :$1" 2>/dev/null)" ]; }

pick_port() {
  local p
  for _ in $(seq 1 50); do
    p=$((20000 + RANDOM % 10000))
    [ "$p" = "$OWNER_PORT" ] && continue
    port_free "$p" && { echo "$p"; return 0; }
  done
  die "no free port found in 20000-29999"
}

port_holder() { { ss -ltnpH "sport = :$1" 2>/dev/null | grep -oE 'pid=[0-9]+' || true; } | sed -n '1s/pid=//p'; }

hugo_version_ok() {
  local v
  v="$("$HUGO_BIN" version 2>/dev/null | grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' | head -1 | tr -d v)" || return 1
  [ -n "$v" ] && [ "$(printf '%s\n%s\n' "$HUGO_MIN" "$v" | sort -V | head -1)" = "$HUGO_MIN" ] && echo "$v"
}

ensure_tools() {
  [ -f "$TOOLS/node_modules/playwright/package.json" ] && return 0
  [ -n "$NODE" ] || die "node is not on PATH"
  echo "verify: installing playwright@$PLAYWRIGHT_VERSION into $TOOLS (once)" >&2
  mkdir -p "$TOOLS"
  [ -f "$TOOLS/package.json" ] || echo '{"name":"agentic-docs-verify-tools","private":true}' >"$TOOLS/package.json"
  (cd "$TOOLS" && npm install --no-audit --no-fund --save-exact "playwright@$PLAYWRIGHT_VERSION" >"$TOOLS/install.log" 2>&1) \
    || die "playwright install failed (see $TOOLS/install.log)"
}

cmd_up() {
  local offline=0 port=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --offline) offline=1 ;;
      --port) port=${2:?--port N}; shift ;;
      *) die "up: unknown flag $1" ;;
    esac
    shift
  done
  local root hv run dir base
  root="$(repo_root)"
  [ -n "$PY" ] || die "python3 is not on PATH"
  hv="$(hugo_version_ok)" || die "$HUGO_BIN is missing or older than $HUGO_MIN (the Stack theme needs it; /usr/bin/hugo 0.123 cannot render it). Set VERIFY_HUGO."
  ensure_tools
  if [ -n "$port" ]; then
    [ "$port" != "$OWNER_PORT" ] || die "port $OWNER_PORT is the owner's hugo server; pick another (or omit --port)"
    port_free "$port" || die "port $port is in use (pid $(port_holder "$port"))"
  else
    port="$(pick_port)"
  fi

  run="$(date +%m%d-%H%M%S)-$$"
  dir="$VERIFY_HOME/$run"
  base="http://localhost:$port/agentic/"
  mkdir -p "$dir/evidence" "$dir/site" "$dir/home" "$dir/cache"
  snapshot "$root" "$dir" >/dev/null
  {
    echo "repo=$root"
    echo "head=$(git -C "$root" rev-parse --short HEAD)"
    echo "dirty=$(git -C "$root" status --porcelain -- hugo_docs | wc -l)"
    echo "tree=$(tree_hash "$root")"
    echo "port=$port"
    echo "url=$base"
    echo "cdn=$([ "$offline" = 1 ] && echo offline || echo cache)"
    echo "hugo=$hv"
  } >"$dir/meta"

  # setsid makes hugo the leader of its own process group, so `down` kills exactly this tree; every
  # fd is redirected so no caller's pipe stays open behind it. --renderToMemory keeps
  # output out of the snapshot's public/, --noBuildLock keeps .hugo_build.lock out of it.
  # shellcheck disable=SC2046
  setsid $(run_env "$dir") HUGO_ENVIRONMENT=development "$HUGO_BIN" server \
    --source "$dir/site" --cacheDir "$dir/cache" \
    --bind 127.0.0.1 --port "$port" --baseURL "$base" --appendPort=false \
    --disableLiveReload --disableFastRender --renderToMemory --noBuildLock \
    </dev/null >"$dir/server.log" 2>&1 &
  echo $! >"$dir/pgid"

  # Usable = the home page answers 200 with its architecture section and a docs page answers 200.
  # Hugo exits on a failed first build, so a dead process is "broken", not "not up yet".
  local code="" ok=0
  for _ in $(seq 1 120); do
    if ! kill -0 "$(cat "$dir/pgid")" 2>/dev/null; then
      tail -25 "$dir/server.log" >&2
      die "hugo exited during startup: a broken build or a bad flag (log above; verify.sh down $run)"
    fi
    code="$(curl -s -o "$dir/ready.html" -w '%{http_code}' -m 5 "$base" || true)"
    if [ "$code" = 200 ] && grep -q 'id="architecture"' "$dir/ready.html" \
      && [ "$(curl -s -o /dev/null -w '%{http_code}' -m 5 "${base}docs/" || true)" = 200 ]; then
      ok=1; break
    fi
    sleep 0.5
  done
  rm -f "$dir/ready.html"
  [ "$ok" = 1 ] || { tail -25 "$dir/server.log" >&2; die "site not usable after 60s (last status $code; verify.sh down $run)"; }
  grep -E '^(ERROR|WARN)' "$dir/server.log" | sed 's/^/verify: hugo: /' >&2 || true
  echo "RUN=$run"
  echo "URL=$base"
  echo "EVIDENCE=$dir/evidence"
  echo "MODE=cdn-$(meta "$dir" cdn)"
}

cmd_doctor() {
  local dir pgid port base root ok=1
  dir="$(run_dir "${1:-}")"
  pgid="$(cat "$dir/pgid" 2>/dev/null || true)"
  port="$(meta "$dir" port)"; base="$(meta "$dir" url)"; root="$(meta "$dir" repo)"
  if [ -n "$pgid" ] && pgrep -g "$pgid" >/dev/null 2>&1; then echo "process  ok   pgid $pgid"; else echo "process  FAIL not running"; ok=0; fi
  local owner
  owner="$(port_holder "$port")"
  if [ -n "$owner" ] && [ "$(ps -o pgid= -p "$owner" | tr -d ' ')" = "$pgid" ]; then
    echo "port     ok   :$port owned by this run (pid $owner)"
  else
    echo "port     FAIL :$port held by ${owner:-nobody}, not this run"; ok=0
  fi
  local c1 c2
  c1="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$base" || true)"
  c2="$(curl -s -o /dev/null -w '%{http_code}' -m 5 "${base}docs/" || true)"
  if [ "$c1" = 200 ] && [ "$c2" = 200 ]; then echo "site     ok   $base (home 200, docs/ 200)"; else echo "site     FAIL home $c1, docs/ $c2"; ok=0; fi
  sed 's/^/meta     /' "$dir/meta"
  if [ "$(git -C "$root" rev-parse --short HEAD)" != "$(meta "$dir" head)" ]; then
    echo "code     WARN HEAD moved since up/sync"
  fi
  if [ "$(tree_hash "$root")" != "$(meta "$dir" tree)" ]; then
    echo "code     WARN hugo_docs/ changed since up/sync: the run serves a stale snapshot (verify.sh sync $(basename "$dir"))"
  else
    echo "code     ok   snapshot matches the working tree"
  fi
  local oh
  oh="$(port_holder "$OWNER_PORT")"
  if [ -n "$oh" ]; then echo "owner    info :$OWNER_PORT held by pid $oh ($(ps -o args= -p "$oh" | cut -c1-60)); not ours, left alone"; else echo "owner    info :$OWNER_PORT free (the owner's hugo server is not running)"; fi
  # Egress: hugo is Go, so the dead proxy refuses every non-loopback request it could make. Prove
  # the env refuses a real host without sending anything, and that the site asks hugo for no
  # remote resources at all.
  # shellcheck disable=SC2046
  if $(run_env "$dir") curl -s -o /dev/null -m 5 https://github.com/ 2>/dev/null; then
    echo "egress   FAIL a request to github.com got through the run's environment"; ok=0
  else
    echo "egress   ok   github.com refused by the dead proxy (exit $?)"
  fi
  local remote
  remote="$(grep -rlE 'GetRemote|getJSON|getCSV' "$dir/site/layouts" "$dir/site/themes"/*/layouts 2>/dev/null || true)"
  if [ -n "$remote" ]; then echo "egress   WARN templates fetch remote resources at build time: $remote"; else echo "egress   ok   no template fetches remote resources (no GetRemote/getJSON)"; fi
  if [ -f "$TOOLS/node_modules/playwright/package.json" ]; then echo "tools    ok   playwright $PLAYWRIGHT_VERSION in $TOOLS"; else echo "tools    FAIL playwright missing from $TOOLS"; ok=0; fi
  echo "cdn      info $(find "$CDN_CACHE" -name '*.json' 2>/dev/null | wc -l) cached CDN responses in $CDN_CACHE"
  # Errors from the latest build only; an earlier failure a later rebuild fixed is history.
  local latest
  latest="$(awk '/^Change detected/{buf=""; next} /^(ERROR|WARN)/{buf=buf $0 "\n"} END{printf "%s", buf}' "$dir/server.log")"
  if [ -n "$latest" ]; then sed 's/^/log      /' <<<"$latest"; fi
  if grep -q '^ERROR' <<<"$latest"; then echo "build    FAIL the latest rebuild failed; the server is serving the build before it"; ok=0; fi
  [ "$ok" = 1 ] || exit 1
}

cmd_sync() {
  local dir root off changes fresh=""
  dir="$(run_dir "${1:-}")"; root="$(meta "$dir" repo)"
  # Only log lines written after this point count: an earlier failed rebuild stays in the log.
  off="$(stat -c %s "$dir/server.log")"
  # Lines starting with "." changed attributes only (hugo touches resources/_gen mtimes).
  changes="$(snapshot "$root" "$dir" | grep -vE '^\.|^cd' || true)"
  {
    echo "head=$(git -C "$root" rev-parse --short HEAD)"
    echo "dirty=$(git -C "$root" status --porcelain -- hugo_docs | wc -l)"
    echo "tree=$(tree_hash "$root")"
  } >>"$dir/meta"
  if [ -z "$changes" ]; then echo "verify: snapshot already current; nothing to rebuild"; return 0; fi
  echo "$changes" | sed 's/^/verify: synced /'
  for _ in $(seq 1 60); do
    fresh="$(tail -c +$((off + 1)) "$dir/server.log")"
    grep -qE '^ERROR|Total in' <<<"$fresh" && break
    sleep 0.5
  done
  echo "$(date -Iseconds) sync: $(echo "$changes" | wc -l) path(s), tree $(meta "$dir" tree)" >>"$dir/evidence/LOG.md"
  if grep -q '^ERROR' <<<"$fresh"; then
    grep -E '^(ERROR|WARN)' <<<"$fresh" >&2
    die "rebuild failed after sync (the server keeps serving the last good build)"
  fi
  grep -q 'Total in' <<<"$fresh" || die "no rebuild seen within 30s (log: $dir/server.log)"
  echo "verify: rebuilt ($(grep -oE 'Total in [0-9]+ ms' <<<"$fresh" | tail -1))"
}

cmd_page() {
  local dir path max base url out meta code ctype
  dir="$(run_dir "${1:-}")"; path=${2-}; max=${3:-200}
  [ $# -ge 2 ] || die "page: RUN PATH [MAX_LINES] (PATH '' is the home page)"
  base="$(meta "$dir" url)"
  case "$path" in
    /*) url="http://localhost:$(meta "$dir" port)$path" ;;
    *) url="$base$path" ;;
  esac
  out="$(next_evidence "$dir" page "${path:-home}")"
  meta="$(curl -sS -o "$out.body" -w '%{http_code}|%{content_type}' -m 15 "$url")"
  code=${meta%%|*}; ctype=${meta#*|}
  {
    echo "> GET $url"
    echo "< HTTP $code $ctype"
    if [[ $ctype == text/html* ]]; then
      mv "$out.body" "${out%.txt}.html"
      echo "[html $(wc -c <"${out%.txt}.html") bytes: ${out%.txt}.html]"
      echo "--- visible text ---"
      "$PY" "$HERE/htmltext.py" "${out%.txt}.html" "$max"
    elif [[ $ctype =~ text|json|xml|javascript ]]; then
      "$PY" -c 'import sys; l=open(sys.argv[1],encoding="utf-8",errors="replace").read().splitlines(); n=int(sys.argv[2]); print("\n".join(l[:n])); print(f"[... {len(l)-n} more lines]") if len(l)>n else None' "$out.body" "$max"
      mv "$out.body" "${out%.txt}.body"
    else
      mv "$out.body" "${out%.txt}.bin"
      echo "[binary $(wc -c <"${out%.txt}.bin") bytes, sha256 $(sha256sum "${out%.txt}.bin" | cut -c1-16): ${out%.txt}.bin]"
    fi
  } >"$out"
  cat "$out"
  echo "[evidence: $out]" >&2
}

cmd_ui() {
  local dir steps
  dir="$(run_dir "${1:-}")"; steps=${2:?STEPS.mjs}
  shift 2
  [ "${1:-}" = -- ] && shift
  [ -f "$steps" ] || die "no such steps file: $steps"
  steps="$(realpath "$steps")"
  # No dead proxy here: route.fetch() fills the CDN cache on a miss. The fence is ui.mjs's
  # context.route, which aborts everything but the run's origin and the four public CDNs.
  env -i PATH="$(dirname "$NODE"):/usr/bin:/bin" HOME="$dir/home" LANG=C.UTF-8 TZ=Asia/Jakarta \
    PLAYWRIGHT_BROWSERS_PATH="$HOME/.cache/ms-playwright" VERIFY_TOOLS="$TOOLS" \
    "$NODE" "$HERE/ui.mjs" "$(meta "$dir" url)" "$steps" "$dir/evidence" "$(meta "$dir" cdn)" "$CDN_CACHE" "$@"
}

cmd_build() {
  local dir base out rc=0 r
  dir="$(run_dir "${1:-}")"; base="$(meta "$dir" url)"
  out="$(next_evidence "$dir" build production)"
  [ "$(tree_hash "$(meta "$dir" repo)")" = "$(meta "$dir" tree)" ] \
    || echo "verify: WARN hugo_docs/ changed since up/sync; building the snapshot, not the working tree" >&2
  rm -rf "$dir/build"
  {
    echo "### hugo --minify (HUGO_ENVIRONMENT=production, as deploy.yml, minus --gc) from the snapshot"
    # shellcheck disable=SC2046
    $(run_env "$dir") HUGO_ENVIRONMENT=production HUGO_ENV=production "$HUGO_BIN" \
      --source "$dir/site" --destination "$dir/build" --cacheDir "$dir/cache" \
      --minify --noBuildLock --baseURL "$base" 2>&1 && r=0 || r=$?
    echo "exit $r"; [ "$r" = 0 ] || rc=1
    if [ "$r" = 0 ]; then
      # popups_verify parses the unminified page, so it gets its own build: its default mode, run
      # inside the snapshot (cwd = the script's hugo_docs), with its temp dir under the run.
      echo; echo "### popups_verify.py (its own unminified build of the snapshot vs the frozen baseline)"
      mkdir -p "$dir/tmp"
      # shellcheck disable=SC2046
      $(run_env "$dir") TMPDIR="$dir/tmp" "$PY" "$dir/site/scripts/popups_verify.py" --hugo "$HUGO_BIN" 2>&1 && r=0 || r=$?
      echo "exit $r"; [ "$r" = 0 ] || rc=1
      echo; echo "### popups_emit.py check (data tree vs baseline, referential integrity)"
      # shellcheck disable=SC2046
      $(run_env "$dir") "$PY" "$dir/site/scripts/popups_emit.py" check 2>&1 && r=0 || r=$?
      echo "exit $r"; [ "$r" = 0 ] || rc=1
      echo; echo "### links.py (every internal href/src and #anchor resolves in the build)"
      "$PY" "$HERE/links.py" "$dir/build" "$base" 2>&1 && r=0 || r=$?
      echo "exit $r"; [ "$r" = 0 ] || rc=1
    fi
    echo; echo "build $([ "$rc" = 0 ] && echo OK || echo FAILED)"
  } >"$out"
  cat "$out"
  echo "[evidence: $out]" >&2
  return $rc
}

cmd_note() {
  local dir
  dir="$(run_dir "${1:-}")"
  echo "$(date -Iseconds) ${2:?TEXT}" >>"$dir/evidence/LOG.md"
}

stop_run() {
  local dir=$1 pgid
  pgid="$(cat "$dir/pgid" 2>/dev/null || true)"
  if [ -n "$pgid" ] && pgrep -g "$pgid" >/dev/null 2>&1; then
    kill -TERM -- "-$pgid" 2>/dev/null || true
    for _ in $(seq 1 40); do pgrep -g "$pgid" >/dev/null 2>&1 || break; sleep 0.25; done
    kill -KILL -- "-$pgid" 2>/dev/null || true
    for _ in $(seq 1 20); do pgrep -g "$pgid" >/dev/null 2>&1 || break; sleep 0.25; done
  fi
  [ -f "$dir/server.log" ] && cp "$dir/server.log" "$dir/evidence/server.log"
  local tries
  for tries in 1 2 3; do
    rm -rf "$dir/site" "$dir/home" "$dir/cache" "$dir/public" "$dir/build" "$dir/tmp" 2>/dev/null && break
    sleep 0.5
  done
  rm -f "$dir/pgid" "$dir/server.log"
  echo "verify: stopped $(basename "$dir"); evidence kept in $dir/evidence ($(find "$dir/evidence" -type f | wc -l) files)"
}

cmd_down() {
  if [ "${1:-}" = --all ]; then
    for d in "$VERIFY_HOME"/*/; do [ -f "$d/pgid" ] && stop_run "${d%/}"; done
    return 0
  fi
  stop_run "$(run_dir "${1:-}")"
}

cmd_ls() {
  [ -d "$VERIFY_HOME" ] || return 0
  local d state
  for d in "$VERIFY_HOME"/[0-9]*/; do
    [ -d "$d" ] || continue
    d=${d%/}
    state=stopped
    [ -f "$d/pgid" ] && pgrep -g "$(cat "$d/pgid")" >/dev/null 2>&1 && state="up :$(meta "$d" port)"
    printf '%-20s %-12s cdn-%-8s %3s evidence  %s @ %s\n' "$(basename "$d")" "$state" "$(meta "$d" cdn)" \
      "$(find "$d/evidence" -type f | wc -l)" "$(meta "$d" repo)" "$(meta "$d" head)"
  done
}

sub=${1:-}; shift || true
case "$sub" in
  up) cmd_up "$@" ;;
  doctor) cmd_doctor "$@" ;;
  sync) cmd_sync "$@" ;;
  page) cmd_page "$@" ;;
  ui) cmd_ui "$@" ;;
  build) cmd_build "$@" ;;
  note) cmd_note "$@" ;;
  down) cmd_down "$@" ;;
  ls) cmd_ls ;;
  *) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 2 ;;
esac
