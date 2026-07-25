#!/usr/bin/env python3
"""Sync a docs section from the Go repo into the Hugo site.

    python3 sync_docs.py <section> [--apply]

Source : ~/agentic_golang/docs/<section>/*.md      (no front matter, leading "# H1")
Target : ~/agentic/hugo_docs/content/docs/<section>/*.md   (Hugo front matter)

Rules
  - The Go repo is the source of truth for BODY text.
  - An existing page keeps its `title` and `date` so sidebar labels and ordering
    do not churn; `lastmod` records the sync.
  - A new page gets a title from TITLES below, else from its H1, and today's date.
  - The leading H1 is dropped: the theme already renders the front-matter title.
  - Relative *.md links are rewritten to Hugo page URLs.
  - `_index.md` is Hugo-only and is never overwritten.
  - Target files with no source counterpart are reported, not deleted.
"""
import datetime
import pathlib
import re
import sys

SRC_ROOT = pathlib.Path.home() / "agentic_golang" / "docs"
DST_ROOT = pathlib.Path.home() / "agentic" / "hugo_docs" / "content" / "docs"
TODAY = "2026-07-25"

# Concise sidebar titles for pages that would otherwise inherit a long H1.
TITLES = {
    "caller_insights/go_closures.md": "Go Closures",
    "architectures/custom_pipeline_vs_frameworks.md": "Custom Pipeline vs Frameworks",
    "architectures/proactive_cancellation.md": "Proactive Cancellation",
    "general_go/generics.md": "Generics",
    "python_stuff/python_workers.md": "Python Workers",
    "frequently_asked/rag_stream_qa.md": "RAG Stream Q&A",
    "frequently_asked/tool_streaming_adapter_qa.md": "Tool Streaming Adapter Q&A",
}


def front_matter(text):
    m = re.match(r"---\n(.*?)\n---\n?", text, re.S)
    if not m:
        return {}, text
    fm = {}
    for line in m.group(1).split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"')
    return fm, text[m.end():]


def rewrite_links(body, section):
    """../architectures/foo.md#x -> ../../architectures/foo/#x ; foo.md -> ../foo/"""
    def sub(m):
        label, target = m.group(1), m.group(2)
        if re.match(r"^(https?:|mailto:|#|/)", target):
            return m.group(0)
        path, _, anchor = target.partition("#")
        if not path.endswith(".md"):
            return m.group(0)
        parts = [p for p in path.split("/") if p not in ("", ".")]
        name = parts[-1][:-3]
        # section the target lives in, relative to docs/
        up = parts.count("..")
        rest = [p for p in parts[:-1] if p != ".."]
        tgt_section = rest[0] if (up and rest) else section
        url = f"../{name}/" if tgt_section == section else f"../../{tgt_section}/{name}/"
        if anchor:
            url += "#" + anchor
        return f"[{label}]({url})"

    return re.sub(r"\[([^\]]*)\]\(([^)]+)\)", sub, body)


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    section = sys.argv[1]
    apply = "--apply" in sys.argv
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    src_dir, dst_dir = SRC_ROOT / section, DST_ROOT / section
    if not src_dir.is_dir():
        sys.exit(f"no source dir: {src_dir}")
    dst_dir.mkdir(parents=True, exist_ok=True)

    srcs = sorted(p for p in src_dir.glob("*.md") if only is None or p.name == only)
    added = updated = same = 0

    for src in srcs:
        dst = dst_dir / src.name
        raw = src.read_text(encoding="utf-8")

        # Drop the leading H1 and remember it.
        h1 = ""
        m = re.match(r"\s*#\s+(.+?)\n+", raw)
        if m:
            h1 = m.group(1).strip()
            raw = raw[m.end():]

        body = rewrite_links(raw.strip(), section) + "\n"

        if dst.exists():
            old_fm, old_body = front_matter(dst.read_text(encoding="utf-8"))
            title = old_fm.get("title") or TITLES.get(f"{section}/{src.name}") or h1
            date = old_fm.get("date", TODAY)
            state = "same" if old_body.strip() == body.strip() else "update"
        else:
            title = TITLES.get(f"{section}/{src.name}") or h1 or src.stem
            date = TODAY
            state = "add"

        fm = [f'title: "{title}"', f"date: {date}"]
        if state != "add":
            fm.append(f"lastmod: {TODAY}")
        fm.append("draft: false")
        out = "---\n" + "\n".join(fm) + "\n---\n\n" + body

        if state == "same":
            same += 1
        else:
            added += state == "add"
            updated += state == "update"
            if apply:
                dst.write_text(out, encoding="utf-8")
        print(f"  {state:6s} {src.name:38s} title={title!r}")

    src_names = {p.name for p in src_dir.glob("*.md")}
    orphans = [p.name for p in sorted(dst_dir.glob("*.md"))
               if p.name not in src_names and p.name != "_index.md"]

    print(f"\n{section}: {added} added, {updated} updated, {same} unchanged"
          f"{'' if apply else '   (DRY RUN - pass --apply)'}")
    if orphans:
        print("  no source counterpart (delete manually if retired): " + ", ".join(orphans))


if __name__ == "__main__":
    main()
