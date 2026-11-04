"""python3 htmltext.py FILE [MAX_LINES]: the text a person would read on a rendered HTML page, one block per line.

Hugo pages carry inline scripts (mermaid init, popup bodies in <script type="text/html">) and styles;
only what a reader sees is printed, so scripts, styles and templates are dropped.
"""
import sys
from html.parser import HTMLParser

SKIP = {"script", "style", "template", "noscript", "svg"}
BLOCK = {"p", "div", "li", "tr", "h1", "h2", "h3", "h4", "section", "article", "header", "footer", "br", "td", "th", "button", "a"}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.out = [""]

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skip += 1
        elif tag in BLOCK:
            self.out.append("")
        label = dict(attrs).get("aria-label")
        if label and not self.skip:
            self.out[-1] += f" [{label}]"

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in BLOCK:
            self.out.append("")

    def handle_data(self, data):
        if not self.skip:
            self.out[-1] += " " + data.strip() if data.strip() else ""


t = Text()
t.feed(open(sys.argv[1], encoding="utf-8", errors="replace").read())
lines = [" ".join(line.split()) for line in t.out]
lines = [line for line in lines if line]
# The cap lives here, not in a `| head` after us: under pipefail a closed pipe aborts the caller.
limit = int(sys.argv[2]) if len(sys.argv) > 2 else len(lines)
print("\n".join(lines[:limit]))
if len(lines) > limit:
    print(f"[... {len(lines) - limit} more lines in the html file]")
