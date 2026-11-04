#!/usr/bin/env python3
"""The README's animation: from a share to a build, in four stages.

    python docs/readme/build_flow.py     # writes docs/readme/flow-light.svg and flow-dark.svg

It is the capture page's "From a share to a build" section, drawn as an SVG for the
README:
1. Share: a picture made of pixels, the Share sheet with second-brain picked.
2. Read: a vision model sweeps the frames like a radar, and what it finds lights up.
3. Distill: the DESIGN.md writes itself, line by line.
4. Build: the agent is asked, and a card is put together in those tokens.

A dot runs along the rail above the stages on one 12s clock. Each stage takes its
turn: its outline lights up and its scene plays, while the others keep their
finished state. Colors are the page's own tokens, read from web/style.css
(page_tokens.py), so there is one file per theme and the README picks one with
<picture>. The type follows the DESIGN.md's stack (DM Sans, then Avenir Next).

It is CSS @keyframes only (no script, no external resources), so it animates inside
a README <img>. Every element's static attributes are its finished state, which is
what prefers-reduced-motion shows. 800 units wide, about the width GitHub renders it.
"""
from __future__ import annotations

import re
from html import escape
from pathlib import Path

from page_tokens import MONO, SANS, tokens

HERE = Path(__file__).resolve().parent
W, H = 800, 388
CYCLE = 12  # seconds
EASE = "cubic-bezier(.25,.6,.3,1)"  # smooth: a long, soft ease-out, as on the page

MARGIN, GAP, TOP = 24, 12, 100
CW, CH = (W - 2 * MARGIN - 3 * GAP) / 4, 262  # card
SW, SH = CW - 16, 168  # scene, inset 8 in its card
RAIL = 80
PHASES = [0, -9, -6, -3]  # each stage's place on the clock: its turn is the first quarter


def paint(value: str) -> str:
    """A fill/stroke attribute pair for a token: rgb(r g b / a) becomes a color plus an opacity."""
    m = re.match(r"rgb\((\d+) (\d+) (\d+) / ([\d.]+)\)", value)
    if not m:
        return f'"{value}"'
    r, g, b, a = m.groups()
    return f'"#{int(r):02x}{int(g):02x}{int(b):02x}" {{op}}="{a}"'


def color(attr: str, value: str) -> str:
    return f"{attr}={paint(value).replace('{op}', attr + '-opacity')}"


def text(x: float, y: float, s: str, cls: str, fill: str, anchor: str = "start", extra: str = "") -> str:
    return (f'<text x="{x:g}" y="{y:g}" class="{cls}" fill="{fill}" text-anchor="{anchor}"{extra}>'
            f"{escape(s)}</text>")


def scene_share(c: dict) -> str:
    """01: a picture made of pixels, "Saved", and the Share sheet with second-brain picked."""
    out = ['<g class="a">']
    size, gap = 16, 3
    for n in range(1, 16):  # 5 columns, 3 rows, colored as the page colors them (last rule wins)
        fill = c["outline"]
        if n % 3 == 0:
            fill = c["primary"]
        if (n - 1) % 4 == 0:
            fill = c["on-surface"]
        if n % 7 == 0:
            fill = c["tertiary"]
        if (n - 2) % 5 == 0:
            fill = c["quiet"]
        col, row = (n - 1) % 5, (n - 1) // 5
        out.append(f'<rect x="{14 + col * (size + gap)}" y="{14 + row * (size + gap)}" width="{size}" '
                   f'height="{size}" rx="3" fill="{fill}"/>')
    out.append("</g>")
    out.append(f'<g class="b"><rect x="8" y="108" width="{SW - 16:g}" height="50" rx="10" fill="{c["surface"]}" '
               f'stroke="{c["outline"]}"/>')
    x0 = 8 + (SW - 16 - (4 * 26 + 3 * 8)) / 2
    for i in range(4):
        x = x0 + i * 34
        if i == 2:
            out.append(f'<rect x="{x - 4:g}" y="116" width="34" height="34" rx="10" fill="none" '
                       f'stroke="{c["primary"]}" stroke-width="2"/>')
            out.append(f'<rect class="me" x="{x:g}" y="120" width="26" height="26" rx="7" fill="{c["primary"]}"/>')
        else:
            out.append(f'<rect x="{x:g}" y="120" width="26" height="26" rx="7" fill="{c["outline"]}"/>')
    out.append("</g>")
    out.append(f'<g class="d"><rect x="{SW - 14 - 58:g}" y="76" width="58" height="20" rx="10" fill="{c["primary"]}"/>'
               + text(SW - 14 - 29, 90, "Saved ✓", "mono s", c["on-primary"], "middle") + "</g>")
    return "".join(out)


