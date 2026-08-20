#!/usr/bin/env python3
"""
Generate the Open Graph / link-preview card for the landing page.

Writes static/og-image.png (1200x630), the size LinkedIn, Slack, X and
Facebook all read from <meta property="og:image">. Without it those
scrapers find no artwork and render an empty thumbnail placeholder.

The card is drawn, not photographed: it reuses the tokens from
static/style.css (warm off-white canvas, hairline structure, one green
accent, Space Grotesk + IBM Plex) so the preview and the page it links
to read as the same object. Text is drawn with the real webfonts rather
than generated, so it stays legible at thumbnail size.

Fonts are fetched once into scripts/.fontcache/ (gitignored).

    python3 scripts/gen_og_image.py
"""

import os
import sys
import urllib.request
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CACHE = os.path.join(HERE, ".fontcache")
OUT = os.path.join(ROOT, "static", "og-image.png")

# Supersample, then downscale: hairlines and small mono labels land on
# fractional pixels at 1x and go chunky. Drawing at 2x and resampling
# gives them proper antialiasing.
S = 2
W, H = 1200, 630

# --- Tokens, lifted from static/style.css --------------------------------
CANVAS      = (251, 251, 249)
SURFACE     = (255, 255, 255)
INK         = (20, 22, 26)
INK_SOFT    = (86, 91, 99)
INK_FAINT   = (138, 143, 152)
LINE        = (228, 226, 219)
LINE_STRONG = (207, 205, 196)
ACCENT      = (46, 111, 94)
ACCENT_WASH = (236, 242, 239)
GRID        = (238, 237, 230)

FONTS = {
    "display": ("SpaceGrotesk-Bold.ttf",
                "https://fonts.gstatic.com/s/spacegrotesk/v22/"
                "V8mQoQDjQSkFtoMM3T6r8E7mF71Q-gOoraIAEj4PVksj.ttf"),
    "sans": ("IBMPlexSans-Regular.ttf",
             "https://fonts.gstatic.com/s/ibmplexsans/v23/"
             "zYXGKVElMYYaJe8bpLHnCwDKr932-G7dytD-Dmu1swZSAXcomDVmadSD6llzAA.ttf"),
    "sans_semi": ("IBMPlexSans-SemiBold.ttf",
                  "https://fonts.gstatic.com/s/ibmplexsans/v23/"
                  "zYXGKVElMYYaJe8bpLHnCwDKr932-G7dytD-Dmu1swZSAXcomDVmadSDNF5zAA.ttf"),
    "mono": ("IBMPlexMono-Regular.ttf",
             "https://fonts.gstatic.com/s/ibmplexmono/v20/"
             "-F63fjptAgt5VM-kVkqdyU8n5ig.ttf"),
    "mono_med": ("IBMPlexMono-Medium.ttf",
                 "https://fonts.gstatic.com/s/ibmplexmono/v20/"
                 "-F6qfjptAgt5VM-kVkqdyU8n3twJ8lc.ttf"),
}


def font(key, size):
    name, url = FONTS[key]
    path = os.path.join(CACHE, name)
    if not os.path.exists(path):
        os.makedirs(CACHE, exist_ok=True)
        sys.stderr.write("fetching %s\n" % name)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(path, "wb") as f:
            f.write(r.read())
    return ImageFont.truetype(path, int(size * S))


def tracked(d, xy, text, f, fill, track=0.0):
    """Draw text with letter-spacing. PIL has no tracking, so step glyphs
    manually; the uppercase mono labels need it to not look cramped."""
    x, y = xy
    step = track * f.size
    for ch in text:
        d.text((x, y), ch, font=f, fill=fill)
        x += f.getlength(ch) + step
    return x


def tracked_width(text, f, track=0.0):
    return sum(f.getlength(c) for c in text) + track * f.size * max(len(text) - 1, 0)


