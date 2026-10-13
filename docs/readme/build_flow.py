#!/usr/bin/env python3
"""The README's animated flow: one capture goes save → curate → DESIGN.md → build.

    python docs/readme/build_flow.py        # writes docs/readme/flow.svg

One capture is the protagonist. It is shared out of an app, flies to the curate
stage, a vision-model scan passes over it, its traits appear and its measured
palette lifts off the thumbnail. The swatches fly into the DESIGN.md token lines,
and a card paints itself with those tokens: surface, ink, the headline font, the
tertiary chip and, last, the primary button. The accent is the thread through
every step. It settles on the composed frame, then fades back for the loop.

Nothing in it is invented for the picture. The capture (the one most of the
style's color tokens were measured from), its traits, palette and topic come from
the synthetic test wiki (tests/fixtures/sample-wiki); the tokens, fonts and the
"use it for" line come from the DESIGN.md generated from it
(docs/examples/DESIGN.style-paper-ink.md, kept current by the tests). The image
is styled with that same DESIGN.md. The only words written for the picture are the
step captions, the footer and the built card's button label.

It is CSS @keyframes only (no script, no external resources), so it animates
inside a README <img>. Every element's static attributes are the final composed
frame, which is what prefers-reduced-motion shows. 800 units wide so that at the
~830px GitHub renders it, the smallest text (13) lands at about 13.5px.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "tests" / "fixtures" / "sample-wiki"
DESIGN = ROOT / "docs" / "examples" / "DESIGN.style-paper-ink.md"
OUT = Path(__file__).with_name("flow.svg")

W, H, T = 800, 450, 14.0  # canvas, loop seconds
FADE = 13.2  # everything that moved fades back to the empty stage from here


# ── Data: the sample wiki and the DESIGN.md generated from it ────────────────
def frontmatter(text: str) -> dict[str, str]:
    block = text.split("\n---\n", 1)[0]
    return {k: v.strip().strip('"') for k, v in re.findall(r"^([\w-]+):\s*(.+)$", block, re.M)}


def captures() -> list[dict]:
    out = []
    for f in sorted((WIKI / "sources").rglob("*.md")):
        text = f.read_text()
        meta = frontmatter(text)
        traits = re.search(r"^Traits: (.+)$", text, re.M)
        palette = re.search(r"^Palette, measured[^:]*: (.+)$", text, re.M)
        colors = re.findall(r"`(#[0-9a-f]{6})`( \(accent\))?", palette.group(1)) if palette else []
        out.append({
            "title": meta.get("title", f.stem), "topic": meta.get("topic", ""), "source": meta.get("source", ""),
            "traits": [v.strip() for v in traits.group(1).split("·")] if traits else [],
            "palette": [h for h, _ in colors],
            "neutrals": [h for h, accent in colors if not accent], "accents": [h for h, accent in colors if accent],
        })
    return out


def design() -> dict:
    text = DESIGN.read_text()
    front, body = text.split("\n---\n", 1)
    colors = dict(re.findall(r'^  ([\w-]+): "(#[0-9a-f]{6})"$', front.split("typography:")[0], re.M))
    return {
        "name": re.search(r'^name: "([^"]+)"', front, re.M).group(1),
        "colors": colors,
        "headline": re.search(r'headline-md:\n\s+fontFamily: "([^"]+)"\n\s+fontSize: "(\d+)px"', front).groups(),
        "label": re.search(r'label-lg:\n\s+fontFamily: "([^"]+)"\n\s+fontSize: "(\d+)px"', front).groups(),
        "radius": re.search(r'^  md: "([\d.]+)px"$', front.split("rounded:")[1], re.M).group(1),
        "button": re.search(r'button-primary:.*?height: "(\d+)px"', front, re.S).group(1),
        "topic": re.search(r"from the style topic `([^`]+)`", body).group(1),
        "use_for": re.search(r"Use it for: ([^.,]+)", body).group(1),
        # "**Secondary (#6b655b):** … Adjusted from `#8c8478` for contrast."
        "adjusted": dict(re.findall(r"\((#[0-9a-f]{6})\):\*\*[^\n]*?Adjusted from `(#[0-9a-f]{6})`", body)),
    }


D = design()
COLORS = D["colors"]
TOKENS = ["primary", "secondary", "tertiary", "neutral", "surface", "on-surface"]  # the ones a capture can supply


def source_of(token: str, palette: list[str]) -> str | None:
    """The swatch of `palette` a token was measured from (directly or adjusted for contrast)."""
    hex_ = COLORS[token]
    src = hex_ if hex_ in palette else D["adjusted"].get(hex_)
    return src if src in palette else None


# The protagonist: the capture of the style's topic that supplied the most color tokens.
CAP = max((c for c in captures() if c["topic"] == D["topic"]),
          key=lambda c: sum(source_of(t, c["palette"]) is not None for t in TOKENS))
FLOWS = [(t, source_of(t, CAP["palette"])) for t in TOKENS if source_of(t, CAP["palette"])]
TRAITS = [v for v in CAP["traits"] if v != "none"]  # "none" alone (no radius) reads as nothing

# ── Theme: the generated DESIGN.md itself ────────────────────────────────────
C = {
    "bg": COLORS["neutral"], "surface": COLORS["surface"], "ink": COLORS["on-surface"], "muted": COLORS["secondary"],
    "line": COLORS["outline"], "accent": COLORS["primary"], "on_accent": COLORS["on-primary"],
    "second": COLORS["tertiary"], "on_second": COLORS["on-tertiary"],
}
SERIF = f'"{D["headline"][0]}", "Iowan Old Style", Georgia, "Times New Roman", serif'
SANS = f'"{D["label"][0]}", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace'
R = float(D["radius"])

# ── Animation: CSS keyframes whose static state is the final frame ───────────
css: list[str] = []
uid = 0


def pct(s: float) -> str:
    return f"{max(0.0, min(s, T)) / T * 100:.2f}%".replace(".00%", "%")


def anim(frames: list[tuple[float, str]]) -> str:
    """Register keyframes from (second, declarations) pairs and return the style that plays them.
    Timing is linear: easing is baked into the frames, so multi-stop flights don't stutter."""
    global uid
    name = f"k{uid}"
    uid += 1
    frames = sorted(frames, key=lambda f: f[0])
    if frames[0][0] > 0:
        frames.insert(0, (0, frames[0][1]))
    if frames[-1][0] < T:
        frames.append((T, frames[-1][1]))
    merged: dict[str, str] = {}
    for s, decl in frames:
        merged[pct(s)] = decl
    body = "".join(f"{k}{{{v}}}" for k, v in merged.items())
    css.append(f"@keyframes {name}{{{body}}}")
    return f"animation:{name} {T:g}s linear infinite"