def scene_read(c: dict) -> str:
    """02: a radar over the frames, three finds, the chips they become and where it's filed."""
    cx, cy, r = 54, 70, 44
    out = [f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{c["surface"]}" stroke="{c["outline"]}"/>',
           f'<circle cx="{cx}" cy="{cy}" r="{r * 2 / 3:g}" fill="none" stroke="{c["outline"]}"/>',
           f'<circle cx="{cx}" cy="{cy}" r="{r / 3:g}" fill="none" stroke="{c["outline"]}"/>',
           f'<path d="M{cx - r} {cy}H{cx + r}M{cx} {cy - r}V{cy + r}" stroke="{c["outline"]}"/>',
           # The sweep: a wedge whose leading edge is bright, turning around the center. The
           # transparent disc gives the group a box centered on the radar, to turn around.
           f'<g class="sweep"><circle cx="{cx}" cy="{cy}" r="{r}" fill="none"/>'
           f'<path d="M{cx} {cy}L{cx} {cy - r}A{r} {r} 0 0 0 {cx - r * 0.766:.1f} {cy - r * 0.643:.1f}Z" '
           f'fill="url(#wedge)"/>'
           f'<path d="M{cx} {cy}L{cx} {cy - r}" stroke="{c["primary"]}" stroke-width="1.5"/></g>']
    for cls, (dx, dy) in zip("abc", [(20, -22), (-22, -6), (8, 24)]):
        out.append(f'<g class="{cls}"><circle cx="{cx + dx}" cy="{cy + dy}" r="3.5" fill="{c["primary"]}"/>'
                   f'<circle cx="{cx + dx}" cy="{cy + dy}" r="7" fill="none" stroke="{c["primary"]}" '
                   f'stroke-opacity=".5"/></g>')
    for cls, (label, w), y in zip("abc", [("nav", 32), ("card", 38), ("motion", 50)], [40, 62, 84]):
        out.append(f'<g class="{cls}"><rect x="106" y="{y}" width="{w}" height="18" rx="9" fill="{c["tertiary"]}"/>'
                   + text(106 + w / 2, y + 12.5, label, "mono s", c["on-tertiary"], "middle") + "</g>")
    out.append('<g class="d">' + text(12, 146, "→ design/menus.md", "mono s", c["muted"]) + "</g>")
    return "".join(out)


def scene_distill(c: dict) -> str:
    """03: the DESIGN.md, line by line: two swatches, then radius, depth and type."""
    right = SW - 12
    out = ['<g class="a">' + text(12, 24, "DESIGN.md", "mono m", c["on-surface"])
           + text(right, 24, "taste", "mono m", c["muted"], "end")
           + f'<path d="M12 34H{right:g}" stroke="{c["outline"]}"/></g>']
    rows = [("b", "primary", ("swatch", c["primary"])), ("c", "tertiary", ("swatch", c["tertiary"])),
            ("d", "radius", ("value", "10px")), ("e", "depth", ("value", "flat")), ("e", "type", ("value", "geometric sans"))]
    for i, (cls, label, (kind, value)) in enumerate(rows):
        y = 56 + i * 21
        item = text(12, y, label, "mono m", c["muted"])
        if kind == "swatch":
            item += f'<rect x="{right - 22:g}" y="{y - 9}" width="22" height="11" rx="3" fill="{value}"/>'
        else:
            item += text(right, y, value, "mono m", c["on-surface"], "end")
        out.append(f'<g class="{cls}">{item}</g>')
    return "".join(out)


