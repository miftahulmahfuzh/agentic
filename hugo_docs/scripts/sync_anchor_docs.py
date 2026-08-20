#!/usr/bin/env python3
"""Sync one section of content/docs/ from its anchor directory in the Go repo.

The Go repo (agentic_golang) is the single source of truth for documentation
prose. This site is a Hugo rendering of it, so every page here is the anchor
file plus three mechanical edits:

  1. the leading `# H1` is dropped (Hugo renders the title from frontmatter),
  2. Hugo frontmatter is prepended,
  3. relative `../foo/bar.md` links become `../../foo/bar/` — Hugo page URLs
     are directory-like, so a link needs one extra `..` to climb out.

Dates come from the anchor repo's git history, never from the clock:

    date     the commit that ADDED the file  (when the doc was written)
    lastmod  the commit that last CHANGED it (when the prose last moved)

Using the sync date instead would be wrong twice over — it invents a creation
date, and it bumps `lastmod` on every run even when the prose was untouched.
Reading git makes both fields truthful and makes the script idempotent: same
anchor commit in, same bytes out.

Because the transform is deterministic, this script is the whole sync: run it,
read the report, and the section matches the anchor. Files present here but not
in the anchor are stale and get deleted; `_index.md` is ours and is never
touched.

Usage:
    sync_anchor_docs.py <section> <anchor_dir> [--dry-run] [--date YYYY-MM-DD]

    section     directory name under content/docs/ (e.g. caller_insights)
    anchor_dir  absolute path to the matching dir in the Go repo
    --date      fallback date for files git cannot date (default: today)

Exit status is 0 when the sync succeeded (even with nothing to do), 1 on a
usage/IO error. Dead cross-references are reported, never silently dropped.
"""

from __future__ import annotations

import argparse
import datetime
import os
import re
import subprocess
import sys
from pathlib import Path

# Hugo root is the parent of scripts/.
HUGO_ROOT = Path(__file__).resolve().parent.parent
DOCS_ROOT = HUGO_ROOT / "content" / "docs"

# Words that look wrong in naive Title Case. Only consulted when minting a
# title for a brand-new page; an existing page keeps the title it already has.
ACRONYMS = {
    "api": "API",
    "cd": "CD",
    "ci": "CI",
    "cli": "CLI",
    "cpu": "CPU",
    "db": "DB",
    "dns": "DNS",
    "faq": "FAQ",
    "grpc": "gRPC",
    "http": "HTTP",
    "id": "ID",
    "io": "IO",
    "json": "JSON",
    "jsonless": "JSONless",
    "llm": "LLM",
    "ows": "OWS",
    "qa": "Q&A",
    "rag": "RAG",
    "rpc": "RPC",
    "sse": "SSE",
    "sql": "SQL",
    "ttl": "TTL",
    "url": "URL",
    "uuid": "UUID",
}

# A markdown link/image target that points at a local .md file, with an
# optional #fragment. Absolute URLs (scheme:) and bare fragments are skipped.
MD_LINK = re.compile(r"(!?\[[^\]]*\]\()([^)\s]+?\.md)(#[^)\s]*)?(\))")

# A relative link to a local file that is NOT markdown — nearly always a link
# into the Go source tree (`../../core/services.go`). Those paths exist in the
# Go repo but not on this site, so they 404 and there is no page to point them
# at; they get reported rather than rewritten. Anchored to `./` or `../` so it
# cannot match Go generic syntax like `[T any](...)` inside a code fence.
SRC_LINK = re.compile(r"!?\[[^\]]*\]\((\.\.?/[^)\s]*)\)")


def title_from_stem(stem: str) -> str:
    words = [w for w in re.split(r"[_\-\s]+", stem) if w]
    return " ".join(ACRONYMS.get(w.lower(), w.capitalize()) for w in words)


