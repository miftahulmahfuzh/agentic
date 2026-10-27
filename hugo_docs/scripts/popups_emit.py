#!/usr/bin/env python3
"""Emit the Hugo popup data tree from the phase-1 baseline.

    python3 hugo_docs/scripts/popups_emit.py emit [--force]
    python3 hugo_docs/scripts/popups_emit.py check

`emit` writes hugo_docs/data/popup_cards/*.yaml (10) and hugo_docs/data/popups/*.yaml (51)
from hugo_docs/scripts/popups_baseline.json, applying decision D1 (the dark-launch split).
`check` reads those files back and asserts, for every id, that the body is byte-identical to
the baseline body, plus the referential-integrity properties phase 3 turns into build guards.

This is a BOOTSTRAP tool. Once the tree is committed the YAML files are the source of truth;
re-running `emit` without --force refuses to clobber them. `check` stays useful forever.

norm() is NOT defined here. It is imported from popups_extract, which owns it. Two norm()s is
how this refactor silently fails.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent          # hugo_docs/scripts
HUGO = HERE.parent                              # hugo_docs
sys.path.insert(0, str(HERE))

# --- Decision D1: the dark-launch split ------------------------------------
# The id `dark-launch` is declared twice in the switch. The first (live) body stays in the
# Multimodal Processing card under the id it has. The second (dead) body is resurrected under
# a NEW id in the System Observability card, where its trigger button already sits and already
# reads "Dark-Launch Feature Flags". Nothing is dropped. This is the one sanctioned content
# change in the whole refactor; see POPUP_DATA_REFACTOR_PLAN.md, Decisions table, D1.
#
# These names are NOT re-declared here. popups_extract.py owns them, popups_verify.py imports
# them, and so does this module: one definition, so the emitter and the checker cannot disagree
# about which body `feature-flags` gets.
from popups_extract import (                   # noqa: E402  (phase 1 owns all of this)
    SPLIT_CARD,
    SPLIT_ID,
    SPLIT_NEW_ID,
    SPLIT_OCCURRENCE,
    norm,
)

BASELINE_PATH = HERE / "popups_baseline.json"
DATA_DIR = HUGO / "data"
POPUPS_DIR = DATA_DIR / "popups"
CARDS_DIR = DATA_DIR / "popup_cards"

# Card ids are PINNED, not merely derived. Phase 3's build guard G1 fails on a typo here, and a
# future change to slugify() must not silently rename a data file. Keys are the <h4> inner text
# exactly as authored, entities included.
CARD_IDS = {
    "Multi-Agent System": "multi-agent-system",
    "Multimodal Processing": "multimodal-processing",
    "The Lock": "the-lock",
    "Planning a Turn": "planning-a-turn",
    "The Measured API": "the-measured-api",
    "Shape of the Tool": "shape-of-the-tool",
    "Performance &amp; Architecture": "performance-architecture",
    "Resource Management": "resource-management",
    "Data Handling &amp; Integrity": "data-handling-integrity",
    "System Observability": "system-observability",
}

SECTIONS = ("agents", "screener", "features")

HEADER = (
    "# Generated once by hugo_docs/scripts/popups_emit.py; this file is now the source of truth.\n"
    "# Edit the prose here. `popups_emit.py check` re-asserts it against popups_baseline.json.\n"
)

BLOCK_INDENT = 2


# --------------------------------------------------------------------------- baseline adapter
class BaselineError(RuntimeError):
    pass


def _pick(d: dict, *names: str):
    """Return the first present key among `names`, or raise naming what was actually there."""
    for n in names:
        if n in d:
            return d[n]
    raise BaselineError(
        "popups_baseline.json: expected one of %r, found keys %r"
        % (list(names), sorted(d.keys()))
    )


def load_baseline(path: Path = BASELINE_PATH):
    """Normalise phase 1's baseline into (occurrences, cards).

    occurrences: list of {"id", "body", "line"} for all 51 `case` occurrences, in SOURCE ORDER.
                 Both dark-launch entries are present and distinguished by position.
    cards:       list of {"section", "heading", "icon", "triggers": [{"id", "label"}]},
                 in SOURCE ORDER, each trigger list in TRIGGER ORDER (never switch order).
    """
    raw = json.loads(path.read_text(encoding="utf-8"))

    raw_occ = _pick(raw, "occurrences", "bodies", "cases", "popups")
    if isinstance(raw_occ, dict):
        # tolerated shape: {key: {...}} — order is recovered from the line number
        raw_occ = list(raw_occ.values())
    occurrences = []
    for o in raw_occ:
        occurrences.append(
            {
                "id": _pick(o, "id", "popup_id", "case"),
                "body": _pick(o, "body", "html", "content"),
                "line": int(_pick(o, "line", "case_line", "lineno", "start_line")),
            }
        )
    occurrences.sort(key=lambda o: o["line"])

    raw_cards = _pick(raw, "cards", "feature_cards", "popup_cards")
    cards = []
    for c in raw_cards:
        raw_trigs = _pick(c, "triggers", "popups", "buttons", "items")
        cards.append(
            {
                "section": _pick(c, "section"),
                "heading": _pick(c, "heading", "title", "h4"),
                "icon": _pick(c, "icon"),
                "triggers": [
                    {"id": _pick(t, "id", "popup_id"), "label": _pick(t, "label", "text")}
                    for t in raw_trigs
                ],
            }
        )

    if len(occurrences) != 51:
        raise BaselineError("expected 51 case occurrences, got %d" % len(occurrences))
    if len(cards) != 10:
        raise BaselineError("expected 10 cards, got %d" % len(cards))
    n_trig = sum(len(c["triggers"]) for c in cards)
    if n_trig != 51:
        raise BaselineError("expected 51 triggers, got %d" % n_trig)
    for c in cards:
        if c["section"] not in SECTIONS:
            raise BaselineError("unknown section %r on card %r" % (c["section"], c["heading"]))
    return occurrences, cards


def body_for(occurrences, popup_id: str, nth: int = 0) -> str:
    """The nth (0-based, source order) `case` body for popup_id, normalised."""
    hits = [o for o in occurrences if o["id"] == popup_id]
    if len(hits) <= nth:
        raise BaselineError("no occurrence #%d of case %r in the baseline" % (nth, popup_id))
    return norm(hits[nth]["body"])


# --------------------------------------------------------------------------- YAML emission
def slugify(heading: str) -> str:
    s = html.unescape(heading).lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def card_id_for(heading: str) -> str:
    try:
        pinned = CARD_IDS[heading]
    except KeyError:
        raise BaselineError(
            "card heading %r is not in CARD_IDS. A new card needs a pinned id here, "
            "because phase 3's guard G1 and every popup's `card:` field spell it out." % heading
        )
    derived = slugify(heading)
    if derived != pinned:
        raise BaselineError(
            "pinned card id %r disagrees with slugify(%r) = %r" % (pinned, heading, derived)
        )
    return pinned


def yaml_scalar(s: str) -> str:
    """A double-quoted YAML scalar. Entities stay as authored; nothing is decoded."""
    if "\n" in s or "\r" in s or "\t" in s:
        raise ValueError("control character in scalar: %r" % s)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def yaml_block(body: str, indent: int = BLOCK_INDENT) -> str:
    """A literal block scalar with an EXPLICIT indentation indicator.

    `|%d` rather than a bare `|` because 15 of the 51 bodies legitimately begin with leading
    whitespace (finding F2) — mermaid and <pre> bodies whose common prefix norm() cannot strip.
    With a bare `|` YAML infers the indent from the first non-empty line, which for those bodies
    is wrong. The explicit indicator makes the parse independent of the content.

    `|` (clip chomping) keeps exactly one trailing newline, which is what norm() guarantees.
    """
    if not body.endswith("\n"):
        raise ValueError("body does not end in a newline — norm() was not applied")
    if body.endswith("\n\n"):
        raise ValueError("body ends in more than one newline — norm() was not applied")
    if not body.strip():
        raise ValueError("empty body")
    if "</script>" in body:
        raise ValueError("body contains </script>; it cannot ride in a script carrier")
    if "\t" in body:
        raise ValueError("body contains a tab; the page region has none and a tab breaks dedent")
    pad = " " * indent
    out = ["|%d" % indent]
    for line in body[:-1].split("\n"):
        if line and line.rstrip() != line:
            print("warn: trailing whitespace preserved verbatim: %r" % line, file=sys.stderr)
        out.append(pad + line if line else "")
    return "\n".join(out) + "\n"


def card_yaml(section: str, heading: str, icon: str, order: int) -> str:
    return (
        HEADER
        + "section: %s\n" % section
        + "heading: %s\n" % yaml_scalar(heading)
        + "icon:    %s\n" % icon
        + "order:   %d\n" % order
    )


def popup_yaml(card: str, order: int, label: str, body: str) -> str:
    return (
        HEADER
        + "card:  %s\n" % card
        + "order: %d\n" % order
        + "label: %s\n" % yaml_scalar(label)
        + "body: " + yaml_block(body)
    )


# --------------------------------------------------------------------------- plan + write
def build_plan(occurrences, cards):
    """(card_records, popup_records). Pure: no I/O, so `check` reuses it verbatim."""
    seen_occ = {}          # popup id -> how many case occurrences consumed so far
    section_order = {}
    card_records, popup_records = [], []

    for card in cards:
        cid = card_id_for(card["heading"])
        section_order[card["section"]] = section_order.get(card["section"], 0) + 10
        card_records.append(
            {
                "id": cid,
                "section": card["section"],
                "heading": card["heading"],
                "icon": card["icon"],
                "order": section_order[card["section"]],
            }
        )
        for i, trig in enumerate(card["triggers"]):
            src_id = trig["id"]
            nth = seen_occ.get(src_id, 0)
            seen_occ[src_id] = nth + 1
            out_id = src_id
            if src_id == SPLIT_ID and cid == SPLIT_CARD:
                out_id = SPLIT_NEW_ID          # D1
                nth = SPLIT_OCCURRENCE         # 1: the DEAD :2885 body, not the live :1754 one
            popup_records.append(
                {
                    "id": out_id,
                    "card": cid,
                    "order": (i + 1) * 10,
                    "label": trig["label"],
                    "body": body_for(occurrences, src_id, nth),
                }
            )
    return card_records, popup_records


def integrity(card_records, popup_records) -> list[str]:
    """Pre-flight for phase 3's build guards G1-G3, plus the content assertions."""
    errs = []
    card_ids = {c["id"] for c in card_records}
    if len(card_ids) != len(card_records):
        errs.append("duplicate card id")
    popup_ids = [p["id"] for p in popup_records]
    if len(set(popup_ids)) != len(popup_ids):
        dupes = sorted({i for i in popup_ids if popup_ids.count(i) > 1})
        errs.append("G0 duplicate popup id (filename collision): %s" % dupes)
    for p in popup_records:
        if p["card"] not in card_ids:
            errs.append("G1 popup %r names unknown card %r" % (p["id"], p["card"]))
        if not p["label"].strip():
            errs.append("empty label on %r" % p["id"])
        if not p["body"].strip():
            errs.append("empty body on %r" % p["id"])
        if "</script>" in p["body"]:
            errs.append("</script> in body of %r" % p["id"])
    for cid in card_ids:
        mine = [p for p in popup_records if p["card"] == cid]
        if not mine:
            errs.append("G2 card %r has no popups" % cid)
        orders = [p["order"] for p in mine]
        if len(set(orders)) != len(orders):
            errs.append("G3 order collision in card %r: %s" % (cid, sorted(orders)))
    return errs