def ease(u: float) -> float:
    return 4 * u ** 3 if u < 0.5 else 1 - (-2 * u + 2) ** 3 / 2


def tf(x: float, y: float, s: float = 1) -> str:
    return f"transform:translate({x:.1f}px,{y:.1f}px) scale({s:.3f})"


def appear(t0: float, dur: float = 0.35, dy: float = 0, out: float = FADE) -> str:
    """Fade (and rise by dy) in at t0, hold, fade back out with the rest."""
    a, b = (f";{tf(0, dy)}", f";{tf(0, 0)}") if dy else ("", "")
    return anim([(t0, f"opacity:0{a}"), (t0 + dur, f"opacity:1{b}"), (out, f"opacity:1{b}"), (out + 0.45, f"opacity:0{b}")])


def flight(t0: float, t1: float, dx: float, dy: float, s0: float = 1, s1: float = 1, lift: float = 40,
           land: str = "stay") -> str:
    """Fly from offset (dx, dy) at scale s0 to the element's own place at scale s1 along an arc.
    land="stay" keeps it there until the fade; land="vanish" lets it melt into its target."""
    mx, my = dx / 2, dy / 2 - lift  # control point of the arc
    fr = [(0, f"opacity:0;{tf(dx, dy, s0)}"), (t0, f"opacity:0;{tf(dx, dy, s0)}")]
    n = 9
    for i in range(n + 1):
        u = ease(i / n)
        x = (1 - u) ** 2 * dx + 2 * (1 - u) * u * mx
        y = (1 - u) ** 2 * dy + 2 * (1 - u) * u * my
        s = s0 + (s1 - s0) * u
        fr.append((t0 + 0.06 + (t1 - t0 - 0.06) * i / n, f"opacity:1;{tf(x, y, s)}"))
    if land == "vanish":
        fr += [(t1 + 0.18, f"opacity:0;{tf(0, 0, s1 * 0.6)}")]
    else:
        fr += [(FADE, f"opacity:1;{tf(0, 0, s1)}"), (FADE + 0.45, f"opacity:0;{tf(0, 0, s1)}")]
    return anim(fr)