class GitDates:
    """Creation and last-change dates for anchor files, read from git.

    Falls back to `fallback` (today, normally) for anything git cannot date —
    an anchor that is not a repo, or a file not committed yet — and records a
    note so the sync report says so out loud instead of quietly inventing a
    date.
    """

    def __init__(self, anchor: Path, fallback: str) -> None:
        self.fallback = fallback
        self.notes: list[str] = []
        self.root = self._toplevel(anchor)
        if self.root is None:
            self.notes.append(f"{anchor} is not a git repo — dates fall back to {fallback}")

    @staticmethod
    def _run(cmd: list[str]) -> str:
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            return ""
        return proc.stdout.strip() if proc.returncode == 0 else ""

    @classmethod
    def _toplevel(cls, anchor: Path) -> Path | None:
        out = cls._run(["git", "-C", str(anchor), "rev-parse", "--show-toplevel"])
        return Path(out) if out else None

    def _log(self, rel: str, extra: list[str]) -> list[str]:
        cmd = ["git", "-C", str(self.root), "log", "--format=%ad", "--date=short"]
        out = self._run(cmd + extra + ["--", rel])
        return [line for line in out.split("\n") if line]

    def for_file(self, path: Path) -> tuple[str, str]:
        """Return (created, modified) as YYYY-MM-DD."""
        if self.root is None:
            return self.fallback, self.fallback
        try:
            rel = str(path.resolve().relative_to(self.root))
        except ValueError:
            self.notes.append(f"{path.name}: outside the anchor repo — dated {self.fallback}")
            return self.fallback, self.fallback

        # --follow tracks the file across renames, so a doc that was moved keeps
        # the date it was originally written rather than the date it was moved.
        adds = self._log(rel, ["--diff-filter=A", "--follow"])
        mods = self._log(rel, ["-1"])
        if not mods:
            self.notes.append(
                f"{path.name}: not committed in the anchor repo — dated {self.fallback}"
            )
            return self.fallback, self.fallback

        created, modified = (adds[-1] if adds else mods[-1]), mods[0]
        if self._run(["git", "-C", str(self.root), "status", "--porcelain", "--", rel]):
            self.notes.append(
                f"{path.name}: uncommitted changes in the anchor repo — lastmod set to "
                f"{self.fallback}; commit there and re-run to settle it"
            )
            modified = self.fallback
        # A doc rewritten before its add commit landed can read as modified
        # earlier than created; the earlier of the two is the honest creation.
        return min(created, modified), max(created, modified)


def split_frontmatter(text: str) -> tuple[dict[str, str], list[str], str]:
    """Return (parsed keys, raw frontmatter lines, body) for an existing page.

    Values stay as raw strings — we only ever read them back out verbatim, so
    there is no reason to pull in a YAML dependency.
    """
    if not text.startswith("---\n"):
        return {}, [], text
    end = text.find("\n---\n", 3)
    if end == -1:
        return {}, [], text
    raw = text[4:end].split("\n")
    body = text[end + 5 :]
    keys: dict[str, str] = {}
    for line in raw:
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            keys[k.strip()] = v.strip()
    return keys, raw, body


