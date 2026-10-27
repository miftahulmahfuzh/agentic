#!/usr/bin/env python3
"""Check the rendered home page against the frozen popup baseline.

This is the committed form of the refactor's verification properties. It builds
the site, pulls the popup bodies and the feature-card trigger lists back out of
the RENDERED html, and diffs them against popups_baseline.json -- the snapshot
popups_extract.py froze from the pre-refactor JavaScript switch.

    property (a)  for every popup id, the HTML that ends up inside
                  #popup-content is byte-identical to what the old switch
                  produced, after the shared norm().
    property (b)  the rendered trigger lists are unchanged: same cards, same
                  sections, same icons, same buttons, same labels, same order.

Both sides go through popups_extract.norm(). There is exactly one normaliser in
this refactor and it lives there; this script imports it and defines nothing of
its own.

The one sanctioned difference is decision D1: `dark-launch` was declared twice
in the switch and pressed by two buttons in two cards, so the dead second body
is resurrected as a NEW id, `feature-flags`, under the System Observability
button that already carries its name. That exception is applied by name and
printed by name -- it is never silent, and it is the only id allowed to have no
pre-refactor rendered counterpart.

Run it BEFORE the refactor too. It then reports every id as MISSING and exits
non-zero, which is the proof that the render-side extractor actually executes
and that a later green run means something.

Usage:
    popups_verify.py                       # build with ~/bin/hugo, then check
    popups_verify.py --index public/index.html   # check an existing build
    popups_verify.py --hugo /path/to/hugo  # a different binary (must be >=0.164)

Exit status is 0 when both properties hold, 1 when any id or trigger mismatches,
and 2 on a build or usage error. `--gc` is never passed: it would delete the
committed hugo_docs/resources/_gen/.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent          # hugo_docs/scripts
HUGO_ROOT = HERE.parent                         # hugo_docs
sys.path.insert(0, str(HERE))

from popups_extract import (                    # noqa: E402  -- one owner for all of this
    CARRIER_RE,
    SPLIT_CARD_HEADING,
    SPLIT_ID,
    SPLIT_NEW_ID,
    SPLIT_OCCURRENCE,
    TRIGGER_LINE,
    ExtractError,
    extract_cards,
    norm,
)

import json                                     # noqa: E402

BASELINE = HERE / "popups_baseline.json"
DEFAULT_HUGO = Path(os.path.expanduser("~/bin/hugo"))
MIN_HUGO = (0, 164, 0)
VERSION_RE = re.compile(r"hugo v(\d+)\.(\d+)\.(\d+)")


class VerifyError(RuntimeError):
    pass


# --------------------------------------------------------------------------- build
def hugo_version(binary: Path) -> tuple[int, int, int]:
    try:
        out = subprocess.run([str(binary), "version"], check=True,
                             capture_output=True, text=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise VerifyError("cannot run %s: %s" % (binary, exc))
    m = VERSION_RE.search(out)
    if not m:
        raise VerifyError("cannot parse a version out of %r" % out.strip())
    return tuple(int(g) for g in m.groups())


def build(binary: Path, keep: bool) -> Path:
    """Build into a throwaway directory and return its index.html.

    Never into hugo_docs/public/: that is gitignored and CI-built, and a verify
    run has no business rewriting it. Never with --gc either -- it deletes the
    committed resources/_gen/ this theme needs.
    """
    version = hugo_version(binary)
    if version < MIN_HUGO:
        raise VerifyError(
            "%s is hugo v%d.%d.%d; this site needs >= v%d.%d.%d (the Stack theme "
            "fails on older ones). Use ~/bin/hugo, not /usr/bin/hugo."
            % ((binary,) + version + MIN_HUGO)
        )
    dest = Path(tempfile.mkdtemp(prefix="popups_verify_"))
    cmd = [str(binary), "--quiet", "--destination", str(dest)]
    proc = subprocess.run(cmd, cwd=str(HUGO_ROOT), capture_output=True, text=True)
    noise = (proc.stdout + proc.stderr).strip()
    if proc.returncode != 0:
        raise VerifyError("hugo failed (%d):\n%s" % (proc.returncode, noise))
    if noise:
        print("hugo said:\n%s" % noise, file=sys.stderr)
    index = dest / "index.html"
    if not index.exists():
        raise VerifyError("hugo wrote no index.html into %s" % dest)
    print("build       %s v%d.%d.%d -> %s (no --gc)"
          % (binary, version[0], version[1], version[2], dest if keep else "<temp>"))
    return index


# --------------------------------------------------------------------------- model
def expected(baseline: dict) -> tuple[dict, list[dict]]:
    """What the POST-refactor page must contain: bodies by id, and cards.

    Applies decision D1 and nothing else. Every other id keeps the body of its
    FIRST case occurrence, because a JavaScript switch takes the first match --
    that is what the page has always rendered.
    """
    occurrences = baseline["occurrences"]
    bodies: dict[str, str] = {}
    for occ in occurrences:
        bodies.setdefault(occ["id"], norm(occ["body"]))

    split = [o for o in occurrences if o["id"] == SPLIT_ID]
    if len(split) <= SPLIT_OCCURRENCE:
        raise VerifyError(
            "the baseline has %d occurrence(s) of case %r; D1 needs #%d (the dead "
            "one). Re-freeze with popups_extract.py."
            % (len(split), SPLIT_ID, SPLIT_OCCURRENCE)
        )
    bodies[SPLIT_NEW_ID] = norm(split[SPLIT_OCCURRENCE]["body"])

    cards = []
    for card in baseline["cards"]:
        triggers = []
        for trig in card["triggers"]:
            tid = trig["id"]
            if tid == SPLIT_ID and card["heading"] == SPLIT_CARD_HEADING:
                tid = SPLIT_NEW_ID
            triggers.append({"id": tid, "label": trig["label"]})
        cards.append({"section": card["section"], "heading": card["heading"],
                      "icon": card["icon"], "triggers": triggers})
    return bodies, cards


def rendered(index: Path) -> tuple[dict, list[dict]]:
    """Bodies and cards as the built page actually contains them.

    Bodies are read VERBATIM out of the carrier element. No HTML entity
    decoding: a <script> is raw text, so `&amp;` reaches textContent as the five
    characters `&amp;`, and decoding here would compare against a string the
    browser never sees.
    """
    text = index.read_text(encoding="utf-8")
    bodies: dict[str, str] = {}
    for m in CARRIER_RE.finditer(text):
        pid = m.group("id")
        if pid in bodies:
            raise VerifyError("two carriers with data-popup-id=%r in the render" % pid)
        bodies[pid] = norm(m.group("body"))
    cards = extract_cards(text.split("\n"))
    return bodies, cards


# --------------------------------------------------------------------------- compare
def li(trigger: dict) -> str:
    return TRIGGER_LINE % (trigger["id"], trigger["label"])


def compare_bodies(want: dict, got: dict) -> int:
    """Property (a). Returns the failure count; prints one line per id."""
    fails = 0
    stats = {"PASS": 0, "FAIL": 0, "MISSING": 0, "EXTRA": 0}
    for pid in sorted(want):
        tag = "" if pid != SPLIT_NEW_ID else "   [D1: new id, checked against the DEAD case]"
        if pid not in got:
            print("  MISSING %s%s" % (pid, tag))
            stats["MISSING"] += 1
            fails += 1
        elif got[pid] == want[pid]:
            print("  PASS    %s%s" % (pid, tag))
            stats["PASS"] += 1
        else:
            print("  FAIL    %s%s" % (pid, tag))
            stats["FAIL"] += 1
            fails += 1
            sys.stdout.writelines(
                "    " + line for line in difflib.unified_diff(
                    want[pid].splitlines(True), got[pid].splitlines(True),
                    "baseline/%s" % pid, "rendered/%s" % pid, n=2)
            )
    for pid in sorted(set(got) - set(want)):
        print("  EXTRA   %s  (rendered, but no baseline body answers to this id)" % pid)
        stats["EXTRA"] += 1
        fails += 1
    print("  -> PASS %d  FAIL %d  MISSING %d  EXTRA %d"
          % (stats["PASS"], stats["FAIL"], stats["MISSING"], stats["EXTRA"]))
    return fails


def compare_cards(want: list, got: list) -> int:
    """Property (b). Compared structurally, which IS the per-line comparison:
    the trigger and <h4> patterns are fully anchored, so a changed class, type,
    attribute order or label makes the line stop matching and the trigger goes
    MISSING. Leading indentation is the only thing deliberately ignored."""
    fails = 0
    want_key = [(c["section"], c["heading"], c["icon"]) for c in want]
    got_key = [(c["section"], c["heading"], c["icon"]) for c in got]
    if want_key != got_key:
        print("  FAIL card list (section, heading, icon) differs")
        sys.stdout.writelines(
            "    " + line for line in difflib.unified_diff(
                ["%s | %s | %s\n" % k for k in want_key],
                ["%s | %s | %s\n" % k for k in got_key],
                "baseline/cards", "rendered/cards", n=2)
        )
        return 1

    for wcard, gcard in zip(want, got):
        wl = [li(t) + "\n" for t in wcard["triggers"]]
        gl = [li(t) + "\n" for t in gcard["triggers"]]
        if wl == gl:
            print("  PASS    %-9s %-28s %d triggers"
                  % (wcard["section"], wcard["heading"], len(wl)))
        else:
            print("  FAIL    %-9s %-28s" % (wcard["section"], wcard["heading"]))
            fails += 1
            sys.stdout.writelines(
                "    " + line for line in difflib.unified_diff(
                    wl, gl, "baseline/%s" % wcard["heading"],
                    "rendered/%s" % gcard["heading"], n=2)
            )
    return fails


# --------------------------------------------------------------------------- main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--index", type=Path,
                    help="an already-built index.html; skips the hugo build")
    ap.add_argument("--hugo", type=Path, default=DEFAULT_HUGO,
                    help="hugo binary (default: ~/bin/hugo)")
    ap.add_argument("--baseline", type=Path, default=BASELINE)
    ap.add_argument("--keep", action="store_true", help="print the temp build directory")
    args = ap.parse_args(argv)

    try:
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print("cannot read baseline %s: %s" % (args.baseline, exc), file=sys.stderr)
        return 2

    try:
        index = args.index if args.index else build(args.hugo, args.keep)
        if args.index:
            print("build       skipped, reading %s" % args.index)
        want_bodies, want_cards = expected(baseline)
        got_bodies, got_cards = rendered(index)
    except (VerifyError, ExtractError, OSError) as exc:
        print("verify error: %s" % exc, file=sys.stderr)
        return 2

    print("baseline    %s (%d occurrences, %d cards, %d triggers)"
          % (args.baseline.name, baseline["counts"]["occurrences"],
             baseline["counts"]["cards"], baseline["counts"]["triggers"]))
    print("sanctioned exception (D1): %r is a NEW id with no pre-refactor rendered "
          "counterpart; its body is the DEAD `case \"%s\"` and the %r button's onclick "
          "moves from %r to %r. Nothing else may differ."
          % (SPLIT_NEW_ID, SPLIT_ID, SPLIT_CARD_HEADING, SPLIT_ID, SPLIT_NEW_ID))

    print("\nproperty (a) -- popup bodies, %d expected" % len(want_bodies))
    fails = compare_bodies(want_bodies, got_bodies)
    print("\nproperty (b) -- feature-card triggers, %d cards expected" % len(want_cards))
    fails += compare_cards(want_cards, got_cards)

    print("\n%s  (%d failure%s)"
          % ("OK" if not fails else "NOT OK", fails, "" if fails == 1 else "s"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