def scene_build(c: dict) -> str:
    """04: the prompt, then a settings card built in the tokens: title, two switches, a button."""
    x, y, w, h = 10, 38, SW - 20, 120
    out = ['<g class="a">' + f'<text x="12" y="24" class="mono s"><tspan fill="{c["primary"]}">›</tspan>'
           f'<tspan fill="{c["on-surface"]}"> build a settings card</tspan></text></g>',
           f'<g class="b"><rect x="{x}" y="{y}" width="{w:g}" height="{h}" rx="10" fill="{c["surface"]}" '
           f'stroke="{c["outline"]}"/><rect x="{x + 12}" y="{y + 14}" width="64" height="8" rx="4" fill="{c["on-surface"]}"/>']
    sx = x + w - 12 - 26
    for cls, (ly, line_w, on) in zip("cd", [(y + 36, 72, True), (y + 58, 52, False)]):
        knob = sx + 18.5 if on else sx + 7.5
        out.append(f'<g class="{cls}"><rect x="{x + 12}" y="{ly}" width="{line_w}" height="6" rx="3" fill="{c["outline"]}"/>'
                   f'<rect x="{sx:g}" y="{ly - 4.5}" width="26" height="15" rx="7.5" '
                   f'fill="{c["primary"] if on else c["outline"]}"/>'
                   f'<circle cx="{knob:g}" cy="{ly + 3}" r="5.5" fill="{c["on-primary"] if on else c["neutral"]}"/></g>')
    bx = x + w - 12 - 44
    out.append(f'<g class="e"><rect x="{bx:g}" y="{y + 84}" width="44" height="22" rx="6" fill="{c["primary"]}"/>'
               + text(bx + 22, y + 99, "Save", "sans s", c["on-primary"], "middle") + "</g></g>")
    return "".join(out)


STAGES = [
    ("Share", ["Any app's Share menu:", "a link, a post, an image."], scene_share),
    ("Read", ["A vision model reads", "the frames and files it."], scene_read),
    ("Distill", ["What you keep saving", "becomes design tokens."], scene_distill),
    ("Build", ["Your coding agent", "builds with your taste."], scene_build),
]


def css(c: dict) -> str:
    """Keyframes on the 12s clock, and each stage's elements shifted to its phase."""
    def keep(start: float) -> str:  # hidden until start%, in by start+5%, held to 95%, gone at 100%
        return (f"0%,{start:g}%{{opacity:0;transform:translateY(8px)}}{start + 5:g}%,95%{{opacity:1;transform:none}}"
                f"100%{{opacity:0;transform:none}}")

    starts = dict(zip("abcde", [3, 7, 11, 15, 19]))
    rules = [f".sans{{font-family:{SANS}}}.mono{{font-family:{MONO}}}",
             ".t{font-size:26px;font-weight:600;letter-spacing:-.025em}",
             ".h{font-size:15px;font-weight:600;letter-spacing:-.01em}",
             ".n{font-size:11px;font-weight:500;letter-spacing:.04em}",
             ".p{font-size:12.5px}.m{font-size:11px}.s{font-size:10.5px;font-weight:500}",
             *(f"@keyframes in-{k}{{{keep(v)}}}" for k, v in starts.items()),
             f"@keyframes on{{0%,23%{{stroke:{c['primary']}}}27%,100%{{stroke:{c['outline']}}}}}",
             f"@keyframes num{{0%,23%{{fill:{c['primary']}}}27%,100%{{fill:{c['quiet']}}}}}",
             f"@keyframes me{{0%,11%{{fill:{c['outline']}}}17%,95%{{fill:{c['primary']}}}100%{{fill:{c['outline']}}}}}",
             "@keyframes spin{to{transform:rotate(360deg)}}",
             ".sweep{transform-box:fill-box;transform-origin:center;animation:spin 3s linear infinite}"]
    step = CW + GAP
    rail = ";".join(f"{a}%{{transform:translateX({x:g}px)}}" for a, x in
                    [(0, 0), (20, 0), (25, step), (45, step), (50, 2 * step), (70, 2 * step),
                     (75, 3 * step), (95, 3 * step), (100, 0)])
    rules.append(f"@keyframes rail{{{rail.replace(';', '')}}}")
    rules.append(f".dot{{animation:rail {CYCLE}s {EASE} infinite}}")
    for i, phase in enumerate(PHASES, 1):
        delay = f"{phase}s"
        rules.append(f".s{i} .card{{animation:on {CYCLE}s ease-in-out {delay} infinite}}")
        rules.append(f".s{i} .num{{animation:num {CYCLE}s ease-in-out {delay} infinite}}")
        rules.append(f".s{i} .me{{animation:me {CYCLE}s {EASE} {delay} infinite both}}")
        for k in starts:
            rules.append(f".s{i} .{k}{{animation:in-{k} {CYCLE}s {EASE} {delay} infinite both}}")
    rules.append("@media (prefers-reduced-motion:reduce){*{animation:none!important}}")
    return "".join(rules)


