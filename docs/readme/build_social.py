#!/usr/bin/env python3
"""The link previews: the card GitHub, LinkedIn and X show when a link is shared.

    python docs/readme/build_social.py   # writes docs/readme/social-preview.svg and og.svg

Two cards from one drawing, both the capture page's welcome held still:
- social-preview (1280x640): the repository's. GitHub takes a PNG under 1 MB, uploaded
  by hand in Settings > Social preview (the API has no endpoint for it).
- og (1200x630): the capture page's (web/icons/og.png, named in web/index.html).

Rasterize each with headless Chrome:

    chrome --headless --hide-scrollbars --force-device-scale-factor=1 --window-size=1280,640 \\
        --screenshot=docs/readme/social-preview.png docs/readme/social-preview.svg
    chrome --headless --hide-scrollbars --force-device-scale-factor=1 --window-size=1200,630 \\
        --screenshot=web/icons/og.png docs/readme/og.svg

They are drawn in the page's dark tokens (web/style.css, through page_tokens.py): the
grid, saved things floating at the sides (near ones sharp, far ones faint and out of
focus), a pill with the address, the welcome's title with its accent line, a tagline
and the four stages of the loop, the last one in the accent. Margins keep the words
clear of the ~2% LinkedIn crops off each side of a 2:1 image.
"""
from __future__ import annotations

from html import escape
from pathlib import Path

from page_tokens import MONO, SANS, tokens

HERE = Path(__file__).resolve().parent
C = tokens("dark")
TITLE = ["Save what catches your eye.", "Build with it."]
STAGES = ["Share", "Read", "Distill", "Build"]

CARDS = {  # name: (address pill, tagline lines, size)
    "social-preview": ("albegosu/second-brain",
                       ["Save UI inspiration from any app. A vision model curates it into a private",
                        "wiki and turns your taste into a DESIGN.md your coding agent builds from."],
                       (1280, 640)),
    "og": ("albegosu.github.io/second-brain",
           ["Share a link, a post or an image from Android or any browser.",
            "A vision model files it into your private wiki."],
           (1200, 630)),
}

# Ink pictures stay dark in both themes, as screenshots would; these are the page's art tokens.
INK, INK_CELL = "#141414", "#262626"
HOT, BLUE, RED, CYAN, GREEN = "#ec810c", "#2e61f8", "#d45c49", "#26b5c4", "#3fbf74"


# ── The saved things: each a 206x124 picture ────────────────────────────────
def art(kind: str) -> str:
    if kind == "gradient":
        return (f'<rect width="206" height="124" fill="{INK}"/><g filter="url(#soft)">'
                f'<circle cx="52" cy="76" r="44" fill="{HOT}"/><circle cx="112" cy="90" r="44" fill="{RED}"/>'
                f'<circle cx="164" cy="40" r="46" fill="{BLUE}"/></g>')
    if kind == "bento":
        return (f'<rect width="206" height="124" fill="{INK}"/>'
                f'<defs><linearGradient id="tall" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="{BLUE}"/>'
                f'<stop offset="1" stop-color="#2450cc"/></linearGradient></defs>'
                f'<rect x="7" y="7" width="70" height="110" rx="6" fill="url(#tall)"/>'
                f'<rect x="82" y="7" width="56" height="52" rx="6" fill="{INK_CELL}"/>'
                f'<rect x="143" y="7" width="56" height="52" rx="6" fill="{INK_CELL}"/>'
                f'<rect x="90" y="40" width="22" height="5" rx="2" fill="{CYAN}"/>'
                f'<rect x="82" y="65" width="117" height="52" rx="6" fill="{INK_CELL}"/>'
                f'<rect x="90" y="88" width="64" height="6" rx="3" fill="{HOT}"/>')
    if kind == "type":
        return (f'<rect width="206" height="124" fill="#fedcc3"/>'
                f'<text x="103" y="80" text-anchor="middle" class="sans" font-size="64" font-weight="600" '
                f'letter-spacing="-2.5" fill="#3a3a3c">Aa</text><rect x="71" y="96" width="64" height="3" fill="{HOT}"/>')
    if kind == "cmdk":
        rows = "".join(f'<rect x="22" y="{y}" width="{w}" height="6" rx="3" fill="#3a3a3a"/>' for y, w in [(77, 100), (101, 90)])
        return (f'<rect width="206" height="124" fill="{INK}"/>'
                f'<rect x="12" y="12" width="182" height="26" rx="6" fill="#1e1e1e" stroke="#333"/>'
                f'<rect x="22" y="22" width="73" height="6" rx="3" fill="#5a5a5a"/>'
                f'<rect x="12" y="46" width="182" height="20" rx="6" fill="{HOT}" fill-opacity=".28"/>'
                f'<rect x="22" y="53" width="100" height="6" rx="3" fill="#5a5a5a"/>{rows}')
    if kind == "radar":
        return (f'<rect width="206" height="124" fill="{INK}"/>'
                f'<circle cx="103" cy="62" r="52" fill="none" stroke="#3a3a3a"/>'
                f'<circle cx="103" cy="62" r="34" fill="none" stroke="#2c2c2c"/>'
                f'<circle cx="103" cy="62" r="17" fill="none" stroke="#2c2c2c"/>'
                f'<path d="M51 62H155M103 10V114" stroke="#2c2c2c"/>'
                f'<path d="M103 62L103 10A52 52 0 0 1 148 36Z" fill="{GREEN}" fill-opacity=".4"/>'
                f'<circle cx="124" cy="40" r="3.5" fill="{GREEN}"/>')
    if kind == "menu":
        pills = "".join(f'<rect x="{x}" y="20" width="38" height="22" rx="11" fill="{fill}"/>'
                        for x, fill in [(13, C["outline"]), (57, C["on-surface"]), (101, C["outline"]), (145, C["outline"])])
        return (f'<rect width="206" height="124" fill="{C["neutral"]}"/>{pills}'
                f'<rect x="57" y="52" width="112" height="58" rx="10" fill="{C["surface"]}" stroke="{C["outline"]}"/>'
                f'<rect x="69" y="65" width="64" height="6" rx="3" fill="{C["outline"]}"/>'
                f'<rect x="69" y="78" width="46" height="6" rx="3" fill="{C["outline"]}"/>'
                f'<rect x="69" y="91" width="56" height="6" rx="3" fill="{HOT}"/>')
    if kind == "swatches":
        return "".join(f'<rect x="{i * 41.2:g}" width="41.2" height="124" fill="{c}"/>'
                       for i, c in enumerate(["#f3f3f3", "#fedcc3", HOT, RED, "#2450cc"]))
    raise ValueError(kind)