# ── Drawing helpers ──────────────────────────────────────────────────────────
def t(x, y, s, *, size=13, fill=None, weight=400, family=SANS, anchor="start", extra=""):
    return (f'<text x="{x:g}" y="{y:g}" font-family=\'{family}\' font-size="{size}" font-weight="{weight}" '
            f'fill="{fill or C["ink"]}" text-anchor="{anchor}" {extra}>{escape(str(s))}</text>')


def rect(x, y, w, h, fill="none", stroke=None, extra="", rx=R):
    s = f' stroke="{stroke}"' if stroke else ""
    return f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="{rx:g}" fill="{fill}"{s} {extra}/>'


def g(style: str, inner: str, at: tuple[float, float] | None = None, hidden: bool = False) -> str:
    """An animated group; `at` places it with a static parent so CSS transforms stay local.
    `hidden` leaves it out of the still (final) frame: it only exists while moving."""
    el = f'<g{' opacity="0"' if hidden else ''} style="{style}">{inner}</g>'
    return f'<g transform="translate({at[0]:g},{at[1]:g})">{el}</g>' if at else el


# ── Layout ───────────────────────────────────────────────────────────────────
ZONES = [(28, 128), (176, 204), (400, 196), (616, 156)]  # x, width
STEPS = [("Save", "from any app"), ("Curate", "a vision model files it"),
         ("DESIGN.md", "your taste as tokens"), ("Build", "your agent builds it")]
TOP = 126  # content starts here
px, py, pw, ph = 32, TOP + 2, 128, 264  # the phone in 01

# The protagonist's thumbnail, drawn from its own measured palette.
TW, TH = 204, 128
nb = CAP["neutrals"] + [C["surface"]] * 4
ac = CAP["accents"] + [C["accent"]] * 2
PAPER, INK, PANEL, MUTED, HOT, LINK = nb[0], nb[1], nb[2], nb[3], ac[0], ac[1]
thumb = (rect(0, 0, TW, TH, PAPER, rx=0)
         + rect(140, 26, 50, 66, PANEL, rx=0)
         + rect(14, 20, 108, 11, INK, rx=0) + rect(14, 36, 76, 11, INK, rx=0)
         + rect(14, 54, 26, 3, HOT, rx=0)
         + "".join(rect(14, 66 + i * 8, w, 3.5, INK, rx=0, extra='opacity="0.85"') for i, w in enumerate([112, 104, 114, 68]))
         + rect(14, 104, 46, 4, MUTED, rx=0) + rect(66, 104, 40, 4, LINK, rx=0)
         + rect(14, 114, 30, 6, HOT, rx=0))
# Where each palette color sits in the thumbnail: the swatches lift off from there.
SPOT = {PAPER: (176, 110), INK: (60, 26), PANEL: (165, 59), MUTED: (37, 106), HOT: (27, 55), LINK: (86, 106)}

out: list[str] = [f'<defs><g id="thumb">{thumb}</g>'
                  f'<clipPath id="screen"><rect x="{px + 6}" y="{py + 6}" width="{pw - 12}" height="{ph - 12}"/></clipPath>'
                  f'<clipPath id="lens"><rect x="0" y="0" width="{TW}" height="{TH}"/></clipPath></defs>',
                  rect(0.5, 0.5, W - 1, H - 1, C["bg"], C["line"], rx=0)]