def svg(theme: str) -> str:
    c = tokens(theme)
    centers = [MARGIN + i * (CW + GAP) + CW / 2 for i in range(4)]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
        f'aria-label="From a share to a build: share, read, distill, build">',
        f"<style>{css(c)}</style>",
        "<defs>",
        f'<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse"><path d="M24 0H0V24" fill="none" '
        f'{color("stroke", c["grid"])}/></pattern>',
        f'<pattern id="grid48" width="48" height="48" patternUnits="userSpaceOnUse"><path d="M48 0H0V48" fill="none" '
        f'{color("stroke", c["grid"])}/></pattern>',
        '<radialGradient id="fade" cx="50%" cy="0" r="75%"><stop offset="0" stop-color="#fff"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/></radialGradient>',
        f'<mask id="top"><rect width="{W}" height="{H}" fill="url(#fade)"/></mask>',
        f'<linearGradient id="wedge" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["primary"]}" '
        f'stop-opacity="0"/><stop offset="1" stop-color="{c["primary"]}" stop-opacity=".45"/></linearGradient>',
        *(f'<clipPath id="sc{i}"><rect width="{SW:g}" height="{SH}" rx="10"/></clipPath>' for i in range(1, 5)),
        "</defs>",
        f'<rect x=".5" y=".5" width="{W - 1}" height="{H - 1}" rx="16" fill="{c["neutral"]}" stroke="{c["outline"]}"/>',
        f'<rect width="{W}" height="{H}" rx="16" fill="url(#grid48)" mask="url(#top)"/>',
        f'<text x="{MARGIN + 4}" y="50" class="sans t"><tspan fill="{c["on-surface"]}">From a share</tspan>'
        f'<tspan fill="{c["quiet"]}"> to a build.</tspan></text>',
        f'<rect x="{W - MARGIN - 4 - 20}" y="39" width="20" height="2" fill="{c["primary"]}" transform="translate(-{len("second-brain") * 6.6 + 10:g} 0)"/>',
        text(W - MARGIN - 4, 44, "second-brain", "mono n", c["muted"], "end"),
        f'<path d="M{centers[0]:g} {RAIL}H{centers[3]:g}" stroke="{c["outline"]}"/>',
        *(f'<path d="M{x:g} {RAIL - 4}V{RAIL + 4}" stroke="{c["outline"]}"/>' for x in centers),
        f'<g class="dot"><circle cx="{centers[0]:g}" cy="{RAIL}" r="8" fill="{c["neutral"]}"/>'
        f'<circle cx="{centers[0]:g}" cy="{RAIL}" r="4.5" fill="{c["primary"]}"/></g>',
    ]
    for i, (title, lines, scene) in enumerate(STAGES, 1):
        x = MARGIN + (i - 1) * (CW + GAP)
        parts.append(f'<g class="s{i}" transform="translate({x:g} {TOP})">')
        parts.append(f'<rect class="card" x=".5" y=".5" width="{CW - 1:g}" height="{CH - 1}" rx="16" '
                     f'fill="{c["surface"]}" stroke="{c["outline"]}"/>')
        parts.append(f'<g transform="translate(8 8)"><g clip-path="url(#sc{i})">'
                     f'<rect width="{SW:g}" height="{SH}" fill="{c["neutral"]}"/>'
                     f'<rect width="{SW:g}" height="{SH}" fill="url(#grid)"/>{scene(c)}</g></g>')
        parts.append(text(16, SH + 38, f"0{i}", "mono n num", c["quiet"]))
        parts.append(text(40, SH + 38, title, "sans h", c["on-surface"]))
        parts.extend(text(16, SH + 60 + j * 17, line, "sans p", c["muted"]) for j, line in enumerate(lines))
        parts.append("</g>")
    parts.append("</svg>\n")
    return "\n".join(parts)


if __name__ == "__main__":
    for theme in ("light", "dark"):
        out = HERE / f"flow-{theme}.svg"
        out.write_text(svg(theme))
        print(f"Wrote {out.relative_to(HERE.parents[1])} ({out.stat().st_size / 1000:.1f} kB, {W}x{H})")
