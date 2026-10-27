#!/usr/bin/env python3
"""Freeze the pre-refactor home-page popups into popups_baseline.json.

The landing page stores 51 popup bodies as JavaScript template literals inside
one `switch (type)` in layouts/page/custom-home.html, and 51 trigger buttons in
the feature-card markup above it. This script reads both sides and writes the
frozen truth that every later phase of the popup-data refactor is checked
against:

    hugo_docs/scripts/popups_baseline.json

It owns `norm()` -- the one normalisation the whole refactor agrees on. Nothing
else may define a second one: two normalisers is how a byte-for-byte refactor
silently stops being byte-for-byte. `popups_verify.py` imports it, and so does
`popups_emit.py`.

What is recovered, and why each piece is non-obvious:

  * Bodies come out as the string the BROWSER would see, not as source bytes.
    A template literal is unescaped text: `"\\\\n"` in the source is one
    backslash plus n at runtime. Copying source bytes gets that body wrong and
    nothing downstream would notice, because the baseline would be wrong too.
  * Both `case "dark-launch":` occurrences are kept, distinguished by their
    source line. The second is unreachable in a switch and has never rendered;
    the refactor resurrects it, so the baseline must still carry it.
  * Card and trigger ORDER comes from the trigger lists, never from the switch.
    The two disagree -- Resource Management's buttons and its cases run in
    different sequences -- and the buttons are what renders.

Usage:
    popups_extract.py                      # write the baseline from the worktree page
    popups_extract.py --rev d963643        # ... from the page at a git revision
    popups_extract.py --check              # re-extract and diff against the committed file
    popups_extract.py --self-test          # pin norm() and the dedent split
    popups_extract.py --report             # human summary, writes nothing

Exit status is 0 on success, 1 on a failed check or self-test, 2 on a usage or
parse error (a body that gained a backtick, a `${`, or an escape this script
will not guess at).
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

# hugo_docs/ is the parent of scripts/, the same anchor sync_anchor_docs.py uses.
HUGO_ROOT = Path(__file__).resolve().parent.parent
PAGE_REL = "hugo_docs/layouts/page/custom-home.html"
PAGE = HUGO_ROOT / "layouts" / "page" / "custom-home.html"
BASELINE = HUGO_ROOT / "scripts" / "popups_baseline.json"

SCHEMA = 1

# Expected counts. These are assertions, not configuration: if the page gains a
# popup, the number here moves in the same commit that re-freezes the baseline.
N_OCCURRENCES = 51
N_UNIQUE_IDS = 50
N_CARDS = 10
N_TRIGGERS = 51
SECTIONS = ("agents", "screener", "features")

# --- Decision D1, declared once so the verifier and the emitter cannot drift --
# `dark-launch` is declared twice in the switch and pressed by two buttons in
# two different cards. The refactor splits it: the live :1754 body keeps the id
# in Multimodal Processing, and the dead :2885 body is resurrected under a new
# id in System Observability, whose button already reads "Dark-Launch Feature
# Flags". These names are the contract between popups_verify.py and
# popups_emit.py; neither invents its own.
SPLIT_ID = "dark-launch"
SPLIT_NEW_ID = "feature-flags"
SPLIT_CARD = "system-observability"          # the popup_cards/ basename phase 2 mints
SPLIT_CARD_HEADING = "System Observability"  # the <h4> text, which is what the baseline has
SPLIT_OCCURRENCE = 1                         # 0-based: the DEAD case, by source order

# --- the switch -------------------------------------------------------------
CASE_RE = re.compile(r'^(?P<indent>[ ]*)case "(?P<id>[A-Za-z0-9_-]+)":[ ]*$')
OPEN_RE = re.compile(r"^[ ]*popupContent = `[ ]*$")
CLOSE_RE = re.compile(r"^[ ]*`;[ ]*$")
BREAK_RE = re.compile(r"^[ ]*break;[ ]*$")

# --- the feature cards ------------------------------------------------------
SECTION_RE = re.compile(r'^\s*<section id="(?P<id>[A-Za-z0-9_-]+)"\s*>\s*$')
SECTION_END_RE = re.compile(r"^\s*</section>\s*$")
GRID_RE = re.compile(r'^\s*<div class="feature-grid">\s*$')
CARD_RE = re.compile(r'^\s*<div class="feature-card">\s*$')
H4_RE = re.compile(
    r'^\s*<h4><svg class="ic"><use href="#(?P<icon>[A-Za-z0-9_-]+)"/></svg>\s*'
    r"(?P<heading>.*?)</h4>\s*$"
)
UL_END_RE = re.compile(r"^\s*</ul>\s*$")

# THE TRIGGER CONTRACT. Phase 3 must emit exactly this shape, modulo leading
# whitespace, or property (b) cannot be checked. popups_verify.py reuses this
# very regex against the rendered page -- one pattern, both sides.
TRIGGER_RE = re.compile(
    r'^\s*<li><button class="popup-trigger" type="button" '
    r"onclick=\"showPopup\('(?P<id>[A-Za-z0-9_-]+)'\)\">"
    r"(?P<label>.*?)</button></li>\s*$"
)

# The exact lines phase 3 must render, modulo leading whitespace. Published as
# format strings so the verifier's diffs and phase 3's template agree on one
# spelling instead of two.
CARD_OPEN_LINE = '<div class="feature-card">'
H4_LINE = '<h4><svg class="ic"><use href="#%s"/></svg> %s</h4>'
TRIGGER_LINE = (
    '<li><button class="popup-trigger" type="button" '
    "onclick=\"showPopup('%s')\">%s</button></li>"
)

# THE CARRIER CONTRACT. Phase 3 must emit exactly this shape for every body.
# `type="text/html"` is a non-JS script type, so Go's context-aware escaper
# leaves `safeHTML` output alone; script elements are raw-text, so textContent
# returns those bytes with entities UNDECODED. popups_verify.py matches on it.
CARRIER_OPEN = (
    '<script type="text/html" class="popup-body" data-popup-id="%s">'
)
CARRIER_RE = re.compile(
    r'<script type="text/html" class="popup-body" '
    r'data-popup-id="(?P<id>[A-Za-z0-9_-]+)">(?P<body>.*?)</script>',
    re.S,
)


class ExtractError(RuntimeError):
    """A structural surprise in the page. Always fatal, never worked around."""


# --------------------------------------------------------------------------- norm
def norm(s: str) -> str:
    """The one normalisation this refactor compares through (plan invariant I1).

        1. CRLF (and bare CR) -> LF
        2. every whitespace-only line becomes empty
        3. the longest common leading-whitespace prefix of all NON-BLANK lines
           is removed
        4. leading and trailing blank lines are stripped
        5. exactly one trailing newline

    It preserves every content byte and all RELATIVE indentation. Step 3 is a
    COMMON-PREFIX dedent, not a per-line strip, and that distinction is the
    whole point: 15 of the 51 bodies contain a block that already sits at column
    0 in the source (13 <div class="mermaid"> graph sources and 2 <pre><code>
    blocks), so their common prefix is empty and the surrounding prose keeps its
    authoring indent. Flattening those further would move prose relative to
    whitespace-significant content and break I1. See --self-test.

    Idempotent: norm(norm(s)) == norm(s).
    """
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    lines = ["" if not line.strip() else line for line in s.split("\n")]

    prefix = None
    for line in lines:
        if not line:
            continue
        lead = line[: len(line) - len(line.lstrip(" \t"))]
        if prefix is None:
            prefix = lead
        else:
            cut = 0
            while cut < len(prefix) and cut < len(lead) and prefix[cut] == lead[cut]:
                cut += 1
            prefix = prefix[:cut]
        if not prefix:
            break
    if prefix:
        n = len(prefix)
        lines = [line[n:] if line else "" for line in lines]

    while lines and not lines[0]:
        lines.pop(0)
    while lines and not lines[-1]:
        lines.pop()
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- JS
# Every escape sequence a template literal can legally carry, with the value it
# evaluates to. Anything NOT here raises: a silent guess is how one body ends up
# wrong in a baseline nothing can double-check.
JS_ESCAPES = {
    "\\": "\\", "`": "`", "$": "$", "'": "'", '"': '"',
    "n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
}


def js_unescape(raw: str, where: str) -> str:
    """Turn template-literal SOURCE text into the string the browser sees.

    The popup region holds exactly one escape today -- `"\\\\n"` at :2842, which
    renders as one backslash plus n -- and an extractor that copies source bytes
    verbatim gets that body wrong.
    """
    out = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        if i + 1 >= len(raw):
            raise ExtractError("%s: template literal ends on a lone backslash" % where)
        nxt = raw[i + 1]
        if nxt not in JS_ESCAPES:
            raise ExtractError(
                "%s: escape \\%r is not in the table this script will unwind. "
                "Add it deliberately -- guessing here corrupts a body silently."
                % (where, nxt)
            )
        out.append(JS_ESCAPES[nxt])
        i += 2
    return "".join(out)


# --------------------------------------------------------------------------- parse
def read_page(page: Path, rev: str | None) -> str:
    """The page text, from the worktree or from a git revision.

    `--rev` exists because the baseline is FROZEN PRE-REFACTOR truth. Once phase
    3 rewrites the page, re-extracting from the worktree is meaningless; naming
    the base revision keeps `--check` runnable forever.
    """
    if rev:
        try:
            top = subprocess.run(
                ["git", "-C", str(page.resolve().parent), "rev-parse", "--show-toplevel"],
                check=True, capture_output=True, text=True,
            ).stdout.strip()
            raw = subprocess.run(
                ["git", "-C", top, "show", "%s:%s" % (rev, PAGE_REL)],
                check=True, capture_output=True,
            ).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ExtractError("cannot read %s at revision %s: %s" % (PAGE_REL, rev, exc))
        return raw.decode("utf-8")
    try:
        return page.read_text(encoding="utf-8")
    except OSError as exc:
        raise ExtractError("cannot read %s: %s" % (page, exc))


def extract_cases(lines: list[str]) -> list[dict]:
    """All 51 `case` occurrences, in source order, bodies normalised.

    The shape is uniform but NOT as symmetrical as it looks: the closing "`;"
    sits at the case indent for the 38 era-0 cases and four columns deeper for
    the 13 era-8 ones. So the body runs to the next closing line, found by
    scanning, never by matching an expected indent.
    """
    out = []
    i = 0
    while i < len(lines):
        m = CASE_RE.match(lines[i])
        if not m:
            i += 1
            continue
        case_line = i + 1
        where = 'case "%s" at :%d' % (m.group("id"), case_line)
        if not OPEN_RE.match(lines[i + 1] if i + 1 < len(lines) else ""):
            raise ExtractError("%s: expected `popupContent = \\`` on the next line" % where)
        j = i + 2
        while j < len(lines) and not CLOSE_RE.match(lines[j]):
            j += 1
        if j >= len(lines):
            raise ExtractError("%s: unterminated template literal" % where)
        if not BREAK_RE.match(lines[j + 1] if j + 1 < len(lines) else ""):
            raise ExtractError("%s: expected `break;` after the closing backtick" % where)

        # The literal opens immediately after the backtick, so its first line is
        # empty, and it closes on the whitespace that precedes "`;", so its last
        # line is whitespace-only. norm() deletes both.
        closing_indent = lines[j][: len(lines[j]) - len(lines[j].lstrip(" "))]
        raw = "\n" + "\n".join(lines[i + 2 : j]) + "\n" + closing_indent

        if "`" in raw:
            raise ExtractError(
                "%s: a backtick inside the body. In the live page this breaks the "
                "whole switch; here it means the literal was split and this parse "
                "is wrong. Fix the page, then re-freeze." % where
            )
        if "${" in raw:
            raise ExtractError(
                "%s: a `${` inside the body -- the browser interpolates it, so the "
                "rendered text is not the source text and this baseline would lie."
                % where
            )
        body = norm(js_unescape(raw, where))
        if not body.strip():
            raise ExtractError("%s: empty body" % where)
        out.append(
            {
                "id": m.group("id"),
                "line": case_line,          # phase 2 reads this key first
                "close_line": j + 1,
                "indent": len(m.group("indent")),
                "body": body,
            }
        )
        i = j + 2
    return out


def extract_cards(lines: list[str]) -> list[dict]:
    """The 10 feature cards in source order, each with its triggers in RENDER order.

    Scoped to `<div class="feature-grid">` blocks on purpose: the page has 60-odd
    other <h4> elements (tools, API, installation) and a looser sweep would
    collect them.
    """
    cards: list[dict] = []
    section = None
    in_grid = False
    cur: dict | None = None

    for n, line in enumerate(lines, 1):
        m = SECTION_RE.match(line)
        if m:
            section = m.group("id")
            in_grid = False
            continue
        if SECTION_END_RE.match(line):
            in_grid = False
            cur = None
            continue
        if GRID_RE.match(line):
            if section is None:
                raise ExtractError(":%d: feature-grid outside any <section id=...>" % n)
            in_grid = True
            continue
        if not in_grid:
            continue
        if CARD_RE.match(line):
            cur = {"section": section, "line": n, "triggers": []}
            cards.append(cur)
            continue
        if cur is None:
            continue
        m = H4_RE.match(line)
        if m:
            if "heading" in cur:
                raise ExtractError(":%d: second <h4> in one feature-card" % n)
            cur["icon"] = m.group("icon")
            cur["heading"] = m.group("heading")   # entities exactly as authored
            continue
        m = TRIGGER_RE.match(line)
        if m:
            cur["triggers"].append({"id": m.group("id"), "label": m.group("label"), "line": n})
            continue
        if UL_END_RE.match(line):
            cur = None

    for c in cards:
        if "heading" not in c:
            raise ExtractError(":%d: feature-card with no <h4><svg>...</svg> heading" % c["line"])
        if not c["triggers"]:
            raise ExtractError(":%d: feature-card %r has no popup triggers" % (c["line"], c["heading"]))
        if c["section"] not in SECTIONS:
            raise ExtractError(":%d: card in unexpected section %r" % (c["line"], c["section"]))
    return cards


def build_baseline(text: str) -> dict:
    """The frozen record. Deliberately contains NO absolute path and no
    revision string: the same page bytes must produce the same file whether it
    was read from the worktree or from `git show`, or `--check` would fail for
    a reason that is not drift. `source_sha256` is what pins the revision."""
    if "\r" in text:
        raise ExtractError("the page contains CR; this file is LF-only")
    lines = text.split("\n")
    occurrences = extract_cases(lines)
    cards = extract_cards(lines)

    ids = [o["id"] for o in occurrences]
    trig_ids = [t["id"] for c in cards for t in c["triggers"]]
    problems = []
    if len(occurrences) != N_OCCURRENCES:
        problems.append("expected %d case occurrences, found %d" % (N_OCCURRENCES, len(occurrences)))
    if len(set(ids)) != N_UNIQUE_IDS:
        problems.append("expected %d unique case ids, found %d" % (N_UNIQUE_IDS, len(set(ids))))
    if len(cards) != N_CARDS:
        problems.append("expected %d feature cards, found %d" % (N_CARDS, len(cards)))
    if len(trig_ids) != N_TRIGGERS:
        problems.append("expected %d triggers, found %d" % (N_TRIGGERS, len(trig_ids)))
    if set(ids) != set(trig_ids):
        problems.append(
            "case ids and trigger ids are not the same set; "
            "cases only: %s; triggers only: %s"
            % (sorted(set(ids) - set(trig_ids)), sorted(set(trig_ids) - set(ids)))
        )
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    if dupes != [SPLIT_ID]:
        problems.append("expected exactly one duplicated case id (%r), found %s" % (SPLIT_ID, dupes))
    if sorted({i for i in trig_ids if trig_ids.count(i) > 1}) != [SPLIT_ID]:
        problems.append("expected exactly one duplicated trigger id (%r)" % SPLIT_ID)
    if problems:
        raise ExtractError("; ".join(problems))

    return {
        "schema": SCHEMA,
        "source": PAGE_REL,
        "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source_lines": text.count("\n"),
        "counts": {
            "cards": len(cards),
            "occurrences": len(occurrences),
            "triggers": len(trig_ids),
            "unique_ids": len(set(ids)),
        },
        "cards": cards,
        "occurrences": occurrences,
    }


def dumps(baseline: dict) -> str:
    """Deterministic: sorted keys, fixed indent, UTF-8 kept as UTF-8, one newline."""
    return json.dumps(baseline, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------- self-test
NORM_CASES = [
    ("CRLF folds to LF", "  <p>a</p>\r\n  <p>b</p>\r\n", "<p>a</p>\n<p>b</p>\n"),
    ("whitespace-only lines are emptied", "  <p>a</p>\n   \n  <p>b</p>\n", "<p>a</p>\n\n<p>b</p>\n"),
    ("common prefix removed, relative indent kept",
     "    <ul>\n        <li>x</li>\n    </ul>\n", "<ul>\n    <li>x</li>\n</ul>\n"),
    ("a column-0 line pins the prefix at zero",
     "    <p>a</p>\n<pre>keep\n  me</pre>\n    <p>b</p>\n",
     "    <p>a</p>\n<pre>keep\n  me</pre>\n    <p>b</p>\n"),
    ("leading and trailing blank lines stripped",
     "\n\n  <p>a</p>\n\n  \n", "<p>a</p>\n"),
    ("exactly one trailing newline", "  <p>a</p>\n\n\n", "<p>a</p>\n"),
    ("no trailing newline gains one", "  <p>a</p>", "<p>a</p>\n"),
    ("inline spacing untouched", "  <p>a  b</p>\n", "<p>a  b</p>\n"),
    ("a lone backslash survives", "  <code>a + \"\\n\"</code>\n", '<code>a + "\\n"</code>\n'),
    ("empty input is one newline", "   \n\n", "\n"),
]

# The 15 bodies norm() leaves indented, and by how much. This is the F2 pin: it
# is CORRECT behaviour, not a bug, and phase 3 must not "fix" it.
RESIDUAL_INDENTS = {
    "server-owned-routing": 4, "image-pipeline": 4, "screener-lock": 4,
    "cache-fastlane": 4, "parallel-map-execution": 4, "stateful-conversation": 4,
    "data-driven-tools": 4, "citations": 4, "file-asset-integrity": 4,
    "bowl-resume": 16, "circuit-breakers": 16, "e2e-cancellation": 16,
    "structured-logging": 16, "observability-stack": 16, "status-tracking": 16,
}


def self_test(baseline: dict | None) -> int:
    fails = 0
    for name, src, want in NORM_CASES:
        got = norm(src)
        if got != want:
            print("FAIL norm: %s\n  want %r\n  got  %r" % (name, want, got), file=sys.stderr)
            fails += 1
        elif norm(got) != got:
            print("FAIL norm not idempotent: %s" % name, file=sys.stderr)
            fails += 1
    print("norm unit cases: %d, failures: %d" % (len(NORM_CASES), fails))

    if baseline is None:
        return 1 if fails else 0

    residual = {}
    for occ in baseline["occurrences"]:
        first = occ["body"].split("\n")[0]
        lead = len(first) - len(first.lstrip(" "))
        if lead:
            residual[occ["id"]] = lead
    flat = len(baseline["occurrences"]) - len(residual)
    if residual != RESIDUAL_INDENTS:
        print("FAIL dedent split moved.\n  want %s\n  got  %s"
              % (sorted(RESIDUAL_INDENTS.items()), sorted(residual.items())), file=sys.stderr)
        fails += 1
    print("dedent split: %d bodies flattened to column 0, %d keep a residual indent "
          "(%d at 4, %d at 16) -- EXPECTED, see norm()'s docstring"
          % (flat, len(residual),
             sum(1 for v in residual.values() if v == 4),
             sum(1 for v in residual.values() if v == 16)))

    escaped = [o for o in baseline["occurrences"] if "\\" in o["body"]]
    if [o["id"] for o in escaped] != ["alerting"]:
        print("FAIL expected exactly one body carrying a backslash ('alerting'), got %s"
              % [o["id"] for o in escaped], file=sys.stderr)
        fails += 1
    else:
        hit = [l for l in escaped[0]["body"].split("\n") if "\\" in l][0]
        print("JS unescape: `alerting` carries one backslash (source :2842 held two) -> %s"
              % repr(hit.strip()[:88]))
    return 1 if fails else 0


# --------------------------------------------------------------------------- report
def report(baseline: dict) -> None:
    occ = baseline["occurrences"]
    print("source      %s (%d lines, sha256 %s)"
          % (baseline["source"], baseline["source_lines"], baseline["source_sha256"][:12]))
    print("occurrences %d case bodies (%d unique ids)"
          % (len(occ), baseline["counts"]["unique_ids"]))
    print("triggers    %d across %d cards" % (baseline["counts"]["triggers"], len(baseline["cards"])))
    for c in baseline["cards"]:
        print("    %-9s :%-4d %-28s %-16s %d triggers"
              % (c["section"], c["line"], c["heading"], c["icon"], len(c["triggers"])))
    dup = [o for o in occ if o["id"] == SPLIT_ID]
    for k, o in enumerate(dup):
        kind = "LIVE" if k == 0 else "DEAD"
        print("    %s case %r #%d at :%d -> %s"
              % (kind, SPLIT_ID, k, o["line"], o["body"].split("\n")[0].strip()))


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--page", type=Path, default=PAGE, help="page to parse (default: the worktree copy)")
    ap.add_argument("--rev", help="read the page from this git revision instead of the worktree")
    ap.add_argument("--out", type=Path, default=BASELINE, help="baseline to write (default: %s)" % BASELINE.name)
    ap.add_argument("--check", action="store_true",
                    help="re-extract and diff against --out instead of writing it")
    ap.add_argument("--self-test", action="store_true", help="pin norm() and the dedent split")
    ap.add_argument("--report", action="store_true", help="print a summary; write nothing")
    args = ap.parse_args(argv)

    try:
        label = "%s@%s" % (PAGE_REL, args.rev) if args.rev else str(args.page)
        text = read_page(args.page, args.rev)
        baseline = build_baseline(text)
    except ExtractError as exc:
        print("extract error: %s" % exc, file=sys.stderr)
        return 2

    if args.self_test:
        return self_test(baseline)
    if args.report:
        report(baseline)
        return 0
    if args.check:
        if not args.out.exists():
            print("no baseline at %s to check against" % args.out, file=sys.stderr)
            return 1
        on_disk = args.out.read_text(encoding="utf-8")
        fresh = dumps(baseline)
        if on_disk == fresh:
            print("baseline is byte-identical to a fresh extraction of %s" % label)
            return 0
        print("BASELINE DRIFT: %s does not match a fresh extraction of %s"
              % (args.out, label), file=sys.stderr)
        sys.stderr.writelines(
            difflib.unified_diff(on_disk.splitlines(True), fresh.splitlines(True),
                                 "committed", "fresh", n=2)
        )
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(dumps(baseline), encoding="utf-8", newline="\n")
    print("wrote %s: %d occurrences, %d cards, %d triggers, from %s"
          % (args.out, len(baseline["occurrences"]), len(baseline["cards"]),
             baseline["counts"]["triggers"], label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