# Step rail: labels, and the accent thread that fills as the capture moves on.
ACTIVE = [0.25, 2.35, 5.75, 8.35]
for i, ((x, w), (label, sub)) in enumerate(zip(ZONES, STEPS)):
    out.append(t(x, 38, f"0{i + 1}", size=13, fill=C["muted"], family=MONO, extra='letter-spacing="1"'))
    out.append(g(anim([(ACTIVE[i], "opacity:.32"), (ACTIVE[i] + 0.3, "opacity:1"), (FADE, "opacity:1"), (FADE + 0.45, "opacity:.32")]),
                 t(x, 70, label, size=30, weight=600, family=SERIF) + t(x, 92, sub, size=14, fill=C["muted"])))
RAIL_Y, RAIL_X0, RAIL_X1 = 108, ZONES[0][0], ZONES[-1][0] + ZONES[-1][1]
out.append(rect(RAIL_X0, RAIL_Y - 0.5, RAIL_X1 - RAIL_X0, 3, C["line"], rx=0))
reach = [(0.25, ZONES[0][0] + 10), (1.5, ZONES[0][0] + ZONES[0][1]), (2.35, ZONES[1][0] + 10),
         (5.4, ZONES[1][0] + ZONES[1][1]), (5.75, ZONES[2][0] + 10), (7.9, ZONES[2][0] + ZONES[2][1]),
         (8.35, ZONES[3][0] + 10), (10.6, RAIL_X1)]
span = RAIL_X1 - RAIL_X0
fr = [(0, "opacity:1;transform:scaleX(0)")] + [(s, f"opacity:1;transform:scaleX({(x - RAIL_X0) / span:.4f})") for s, x in reach]
fr += [(FADE, "opacity:1;transform:scaleX(1)"), (FADE + 0.45, "opacity:0;transform:scaleX(1)"),
       (T - 0.01, "opacity:0;transform:scaleX(0)"), (T, "opacity:1;transform:scaleX(0)")]
out.append(f'<g transform="translate({RAIL_X0},{RAIL_Y - 0.5})"><rect width="{span}" height="3" fill="{C["accent"]}" '
           f'style="{anim(fr)}"/></g>')
for i, (x, _) in enumerate(ZONES):
    lit = anim([(ACTIVE[i], f"fill:{C['line']}"), (ACTIVE[i] + 0.15, f"fill:{C['accent']}"),
                (FADE, f"fill:{C['accent']}"), (FADE + 0.45, f"fill:{C['line']}")])
    out.append(rect(x, RAIL_Y - 4, 10, 10, C["accent"], rx=0, extra=f'style="{lit}"'))

# 01 Save: the capture in an app, the share sheet, second-brain as the target.
out.append(rect(px, py, pw, ph, C["surface"], C["line"], rx=16))
out.append(rect(px + 6, py + 6, pw - 12, ph - 12, C["bg"], rx=11))
post_x, post_y, post_s = px + 12, py + 40, (pw - 24) / TW
out.append(f'<circle cx="{px + 20}" cy="{py + 24}" r="7" fill="{C["line"]}"/>' + rect(px + 32, py + 21, 46, 6, C["line"], rx=0))
out.append(f'<use href="#thumb" transform="translate({post_x:g},{post_y:g}) scale({post_s:.4f})"/>')
out.append(rect(post_x, post_y, pw - 24, TH * post_s, "none", C["line"], rx=0))
out.append("".join(rect(post_x, post_y + TH * post_s + 10 + i * 9, w, 4, C["line"], rx=0) for i, w in enumerate([96, 70])))
sheet_y = py + ph - 112
sheet = (rect(px + 6, sheet_y, pw - 12, 106, C["surface"], C["line"], rx=0)
         + rect(px + pw / 2 - 12, sheet_y + 7, 24, 3, C["line"], rx=0)
         + "".join(rect(px + 16 + i * 26, sheet_y + 20, 18, 18, C["line"], rx=4) for i in range(4))
         + rect(px + 12, sheet_y + 52, pw - 24, 34, C["bg"], C["line"], rx=0)
         + rect(px + 12, sheet_y + 52, 4, 34, C["accent"], rx=0)
         + t(px + pw / 2 + 2, sheet_y + 74, "second-brain", size=13, weight=600, anchor="middle"))