def cmd_emit(force: bool) -> int:
    occurrences, cards = load_baseline()
    card_records, popup_records = build_plan(occurrences, cards)
    errs = integrity(card_records, popup_records)
    if errs:
        for e in errs:
            print("ERROR %s" % e, file=sys.stderr)
        return 1

    for d in (CARDS_DIR, POPUPS_DIR):
        d.mkdir(parents=True, exist_ok=True)          # finding F1: data/ does not exist
        existing = sorted(d.glob("*.yaml"))
        if existing and not force:
            print(
                "refusing to overwrite %d file(s) in %s; these YAML files are the source of "
                "truth now. Pass --force only to re-bootstrap from the baseline."
                % (len(existing), d),
                file=sys.stderr,
            )
            return 1

    for c in card_records:
        (CARDS_DIR / ("%s.yaml" % c["id"])).write_text(
            card_yaml(c["section"], c["heading"], c["icon"], c["order"]), encoding="utf-8"
        )
    for p in popup_records:
        (POPUPS_DIR / ("%s.yaml" % p["id"])).write_text(
            popup_yaml(p["card"], p["order"], p["label"], p["body"]), encoding="utf-8"
        )

    print("wrote %d popup_cards + %d popups = %d files"
          % (len(card_records), len(popup_records), len(card_records) + len(popup_records)))
    return 0