def arrow(d, x, y, w, color):
    """Hairline arrow, vertically centred on y."""
    d.line([(x, y), (x + w - 5 * S, y)], fill=color, width=max(1, S // 2))
    tip = x + w
    d.polygon([(tip, y), (tip - 6 * S, y - 4 * S), (tip - 6 * S, y + 4 * S)], fill=color)


def mark(d, x, y, size, color):
    """The layered-cube glyph from the page's icon sprite (#ic-architecture),
    hand-plotted so the card carries the same mark as the site."""
    u = size / 24.0
    def p(px, py):
        return (x + px * u, y + py * u)
    w = max(1, int(1.9 * u))
    d.polygon([p(12, 2), p(2, 7), p(12, 12), p(22, 7)], outline=color, width=w)
    d.line([p(2, 12), p(12, 17), p(22, 12)], fill=color, width=w, joint="curve")
    d.line([p(2, 17), p(12, 22), p(22, 17)], fill=color, width=w, joint="curve")


def main():
    img = Image.new("RGB", (W * S, H * S), CANVAS)
    d = ImageDraw.Draw(img)

    PAD = 72 * S

    # Faint dot grid — the "control plane" texture, barely there.
    for gy in range(0, H * S, 28 * S):
        for gx in range(0, W * S, 28 * S):
            d.rectangle([gx, gy, gx + S - 1, gy + S - 1], fill=GRID)

    # Accent rule across the top: the one piece of brand colour that
    # survives however aggressively a scraper crops the thumbnail.
    d.rectangle([0, 0, W * S, 9 * S], fill=ACCENT)

    # --- Eyebrow row: mark + wordmark, tech stack right-aligned ----------
    f_word = font("mono_med", 21)
    f_stack = font("mono", 15)
    y = 52 * S

    mark(d, PAD, y - 2 * S, 26 * S, ACCENT)
    tracked(d, (PAD + 38 * S, y), "tuntun-go-chatbot", f_word, INK, track=0.01)

    stack = "GO · GIN · LANGCHAINGO · GEMINI · ARANGODB · REDIS"
    sw = tracked_width(stack, f_stack, 0.09)
    tracked(d, (W * S - PAD - sw, y + 5 * S), stack, f_stack, INK_FAINT, track=0.09)

    # --- Headline --------------------------------------------------------
    f_h = font("display", 71)
    y = 116 * S
    for line in ("High-concurrency agentic", "engine, built in Go."):
        d.text((PAD, y), line, font=f_h, fill=INK)
        y += 82 * S

    # --- Lede ------------------------------------------------------------
    f_lede = font("sans", 25)
    y = 292 * S
    for line in ("Plan-and-execute, multimodal, thirty registered tools —",
                 "an agentic engine for Indonesian equity-market workloads."):
        d.text((PAD, y), line, font=f_lede, fill=INK_SOFT)
        y += 35 * S

    # --- Request-lifecycle rail -----------------------------------------
    # The page's signature graphic, compressed to five nodes. The cache
    # fast-lane is the one filled node because it is the one path that
    # bypasses the processing semaphore.
    nodes = [
        ("ENTRY", "Admission", False),
        ("HOT",   "Cache lane", True),
        ("QUEUE", "FIFO · 100", False),
        ("WORK",  "Agents × 2", False),
        ("OUT",   "SSE stream", False),
    ]
    gap = 30 * S
    avail = W * S - 2 * PAD
    nw = (avail - gap * (len(nodes) - 1)) / len(nodes)
    nh = 74 * S
    ry = 402 * S

    f_lab = font("mono_med", 12)
    f_tit = font("sans_semi", 19)

    x = PAD
    for i, (label, title, hot) in enumerate(nodes):
        fill = ACCENT_WASH if hot else SURFACE
        edge = ACCENT if hot else LINE_STRONG
        d.rounded_rectangle([x, ry, x + nw, ry + nh], radius=5 * S,
                            fill=fill, outline=edge, width=max(1, S))
        tracked(d, (x + 15 * S, ry + 14 * S), label, f_lab,
                ACCENT if hot else INK_FAINT, track=0.14)
        d.text((x + 15 * S, ry + 36 * S), title, font=f_tit,
               fill=INK if not hot else ACCENT)
        if i < len(nodes) - 1:
            arrow(d, x + nw + 8 * S, ry + nh / 2, gap - 16 * S, LINE_STRONG)
        x += nw + gap

    # --- Footer: metrics left, URL right --------------------------------
    d.line([(PAD, 524 * S), (W * S - PAD, 524 * S)], fill=LINE, width=max(1, S))

    f_num = font("mono_med", 20)
    f_cap = font("sans", 17)
    y = 550 * S
    x = PAD
    for num, cap in (("50", "concurrent"), ("5", "stream workers"),
                     ("100", "deep queue"), ("30", "tools")):
        d.text((x, y - 1 * S), num, font=f_num, fill=ACCENT)
        x += f_num.getlength(num) + 7 * S
        d.text((x, y + 2 * S), cap, font=f_cap, fill=INK_SOFT)
        x += f_cap.getlength(cap) + 22 * S

    url = "miftahulmahfuzh.github.io/agentic"
    f_url = font("mono", 17)
    uw = tracked_width(url, f_url, 0.02)
    tracked(d, (W * S - PAD - uw, y + 2 * S), url, f_url, INK_FAINT, track=0.02)

    img.resize((W, H), Image.LANCZOS).save(OUT, optimize=True)
    print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