out.append(f'<g clip-path="url(#screen)">' + g(anim([(0.35, f"{tf(0, 112)}"), (0.8, f"{tf(0, 0)}"), (FADE, f"{tf(0, 0)}"), (FADE + 0.45, f"{tf(0, 112)}")]), sheet) + "</g>")
tap_x, tap_y = px + pw / 2, sheet_y + 69
out.append(f'<g transform="translate({tap_x},{tap_y})"><circle r="10" fill="none" stroke="{C["accent"]}" stroke-width="2.5" '
           f'opacity="0" style="{anim([(1.0, "opacity:0;transform:scale(.4)"), (1.05, "opacity:1;transform:scale(.5)"), (1.6, "opacity:0;transform:scale(2.4)")])}"/></g>')

# 02 Curate: the card lands, the model scans it, its traits and palette come out, it is filed.
cx, cy = ZONES[1][0], TOP
card = (f'<use href="#thumb"/>' + rect(0, 0, TW, TH, "none", C["line"], rx=0))
out.append(g(flight(1.25, 2.3, post_x - cx, post_y - cy, post_s, 1, lift=60), card, at=(cx, cy)))
# vision-model scan, clipped to the thumbnail
scan = (f'<rect x="0" y="-34" width="{TW}" height="34" fill="{C["accent"]}" opacity="0.16"/>'
        f'<rect x="0" y="-2" width="{TW}" height="2.5" fill="{C["accent"]}"/>')
out.append(f'<g transform="translate({cx},{cy})"><g clip-path="url(#lens)"><g opacity="0" style="'
           + anim([(2.4, f"opacity:0;{tf(0, 0)}"), (2.45, f"opacity:1;{tf(0, 0)}"), (3.45, f"opacity:1;{tf(0, TH + 36)}"), (3.5, f"opacity:0;{tf(0, TH + 36)}")])
           + f'">{scan}</g></g></g>')
br = 14  # viewfinder brackets
corners = [(0, 0, 1, 1), (TW, 0, -1, 1), (0, TH, 1, -1), (TW, TH, -1, -1)]
brackets = "".join(f'<path d="M {x0 - 5 * sx:g},{y0 - 5 * sy + br * sy:g} V {y0 - 5 * sy:g} H {x0 - 5 * sx + br * sx:g}" '
                   f'fill="none" stroke="{C["ink"]}" stroke-width="2"/>' for x0, y0, sx, sy in corners)
out.append(f'<g transform="translate({cx},{cy})"><g opacity="0" style="'
           + anim([(2.35, "opacity:0"), (2.5, "opacity:1"), (3.5, "opacity:1"), (3.7, "opacity:0")]) + f'">{brackets}</g></g>')
out.append(g(appear(2.8, 0.35, dy=6), t(cx, cy + TH + 22, CAP["title"], size=16, weight=600, family=SERIF)))
chip_x, chip_y = cx, cy + TH + 34
for i, trait in enumerate(TRAITS):
    w = 14 + len(trait) * 7.4
    if chip_x + w > cx + TW + 1:
        break
    out.append(g(appear(3.0 + i * 0.14, 0.25, dy=6),
                 rect(chip_x, chip_y, w, 22, C["second"], rx=0) + t(chip_x + w / 2, chip_y + 15.5, trait, size=13, weight=500,
                                                                      fill=C["on_second"], anchor="middle")))
    chip_x += w + 6