def cmd_check() -> int:
    try:
        import yaml  # PyYAML, dev-time only; Hugo is the authoritative parser (see Step 4)
    except ImportError:
        print("check needs PyYAML (pip install --user pyyaml). The `hugo` build in the exit "
              "criteria is the authoritative parse check; this is the byte-level one.",
              file=sys.stderr)
        return 2

    occurrences, cards = load_baseline()
    card_records, popup_records = build_plan(occurrences, cards)

    fails = 0
    on_disk_popups = sorted(p.stem for p in POPUPS_DIR.glob("*.yaml"))
    on_disk_cards = sorted(c.stem for c in CARDS_DIR.glob("*.yaml"))
    if on_disk_popups != sorted(p["id"] for p in popup_records):
        print("FAIL popups/ on disk does not match the plan", file=sys.stderr)
        fails += 1
    if on_disk_cards != sorted(c["id"] for c in card_records):
        print("FAIL popup_cards/ on disk does not match the plan", file=sys.stderr)
        fails += 1

    for c in card_records:
        d = yaml.safe_load((CARDS_DIR / ("%s.yaml" % c["id"])).read_text(encoding="utf-8"))
        for k in ("section", "heading", "icon", "order"):
            if d.get(k) != c[k]:
                print("FAIL card %s.%s: %r != %r" % (c["id"], k, d.get(k), c[k]), file=sys.stderr)
                fails += 1

    h2_re = re.compile(r"<h2>(.*?)</h2>", re.S)
    divergent = []
    for p in popup_records:
        d = yaml.safe_load((POPUPS_DIR / ("%s.yaml" % p["id"])).read_text(encoding="utf-8"))
        for k in ("card", "order", "label"):
            if d.get(k) != p[k]:
                print("FAIL %s.%s: %r != %r" % (p["id"], k, d.get(k), p[k]), file=sys.stderr)
                fails += 1
        # the property this whole phase exists to guarantee
        if norm(d.get("body") or "") != p["body"]:
            print("FAIL body round trip: %s" % p["id"], file=sys.stderr)
            fails += 1
        m = h2_re.search(d.get("body") or "")
        if m and m.group(1) != p["label"]:
            divergent.append((p["id"], p["label"], m.group(1)))

    errs = integrity(card_records, popup_records)
    for e in errs:
        print("FAIL %s" % e, file=sys.stderr)
    fails += len(errs)

    for pid, label, h2 in divergent:
        print("note: label != <h2> for %s: %r vs %r" % (pid, label, h2))
    if len(divergent) != 1 or divergent[0][0] != "screener-content-is-routing":
        print("FAIL expected exactly one label/<h2> divergence "
              "(screener-content-is-routing); got %r" % [d[0] for d in divergent],
              file=sys.stderr)
        fails += 1

    print("checked %d cards + %d popups; failures: %d"
          % (len(card_records), len(popup_records), fails))
    return 1 if fails else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("emit", help="write the data tree from the baseline")
    e.add_argument("--force", action="store_true", help="overwrite an existing data tree")
    sub.add_parser("check", help="assert the data tree against the baseline")
    args = ap.parse_args(argv)
    try:
        return cmd_emit(args.force) if args.cmd == "emit" else cmd_check()
    except BaselineError as exc:
        print("baseline error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
