---
description: Sync one content/docs section from its anchor directory in the Go repo
argument-hint: <section> <anchor_absolute_dir>
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

# Update Hugo Docs Command

Sync a section of `hugo_docs/content/docs/` so it matches its anchor directory,
which always wins. Anchor = the matching directory in the Go repo
(`/home/miftah/agentic_golang/docs/<section>`). This repo is a Hugo *rendering*
of those files, never an independent copy — so a page here that the anchor no
longer has is stale and goes away, and a page the anchor added shows up here.

## Arguments

`$ARGUMENTS` is two whitespace-separated tokens — read them as SECTION and
ANCHOR, and use those two values everywhere below:

- **SECTION** — section directory name under `content/docs/` (e.g. `caller_insights`)
- **ANCHOR** — absolute path to the anchor directory (e.g. `/home/miftah/agentic_golang/docs/caller_insights`)

Do not rely on `$1`/`$2`; parse `$ARGUMENTS` yourself. If a token is missing,
ask for it — do not guess the anchor path. If the user names several sections,
run the whole process below once per section.

## The transform is mechanical — do not hand-edit pages

Every page here is its anchor file plus exactly three edits:

1. the leading `# H1` is dropped (Hugo renders the title from frontmatter),
2. Hugo frontmatter is prepended,
3. relative `../foo/bar.md` links become `../../foo/bar/` — Hugo page URLs are
   directory-like (`/docs/<section>/<page>/`), so a cross-section link needs one
   extra `..` to climb out, and a same-section link becomes `../<page>/`.

`hugo_docs/scripts/sync_anchor_docs.py` implements all three. Run it; never
retype prose by hand, and never "improve" the wording while syncing — divergence
from the anchor is the one failure mode this command exists to prevent. If the
prose is wrong, it gets fixed in the Go repo and synced back down.

## Dates come from the anchor's git log, not from the clock

    date     the anchor commit that ADDED the file  (when the doc was written)
    lastmod  the anchor commit that last CHANGED it (when the prose last moved)

Never stamp the sync date. It invents a creation date, and it bumps `lastmod`
on every run even when nothing was touched — a page then claims to have been
revised on a day nobody edited it. Reading git makes both fields true and makes
the sync idempotent: same anchor commit in, same bytes out. The script does this
for you; `--date` is only the fallback for a file git cannot date (uncommitted,
or an anchor that is not a repo), and it reports every such case under `DATES`.

`lastmod` is omitted while a page is still byte-identical to the commit that
added it. `title` and `draft` stay as they are here — a title may have been
shortened for the sidebar — and any other hand-set key is carried through.

## Process

### 1. Dry run first

```bash
cd /home/miftah/agentic/hugo_docs
python3 scripts/sync_anchor_docs.py SECTION ANCHOR --dry-run
```

Read the report. It lists `created` / `updated` / `deleted` / `unchanged`, plus
any `DATES`, `DEAD LINKS`, `NESTED` files, or a missing `_index.md`. Each
`updated` entry says what moved — `body`, `date x→y`, `lastmod x→y` — so a
frontmatter-only run is obvious at a glance. If it says `already in sync` with
no warnings, stop here and say so — that is a valid, complete outcome. Do not
invent work.

### 2. Sanity-check the deletions

Anything under `deleted` is about to be removed from the site. Confirm each one
really is absent from the anchor (`ls ANCHOR`) rather than merely renamed. A rename
shows up as one delete plus one create — that is fine and expected, but say so in
the summary so the user knows a URL changed.

### 3. Apply

```bash
python3 scripts/sync_anchor_docs.py SECTION ANCHOR
```

The script is idempotent: a page whose body already matches is left completely
untouched, so `lastmod` does not churn and `git status` stays honest.

### 4. Resolve what the script deliberately left alone

The script reports these and refuses to guess — handle each one:

- **DEAD LINKS.** The URL was rewritten to Hugo form, but the target is missing
  in the anchor repo or lives in a section this site does not publish — so it
  will 404. Fix by pointing it at the right page, or by unlinking it (keep the
  text, drop the `[...](...)`) — *in the anchor repo*, then re-run this command.
  Only patch it locally if the user says to; the local edit will be overwritten
  by the next sync.
- **NESTED files.** Sections here are flat. If the anchor grew a subdirectory,
  ask the user whether to flatten the names or add a nested section.
- **Missing `_index.md`.** Write one for a brand-new section: `title` matching
  the other sections' style plus a one-line blurb. `_index.md` is ours — the
  script never touches or deletes it.
- **DATES.** A file git could not date fell back to today. Usually it means the
  doc is not committed in the Go repo yet: commit it there and re-run, which
  replaces the guess with the real date.

### 5. Check new pages' title

For a `created` page the script mints `title` from the filename
(`rag_stream.md` → `RAG Stream`). Read the new page's `# H1` in the anchor and
confirm the short title reads sensibly in the sidebar; adjust if not. An
existing page keeps whatever title it already had — leave it.

### 6. Report

Summarize: which pages were created / updated / deleted, any URL changes from
renames, and anything from step 4 still outstanding. If a section was added or
retired, note that `/home/miftah/agentic/CLAUDE.md` lists the sections under
`content/docs/` and may need the same edit.

## Do not

- **Do not run `/usr/bin/hugo`** to verify. It is v0.123.7 and cannot render the
  Stack theme; CI builds the live site with `latest`. This command only touches
  markdown under `content/`, so there is nothing a local build would catch. If a
  render check is genuinely needed, download a v0.164.0 extended binary into the
  scratchpad — and never pass `--gc`, which wipes the committed
  `resources/_gen/` cache.
- **Do not touch `hugo_docs/public/`.** It is gitignored and rebuilt by CI.
- **Do not commit** unless the user asks (they type `p` for that).