CHIP_SERIF = (cx + 7 + len(TRAITS[0]) * 3.7, chip_y + 11)  # the typography trait, first chip
SW, SG = 24, (TW - 6 * 24) / 5
sw_y = chip_y + 38
slot = {}
for i, h in enumerate(CAP["palette"][:6]):
    sx, sy = cx + i * (SW + SG) + SW / 2, sw_y + SW / 2
    slot[h] = (sx, sy)
    fx, fy = SPOT.get(h, (TW / 2, TH / 2))
    out.append(g(flight(3.75 + i * 0.12, 4.6 + i * 0.12, cx + fx - sx, cy + fy - sy, 0.6, 1, lift=30),
                 rect(-SW / 2, -SW / 2, SW, SW, h, C["line"], rx=0, extra='stroke-width="0.8"'), at=(sx, sy)))
topic_y = sw_y + SW + 14
folder = (f'<path d="M 0,3 H 5 L 7,5 H 14 V 14 H 0 Z" fill="none" stroke="{C["muted"]}" stroke-width="1.4"/>')
out.append(g(anim([(4.95, f"opacity:0;{tf(-18, 0)}"), (5.35, f"opacity:1;{tf(0, 0)}"), (FADE, f"opacity:1;{tf(0, 0)}"),
                   (FADE + 0.45, f"opacity:0;{tf(0, 0)}")]),
             f'<g transform="translate({cx},{topic_y + 1})">{folder}</g>' + t(cx + 20, topic_y + 13, CAP["topic"], size=13, family=MONO)))

# 03 DESIGN.md: the swatches fly into the token lines.
dx_, dw = ZONES[2]
doc_h = 264
out.append(rect(dx_, TOP, dw, doc_h, C["surface"], C["line"], rx=0))
out.append(g(appear(5.8, 0.3), t(dx_ + 14, TOP + 26, f'name: {D["name"]}', size=13, family=MONO, fill=C["muted"])))
row_y = {}
for i, (token, src) in enumerate(FLOWS):
    y = TOP + 52 + i * 27
    row_y[token] = y
    hx, hy = dx_ + 14 + 9, y + 9  # swatch center
    land = 6.05 + i * 0.24 + 0.6
    morph = (f"fill:{src}", f"fill:{COLORS[token]}") if src != COLORS[token] else None
    sw = rect(-9, -9, 18, 18, COLORS[token], C["line"], rx=0, extra='stroke-width="0.8"')
    if morph:  # adjusted for contrast on the way
        sw = sw.replace("/>", f' style="{anim([(land - 0.3, morph[0]), (land + 0.1, morph[1])])}"/>')
    sx, sy = slot[src]
    out.append(g(flight(land - 0.6, land, sx - hx, sy - hy, 24 / 18, 1, lift=50), sw, at=(hx, hy)))
    out.append(g(appear(land - 0.05, 0.25, dy=0), t(dx_ + 40, y + 14, token, size=13, family=MONO)
                 + t(dx_ + dw - 12, y + 14, COLORS[token], size=13, family=MONO, fill=C["muted"], anchor="end")))
font_y = TOP + 52 + len(FLOWS) * 27 + 10
out.append(g(appear(7.6, 0.3), f'<line x1="{dx_ + 14}" y1="{font_y - 6}" x2="{dx_ + dw - 14}" y2="{font_y - 6}" stroke="{C["line"]}"/>'))
aa_x, aa_y = dx_ + 14, font_y + 24
out.append(g(flight(7.6, 8.15, CHIP_SERIF[0] - (aa_x + 12), CHIP_SERIF[1] - 18 - (aa_y - 7), 0.7, 1, lift=40),  # rises off the chip
             t(0, 0, "Aa", size=24, weight=500, family=SERIF), at=(aa_x, aa_y)))
out.append(g(appear(8.1, 0.25), t(dx_ + 52, font_y + 12, "headline", size=13, family=MONO)
             + t(dx_ + 52, font_y + 29, D["headline"][0], size=13, family=MONO, fill=C["muted"])))

# 04 Build: a card that paints itself with those tokens.
bx, bw = ZONES[3]
by, bh = TOP, doc_h
pad = 16
P_SURF, P_INK, P_MUTED, P_CHIP, P_BTN = 8.55, 8.95, 9.35, 9.75, 10.15