def card(x: float, y: float, kind: str, title: str, label: str, rot: float = 0, scale: float = 1,
         blur: float = 0, opacity: float = 1) -> str:
    """A saved thing as the page's drift draws it: a 220px card, its picture, its name and kind."""
    blur_attr = f' filter="url(#b{str(blur).replace(".", "_")})"' if blur else ""
    return (f'<g transform="translate({x:g} {y:g}) rotate({rot:g} 110 92) scale({scale:g})" opacity="{opacity:g}"{blur_attr}>'
            f'<rect x=".5" y=".5" width="219" height="183" rx="16" fill="{C["surface"]}" stroke="{C["outline"]}"/>'
            f'<g transform="translate(7 7)" clip-path="url(#art)">{art(kind)}</g>'
            f'<text x="12" y="153" class="sans" font-size="13" font-weight="600" fill="{C["on-surface"]}">{escape(title)}</text>'
            f'<text x="12" y="170" class="sans" font-size="12" font-weight="500" fill="{C["muted"]}">{escape(label)}</text>'
            f"</g>")


def width(s: str, size: float, per: float = 0.56) -> float:
    """A rough advance width for centering pills: the fallback sans averages ~0.56em a character."""
    return len(s) * size * per


def svg(name: str) -> str:
    pill, tagline, (w, h) = CARDS[name]
    cx = w / 2
    sx = w / 1280  # the side cards keep their place on a narrower canvas
    blurs = sorted({1.5, 3, 3.5})
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">',
        f"<style>.sans{{font-family:{SANS}}}.mono{{font-family:{MONO}}}</style>",
        "<defs>",
        '<pattern id="grid" width="48" height="48" patternUnits="userSpaceOnUse" x="16"><path d="M48 0H0V48" fill="none" '
        'stroke="#ffffff" stroke-opacity=".07"/></pattern>',
        '<radialGradient id="fade" cx="50%" cy="0" r="85%"><stop offset="0" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
        f'<mask id="top"><rect width="{w}" height="{h}" fill="url(#fade)"/></mask>',
        f'<radialGradient id="clear" cx="50%" cy="52%" r="50%" gradientTransform="translate(0 0)">'
        f'<stop offset=".45" stop-color="{C["neutral"]}"/><stop offset="1" stop-color="{C["neutral"]}" stop-opacity="0"/></radialGradient>',
        '<filter id="soft" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="16"/></filter>',
        *(f'<filter id="b{str(b).replace(".", "_")}" x="-20%" y="-20%" width="140%" height="140%">'
          f'<feGaussianBlur stdDeviation="{b}"/></filter>' for b in blurs),
        '<clipPath id="art"><rect width="206" height="124" rx="10"/></clipPath>',
        "</defs>",
        f'<rect width="{w}" height="{h}" fill="{C["neutral"]}"/>',
        f'<rect width="{w}" height="{h}" fill="url(#grid)" mask="url(#top)"/>',
        # Far, then near: the depth comes from size, focus and how faint each is, never a shadow.
        card(250 * sx, -18, "menu", "Morphing menu", "Pattern", rot=3, scale=0.7, blur=3, opacity=0.5),
        card(850 * sx, -24, "swatches", "Warm palette", "Visual style", rot=-2, scale=0.68, blur=3.5, opacity=0.5),
        card(215 * sx, 470, "radar", "Radar alerts", "Pattern", rot=-3, scale=0.78, blur=1.5, opacity=0.7),
        card(-46, 70, "gradient", "Liquid gradient", "Visual style", rot=-4),
        card(24, 366, "bento", "Bento dashboard", "Visual style", rot=2, scale=0.96),
        card(w - 196, 58, "type", "Geometric sans", "Visual style", rot=4),
        card(w - 250, 360, "cmdk", "Command palette", "Tool", rot=-3, scale=0.98),
        f'<ellipse cx="{cx:g}" cy="{h * 0.5:g}" rx="{w * 0.36:g}" ry="{h * 0.44:g}" fill="url(#clear)"/>',
    ]
    # The address, as the page's announcement pill.
    chip, pw = "MIT", width(pill, 16) + 92
    px = cx - pw / 2
    out.append(f'<rect x="{px:g}" y="104" width="{pw:g}" height="40" rx="20" fill="{C["surface"]}" stroke="{C["outline"]}"/>'
               f'<rect x="{px + 5:g}" y="109" width="52" height="30" rx="15" fill="{C["tertiary"]}"/>'
               f'<text x="{px + 31:g}" y="129" text-anchor="middle" class="sans" font-size="13" font-weight="600" '
               f'fill="{C["on-tertiary"]}">{chip}</text>'
               f'<text x="{px + 70:g}" y="130" class="sans" font-size="16" font-weight="500" fill="{C["muted"]}">{escape(pill)}</text>')
    for i, (line, fill) in enumerate(zip(TITLE, [C["on-surface"], C["primary"]])):
        out.append(f'<text x="{cx:g}" y="{236 + i * 68}" text-anchor="middle" class="sans" font-size="62" font-weight="600" '
                   f'letter-spacing="-1.8" fill="{fill}">{escape(line)}</text>')
    for i, line in enumerate(tagline):
        out.append(f'<text x="{cx:g}" y="{372 + i * 30}" text-anchor="middle" class="sans" font-size="20" '
                   f'fill="{C["muted"]}">{escape(line)}</text>')
    # The loop's four stages, the last in the accent: what it is all for.
    sizes = [width(f"0{i} {s}", 15, 0.6) + 34 for i, s in enumerate(STAGES, 1)]
    gap = 34
    x = cx - (sum(sizes) + gap * 3) / 2
    for i, (stage, sw) in enumerate(zip(STAGES, sizes), 1):
        last = i == len(STAGES)
        fill, stroke, ink = (C["primary"], C["primary"], C["on-primary"]) if last else (C["surface"], C["outline"], C["on-surface"])
        out.append(f'<rect x="{x:g}" y="458" width="{sw:g}" height="42" rx="10" fill="{fill}" stroke="{stroke}"/>'
                   f'<text x="{x + sw / 2:g}" y="484" text-anchor="middle" class="sans" font-size="15" font-weight="500" '
                   f'fill="{ink}"><tspan class="mono" font-size="12" fill-opacity=".7">0{i}</tspan> {stage}</text>')
        if not last:
            out.append(f'<text x="{x + sw + gap / 2:g}" y="485" text-anchor="middle" class="sans" font-size="18" '
                       f'fill="{C["quiet"]}">›</text>')
        x += sw + gap
    out.append("</svg>\n")
    return "\n".join(out)


if __name__ == "__main__":
    for name in CARDS:
        out = HERE / f"{name}.svg"
        out.write_text(svg(name))
        w, h = CARDS[name][2]
        print(f"Wrote {out.relative_to(HERE.parents[1])} ({out.stat().st_size / 1000:.1f} kB, {w}x{h})")