def strip_h1(text: str) -> str:
    """Drop a leading `# Heading` and the blank lines that followed it."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and lines[i].startswith("# "):
        i += 1
        while i < len(lines) and not lines[i].strip():
            i += 1
        return "\n".join(lines[i:])
    return "\n".join(lines[i:])


def rewrite_links(
    body: str, section: str, anchor_root: Path, incoming: set[str]
) -> tuple[str, list[str]]:
    """Point relative .md links at Hugo page URLs; report the ones that die.

    `anchor_root` is the anchor dir's parent — the Go repo's docs/ root — which
    is what a link like `../architectures/x.md` is relative to. `incoming` is
    the set of filenames this run is about to write into `section`, so a link
    to a sibling page created by the same run is not reported as missing.
    """
    dead: list[str] = []

    def repl(m: re.Match[str]) -> str:
        prefix, target, frag, suffix = m.group(1), m.group(2), m.group(3) or "", m.group(4)
        if "://" in target or target.startswith("/"):
            return m.group(0)

        # Resolve the target against the anchor section, then express it as a
        # path relative to the anchor docs root.
        resolved = os.path.normpath(os.path.join(section, target))
        if resolved.startswith(".."):
            dead.append(f"{target} — escapes the docs root")
            return m.group(0)

        parts = Path(resolved).parts
        if len(parts) == 2:
            tgt_section, tgt_stem = parts[0], Path(parts[1]).stem
        elif len(parts) == 1:
            tgt_section, tgt_stem = section, Path(parts[0]).stem
        else:
            dead.append(f"{target} — nested deeper than <section>/<page>.md")
            return m.group(0)

        tgt_file = f"{tgt_stem}.md"
        will_exist = tgt_section == section and tgt_file in incoming
        if not (anchor_root / tgt_section / tgt_file).exists():
            dead.append(f"{target} — missing in the anchor repo")
        elif not will_exist and not (DOCS_ROOT / tgt_section / tgt_file).exists():
            dead.append(f"{target} — section/page not published on this site")

        # Page URLs are /docs/<section>/<page>/, so a sibling page is ../<page>/
        # and a page in another section is ../../<section>/<page>/.
        if tgt_stem == "_index":
            url = f"../{tgt_section}/" if tgt_section != section else "../"
        elif tgt_section == section:
            url = f"../{tgt_stem}/"
        else:
            url = f"../../{tgt_section}/{tgt_stem}/"
        return f"{prefix}{url}{frag}{suffix}"

    # Scan the ORIGINAL body for relative links to non-markdown files. Scanning
    # the rewritten output instead would flag the correct Hugo URLs this pass
    # just produced, since those are relative and have no .md suffix.
    src = sorted(
        {t for t in SRC_LINK.findall(body) if not t.split("#")[0].rstrip("/").endswith(".md")}
    )
    for target in src:
        dead.append(f"{target} — source file, no page on this site to point at")
    return MD_LINK.sub(repl, body), dead


def render(body: str, existing: str | None, stem: str, created: str, modified: str) -> str:
    """Build the finished page: frontmatter + transformed body.

    `title` and `draft` are ours to keep — an editor may have shortened a title
    to fit the sidebar. `date` and `lastmod` belong to git and are overwritten
    every run; `lastmod` is omitted while a doc is still exactly as it was
    added, which is how a fresh page reads.
    """
    keys, raw, _ = split_frontmatter(existing or "")
    title = keys.get("title") or f'"{title_from_stem(stem)}"'
    fm = [f"title: {title}", f"date: {created}"]
    if modified != created:
        fm.append(f"lastmod: {modified}")
    fm.append(f"draft: {keys.get('draft', 'false')}")
    # Carry through anything else the page had set by hand (weight, tags, ...).
    handled = {"title", "date", "lastmod", "draft"}
    for line in raw:
        k = line.split(":", 1)[0].strip() if ":" in line else None
        if k and k not in handled and not line.startswith((" ", "\t")):
            fm.append(line.strip())
    return "---\n" + "\n".join(fm) + "\n---\n\n" + body


def describe_change(existing: str, body: str, created: str, modified: str) -> str:
    """Say what actually moved, so the report is reviewable at a glance."""
    keys, _, old_body = split_frontmatter(existing)
    what = []
    if old_body.strip() != body.strip():
        what.append("body")
    if keys.get("date") != created:
        what.append(f"date {keys.get('date', '—')}→{created}")
    old_mod = keys.get("lastmod", keys.get("date", "—"))
    if old_mod != modified:
        what.append(f"lastmod {old_mod}→{modified}")
    return ", ".join(what) or "frontmatter"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("section")
    ap.add_argument("anchor_dir")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    ap.add_argument("--date", help="fallback date for files git cannot date (YYYY-MM-DD)")
    args = ap.parse_args()

    fallback = args.date or datetime.date.today().isoformat()
    section = args.section.strip("/")
    anchor = Path(args.anchor_dir).resolve()
    target = DOCS_ROOT / section

    if not anchor.is_dir():
        print(f"error: anchor dir not found: {anchor}", file=sys.stderr)
        return 1
    if not DOCS_ROOT.is_dir():
        print(f"error: not a Hugo site: {DOCS_ROOT} missing", file=sys.stderr)
        return 1

    anchor_files = sorted(p for p in anchor.glob("*.md") if p.name != "_index.md")
    if not anchor_files:
        print(f"error: no .md files in {anchor}", file=sys.stderr)
        return 1
    nested = sorted(p.relative_to(anchor) for p in anchor.rglob("*.md") if p.parent != anchor)

    dates = GitDates(anchor, fallback)
    anchor_names = {p.name for p in anchor_files}
    created, updated, unchanged, deleted = [], [], [], []
    dead: dict[str, list[str]] = {}

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)

    for src in anchor_files:
        raw = src.read_text(encoding="utf-8")
        body, page_dead = rewrite_links(strip_h1(raw), section, anchor.parent, anchor_names)
        if page_dead:
            dead[src.name] = page_dead

        dst = target / src.name
        existing = dst.read_text(encoding="utf-8") if dst.exists() else None
        born, changed = dates.for_file(src)
        out = render(body, existing, src.stem, born, changed)

        if existing is None:
            created.append(f"{src.name} ({born})")
        elif existing == out:
            unchanged.append(src.name)
            continue
        else:
            updated.append(f"{src.name} ({describe_change(existing, body, born, changed)})")
        if not args.dry_run:
            dst.write_text(out, encoding="utf-8")

    if target.is_dir():
        for existing_page in sorted(target.glob("*.md")):
            if existing_page.name == "_index.md" or existing_page.name in anchor_names:
                continue
            deleted.append(existing_page.name)
            if not args.dry_run:
                existing_page.unlink()

    index = target / "_index.md"
    index_note = ""
    if not index.exists():
        index_note = f"_index.md missing — write one (title + one-line blurb) at {index}"

    tag = "DRY RUN " if args.dry_run else ""
    print(f"{tag}sync {section} <- {anchor}")
    for label, names in (
        ("created", created),
        ("updated", updated),
        ("deleted", deleted),
        ("unchanged", unchanged),
    ):
        if names:
            print(f"  {label:9} {len(names):>2}: {', '.join(names)}")
    if not (created or updated or deleted):
        print("  already in sync")
    if nested:
        print("  NESTED (not synced, flat sections only): " + ", ".join(map(str, nested)))
    if dates.notes:
        print("  DATES (git could not date these):")
        for note in dates.notes:
            print(f"    {note}")
    if dead:
        print("  DEAD LINKS (rewritten, but the target is not published — needs a human):")
        for name, items in dead.items():
            for item in items:
                print(f"    {name}: {item}")
    if index_note:
        print(f"  TODO {index_note}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
