"""python3 links.py BUILD_DIR BASE_URL: check every internal link and asset in a built Hugo site.

BUILD_DIR is a `hugo --destination` output; BASE_URL is the baseURL it was built with
(http://localhost:PORT/agentic/). A link is internal when it is relative, root-relative under the
base path, or absolute on the base URL. Each one must resolve to a file in BUILD_DIR, and its
#fragment (when it names another page or this one) must match an id or name on that page.
External links are listed by host and never fetched.

Exit 0 when every internal link resolves, 1 otherwise.
"""
import os
import sys
from collections import Counter
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for key in ("id", "name"):
            if a.get(key):
                self.ids.add(a[key])
        for key in ("href", "src"):
            v = a.get(key)
            # rel=preconnect/dns-prefetch name an origin, not a resource.
            if v and not (tag == "link" and a.get("rel") in ("preconnect", "dns-prefetch")):
                self.links.append((tag, key, v.strip()))


def parse(path):
    p = Page()
    p.feed(open(path, encoding="utf-8", errors="replace").read())
    return p


def target_file(build, base_path, url_path):
    path = unquote(url_path)
    if path == base_path.rstrip("/"):
        path = base_path  # /agentic is the site root; every static host redirects it to /agentic/
    if not path.startswith(base_path):
        return None
    rel = path[len(base_path):]
    cand = os.path.join(build, rel)
    if rel == "" or rel.endswith("/"):
        cand = os.path.join(cand, "index.html")
    elif os.path.isdir(cand):
        cand = os.path.join(cand, "index.html")
    return cand


def main():
    build, base = sys.argv[1], sys.argv[2]
    base_split = urlsplit(base)
    origin = f"{base_split.scheme}://{base_split.netloc}"
    base_path = base_split.path if base_split.path.endswith("/") else base_split.path + "/"

    pages = {}
    for d, _, files in os.walk(build):
        for f in files:
            if f.endswith(".html"):
                pages[os.path.join(d, f)] = None

    cache = {}

    def page(path):
        if path not in cache:
            cache[path] = parse(path)
        return cache[path]

    broken, bad_anchor = [], []
    external = Counter()
    checked = 0
    for path in sorted(pages):
        rel = os.path.relpath(path, build).replace(os.sep, "/")
        page_url = origin + base_path + (rel[: -len("index.html")] if rel.endswith("index.html") else rel)
        for tag, key, v in page(path).links:
            if v.startswith(("mailto:", "javascript:", "data:", "tel:")):
                continue
            absu = urljoin(page_url, v)
            s = urlsplit(absu)
            if f"{s.scheme}://{s.netloc}" != origin:
                external[s.netloc] += 1
                continue
            checked += 1
            tf = target_file(build, base_path, s.path)
            if tf is None or not os.path.isfile(tf):
                broken.append(f"{rel}: <{tag} {key}={v!r}> -> {s.path} (no file)")
                continue
            if s.fragment and tf.endswith(".html"):
                frag = unquote(s.fragment)
                if frag not in page(tf).ids:
                    bad_anchor.append(f"{rel}: <{tag} {key}={v!r}> -> #{frag} not on {os.path.relpath(tf, build)}")

    print(f"pages       {len(pages)}")
    print(f"internal    {checked} links/assets checked")
    print(f"broken      {len(broken)}")
    for b in broken:
        print(f"  {b}")
    print(f"anchors     {len(bad_anchor)} missing")
    for b in bad_anchor:
        print(f"  {b}")
    print("external    " + ", ".join(f"{h} x{n}" for h, n in external.most_common()) if external else "external    none")
    return 1 if broken or bad_anchor else 0


if __name__ == "__main__":
    sys.exit(main())