def paint(t0: float, src: tuple[float, float], dst: tuple[float, float], color: str, size: float = 18) -> str:
    """A copy of a token swatch flies from DESIGN.md and melts into its target."""
    return g(flight(t0, t0 + 0.55, src[0] - dst[0], src[1] - dst[1], 1, 0.7, lift=36, land="vanish"),
             rect(-size / 2, -size / 2, size, size, color, C["line"], rx=0, extra='stroke-width="0.8"'), at=dst, hidden=True)


def wipe(t0: float, axis: str = "Y") -> str:
    """Fill grows from its start edge: the paint arriving."""
    return anim([(t0, f"opacity:1;transform:scale{axis}(0)"), (t0 + 0.45, f"opacity:1;transform:scale{axis}(1)"),
                 (FADE, f"opacity:1;transform:scale{axis}(1)"), (FADE + 0.45, f"opacity:0;transform:scale{axis}(1)"),
                 (T - 0.01, f"opacity:0;transform:scale{axis}(0)"), (T, f"opacity:1;transform:scale{axis}(0)")])


def until(t0: float) -> str:
    """A placeholder that gives way when the paint arrives, and comes back for the next loop."""
    return anim([(t0, "opacity:1"), (t0 + 0.2, "opacity:0"), (FADE + 0.3, "opacity:0"), (FADE + 0.65, "opacity:1")])


def recolor(t0: float, prop: str, before: str, after: str) -> str:
    return anim([(t0, f"{prop}:{before}"), (t0 + 0.3, f"{prop}:{after}"), (FADE, f"{prop}:{after}"), (FADE + 0.45, f"{prop}:{before}")])


def token_at(token: str) -> tuple[float, float]:
    return dx_ + 14 + 9, row_y[token] + 9


# card surface
out.append(rect(bx, by, bw, bh, "none", C["line"], rx=0, extra=f'stroke-dasharray="4 4" opacity="0" style="{until(P_SURF + 0.6)}"'))
out.append(paint(P_SURF, token_at("surface"), (bx + bw / 2, by + 20), COLORS["surface"]))
out.append(f'<g transform="translate({bx},{by})"><rect width="{bw}" height="{bh}" fill="{COLORS["surface"]}" '
           f'style="{wipe(P_SURF + 0.5)}"/></g>')
out.append(rect(bx, by, bw, bh, "none", C["line"], rx=0, extra=f'opacity="1" style="{appear(P_SURF + 0.6, 0.3)}"'))
# chip: tertiary
chip_w = 14 + len(D["use_for"]) * 7.4
out.append(rect(bx + pad, by + pad + 2, chip_w, 22, "none", C["line"], rx=0, extra=f'stroke-dasharray="3 3" opacity="0" style="{until(P_CHIP + 0.6)}"'))
out.append(paint(P_CHIP, token_at("tertiary"), (bx + pad + chip_w / 2, by + pad + 13), COLORS["tertiary"]))
out.append(f'<g transform="translate({bx + pad},{by + pad + 2})"><rect width="{chip_w:g}" height="22" fill="{C["second"]}" '
           f'style="{wipe(P_CHIP + 0.5, "X")}"/></g>')
out.append(t(bx + pad + chip_w / 2, by + pad + 17.5, D["use_for"], size=13, weight=500, anchor="middle", fill=C["on_second"],
             extra=f'style="{recolor(P_CHIP + 0.55, "fill", C["muted"], C["on_second"])}"'))
# heading: on-surface ink and the headline font (the sans placeholder gives way to the serif)
hs = int(D["headline"][1])
words = D["name"].split()
lines = [" ".join(words[:-1]), words[-1]] if len(D["name"]) * hs * 0.5 > bw - 2 * pad else [D["name"]]
head_y = by + pad + 62
plain = "".join(t(bx + pad, head_y + i * (hs + 4), ln, size=hs - 4, weight=400, fill=C["line"]) for i, ln in enumerate(lines))
styled = "".join(t(bx + pad, head_y + i * (hs + 4), ln, size=hs, weight=500, family=SERIF) for i, ln in enumerate(lines))
out.append(g(anim([(P_INK + 0.45, "opacity:1"), (P_INK + 0.6, "opacity:0"), (FADE + 0.3, "opacity:0"), (FADE + 0.65, "opacity:1")]),
             plain, hidden=True))
out.append(paint(P_INK, token_at("on-surface"), (bx + pad + 30, head_y - 8), COLORS["on-surface"]))
out.append(g(appear(P_INK + 0.6, 0.35, dy=6), styled))
# body: secondary
body_y = head_y + (len(lines) - 1) * (hs + 4) + 22
bars = [bw - 2 * pad, bw - 2 * pad - 18, bw - 2 * pad - 48]
out.append(paint(P_MUTED, token_at("secondary"), (bx + pad + 40, body_y + 10), COLORS["secondary"]))
out.append("".join(rect(bx + pad, body_y + i * 11, w, 5, COLORS["secondary"], rx=0,
                        extra=f'style="{recolor(P_MUTED + 0.5, "fill", C["line"], COLORS["secondary"])}"') for i, w in enumerate(bars)))
# button: primary, last, the thread arrives
btn_h = int(D["button"])
btn_y = by + bh - pad - btn_h
btn_w = bw - 2 * pad
out.append(rect(bx + pad, btn_y, btn_w, btn_h, "none", C["line"], rx=0, extra=f'stroke-dasharray="3 3" opacity="0" style="{until(P_BTN + 0.6)}"'))
out.append(paint(P_BTN, token_at("primary"), (bx + pad + btn_w / 2, btn_y + btn_h / 2), COLORS["primary"], size=22))
out.append(f'<g transform="translate({bx + pad},{btn_y})"><rect width="{btn_w}" height="{btn_h}" fill="{C["accent"]}" '
           f'style="{wipe(P_BTN + 0.5, "X")}"/></g>')
out.append(t(bx + pad + btn_w / 2, btn_y + btn_h / 2 + 5, "Save a look", size=int(D["label"][1]), weight=600, anchor="middle",
             fill=C["on_accent"], extra=f'style="{recolor(P_BTN + 0.55, "fill", C["muted"], C["on_accent"])}"'))

# Recap: once built, the accent lights up where it travelled, left to right.
PRIMARY_SRC = dict(FLOWS)["primary"]
ring = [(px + 12, sheet_y + 52, pw - 24, 34), (slot[PRIMARY_SRC][0] - SW / 2, slot[PRIMARY_SRC][1] - SW / 2, SW, SW),
        (dx_ + 8, row_y["primary"] - 4, dw - 16, 26), (bx + pad, btn_y, btn_w, btn_h)]
for i, (x, y, w, h) in enumerate(ring):
    t0 = 10.95 + i * 0.22
    out.append(rect(x - 4, y - 4, w + 8, h + 8, "none", C["accent"], rx=0,
                    extra=f'stroke-width="2" opacity="0" style="{anim([(t0, "opacity:0"), (t0 + 0.12, "opacity:1"), (t0 + 0.75, "opacity:0")])}"'))

# Footer
out.append(t(28, H - 22, f"Styled with {D['name']}, the DESIGN.md second-brain generated from its sample wiki.", size=13, fill=C["muted"]))

css.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
label = (f"second-brain, one capture end to end: {CAP['title']} is shared from an app, a vision model reads it, "
         f"files it under {CAP['topic']} and lifts its palette, the swatches become the {D['name']} DESIGN.md tokens, "
         f"and a card paints itself with them, ending on the {COLORS['primary']} primary button.")
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
       f'aria-label="{escape(label)}">\n<title>{escape(label)}</title>\n'
       f'<style>{"".join(css)}</style>\n' + "\n".join(out) + "\n</svg>\n")
OUT.write_text(svg)
print(f"Wrote {OUT.relative_to(ROOT)} ({len(svg.encode()) / 1024:.1f} kB, {W}x{H}, {T:g}s loop, "
      f"protagonist: capture '{CAP['title']}', {len(FLOWS)} tokens traced)")
