#!/usr/bin/env python3
"""The README's animated flow: save from anywhere → curate → DESIGN.md → build.

    python docs/readme/build_flow.py        # writes docs/readme/flow.svg

Nothing in it is invented for the picture. The captures, their traits and
measured palettes, the topics and the tokens all come from the synthetic test
wiki (tests/fixtures/sample-wiki) and the DESIGN.md generated from it
(docs/examples/DESIGN.style-paper-ink.md, kept current by the tests). The image
is styled with that same DESIGN.md. CSS + SMIL only, so it animates inside a
README <img>.
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WIKI = ROOT / "tests" / "fixtures" / "sample-wiki"
DESIGN = ROOT / "docs" / "examples" / "DESIGN.style-paper-ink.md"
OUT = Path(__file__).with_name("flow.svg")

W, H, T = 1280, 720, 14.0  # canvas, loop seconds
HOLD_END = T - 0.8


# ── Data from the sample wiki ────────────────────────────────────────────────
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
        out.append({
            "title": meta.get("title", f.stem),
            "topic": meta.get("topic", ""),
            "traits": traits.group(1) if traits else "",
            "palette": re.findall(r"`(#[0-9a-f]{6})`", palette.group(1)) if palette else [],
        })
    return out


def design_tokens() -> tuple[dict[str, str], dict[str, str], str]:
    text = DESIGN.read_text()
    front = text.split("\n---\n", 1)[0]
    colors = dict(re.findall(r'^  ([\w-]+): "(#[0-9a-f]{6})"$', front.split("typography:")[0], re.M))
    heading = re.search(r'headline-display:\n\s+fontFamily: "([^"]+)"', front).group(1)
    rounded = dict(re.findall(r'^  (sm|md|lg): "([\d.]+px)"$', front.split("rounded:")[1].split("spacing:")[0], re.M))
    name = re.search(r'^name: "([^"]+)"', front, re.M).group(1)
    return colors, rounded, f"{name}|{heading}"


def lint_summary() -> str | None:
    """The spec linter's verdict on the example, if npx can run it."""
    try:
        res = subprocess.run(["npx", "-y", "@google/design.md@0.4.0", "lint", str(DESIGN)],
                             capture_output=True, text=True, timeout=120)
        m = re.search(r'"errors":\s*(\d+),\s*"warnings":\s*(\d+)', res.stdout)
        return f"lint · {m.group(1)} errors · {m.group(2)} warnings" if m else None
    except (OSError, subprocess.TimeoutExpired):
        return None


caps = captures()
colors, rounded, meta = design_tokens()
style_name, heading_font = meta.split("|")
lint = lint_summary()
topics = Counter(c["topic"] for c in caps)

# ── Theme: the generated DESIGN.md itself ────────────────────────────────────
C = {
    "bg": colors["neutral"], "surface": colors["surface"], "ink": colors["on-surface"], "muted": colors["secondary"],
    "line": colors["outline"], "accent": colors["primary"], "on_accent": colors["on-primary"], "second": colors["tertiary"],
    "on_second": colors["on-tertiary"],
}
SERIF = f'"{heading_font}", "Iowan Old Style", Georgia, "Times New Roman", serif'
SANS = 'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif'
MONO = 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace'
R = float(rounded.get("md", "4px").rstrip("px"))

css: list[str] = []
uid = 0


def pct(s: float) -> str:
    return f"{s / T * 100:.2f}%"


def appear(start: float, dur: float = 0.35, rise: float = 0) -> str:
    """Fade (and optionally rise) in at `start`, hold, fade out before the loop restarts."""
    global uid
    name = f"a{uid}"
    uid += 1
    move = (lambda y: f";transform:translateY({y}px)") if rise else (lambda y: "")
    css.append(f"@keyframes {name}{{0%,{pct(start)}{{opacity:0{move(rise)}}}"
               f"{pct(start + dur)},{pct(HOLD_END)}{{opacity:1{move(0)}}}"
               f"{pct(HOLD_END + 0.4)},100%{{opacity:0{move(0)}}}}}")
    return f'style="opacity:0;animation:{name} {T}s ease-out infinite"'


def highlight(start: float, until: float) -> str:
    """A row lights up while the flow passes through it, then settles."""
    global uid
    name = f"h{uid}"
    uid += 1
    css.append(f"@keyframes {name}{{0%,{pct(start)}{{fill-opacity:0}}{pct(start + 0.2)},{pct(until)}{{fill-opacity:1}}"
               f"{pct(until + 0.4)},100%{{fill-opacity:0}}}}")
    return f'style="fill-opacity:0;animation:{name} {T}s linear infinite"'


def t(x, y, s, *, size=13, fill=None, weight=400, family=SANS, anchor="start", extra=""):
    return (f'<text x="{x}" y="{y}" font-family=\'{family}\' font-size="{size}" font-weight="{weight}" '
            f'fill="{fill or C["ink"]}" text-anchor="{anchor}" {extra}>{escape(str(s))}</text>')


def swatches(x, y, hexes, size=12, gap=3):
    return "".join(f'<rect x="{x + i * (size + gap)}" y="{y}" width="{size}" height="{size}" rx="2" fill="{h}" '
                   f'stroke="{C["line"]}" stroke-width="0.6"/>' for i, h in enumerate(hexes))


def connector(x1, x2, y, start, dur=0.7):
    """Arrow between columns, with a dot riding it (SMIL keeps the loop in phase)."""
    kt = lambda s: f"{s / T:.4f}"
    return (f'<g {appear(start - 0.1, 0.2)}><line x1="{x1}" y1="{y}" x2="{x2 - 6}" y2="{y}" stroke="{C["line"]}" stroke-width="1.5"/>'
            f'<path d="M {x2 - 8},{y - 5} L {x2},{y} L {x2 - 8},{y + 5}" fill="none" stroke="{C["muted"]}" stroke-width="1.5"/></g>'
            f'<circle r="4.5" fill="{C["accent"]}" opacity="0">'
            f'<animateMotion dur="{T}s" repeatCount="indefinite" path="M {x1},{y} L {x2 - 4},{y}" keyPoints="0;0;1;1" '
            f'keyTimes="0;{kt(start)};{kt(start + dur)};1" calcMode="linear"/>'
            f'<animate attributeName="opacity" dur="{T}s" repeatCount="indefinite" values="0;0;1;1;0;0" '
            f'keyTimes="0;{kt(start)};{kt(start + 0.05)};{kt(start + dur)};{kt(start + dur + 0.1)};1"/></circle>')


out: list[str] = [f'<rect width="{W}" height="{H}" fill="{C["bg"]}"/>']

# Header
out.append(t(40, 56, "second-brain", size=34, weight=600, family=SERIF))
out.append(t(262, 56, "save → curate → DESIGN.md → build", size=15, fill=C["muted"], family=MONO))
out.append(t(40, 84, "Your references from anywhere, filed by a vision model, turned into the tokens your coding agent builds with.",
             size=15, fill=C["muted"]))
out.append(f'<line x1="40" y1="104" x2="{W - 40}" y2="104" stroke="{C["line"]}"/>')

COLS = [(40, 285), (345, 285), (650, 285), (955, 285)]  # x, width
TOP = 128
titles = ["01 / SAVE", "02 / CURATE", "03 / DESIGN.md", "04 / BUILD"]
subs = ["share from any app", "a vision model files it", "your taste as tokens", "the agent builds with it"]
for (x, w), title, sub in zip(COLS, titles, subs):
    out.append(t(x, TOP + 14, title, size=12, weight=700, fill=C["accent"], family=MONO, extra='letter-spacing="1"'))
    out.append(t(x, TOP + 34, sub, size=13, fill=C["muted"]))
PANEL_Y, PANEL_H = TOP + 50, 452
for x, w in COLS:
    out.append(f'<rect x="{x}" y="{PANEL_Y}" width="{w}" height="{PANEL_H}" rx="{R + 2}" fill="{C["surface"]}" fill-opacity="0.55" stroke="{C["line"]}"/>')

# 01 / SAVE: where captures come from, then the captures themselves
x0, w0 = COLS[0]
chips = ["X", "Instagram", "LinkedIn", "any web page", "screenshot", "photo"]
cx, cy = x0 + 16, PANEL_Y + 24
for i, chip in enumerate(chips):
    cw = 12 + len(chip) * 7.2
    if cx + cw > x0 + w0 - 12:
        cx, cy = x0 + 16, cy + 30
    out.append(f'<g {appear(0.3 + i * 0.12)}><rect x="{cx}" y="{cy}" width="{cw}" height="22" rx="11" fill="{C["bg"]}" stroke="{C["line"]}"/>'
               + t(cx + cw / 2, cy + 15, chip, size=12, anchor="middle") + "</g>")
    cx += cw + 8
out.append(t(x0 + 16, cy + 50, "Share → second-brain (iPhone / Mac)", size=12, fill=C["muted"], family=MONO))
card_y = cy + 66
shown = caps[:6]
for i, c in enumerate(shown):
    y = card_y + i * 44
    out.append(f'<g {appear(1.0 + i * 0.3, 0.4, rise=-8)}><rect x="{x0 + 16}" y="{y}" width="{w0 - 32}" height="36" rx="{R}" fill="{C["bg"]}" stroke="{C["line"]}"/>'
               + t(x0 + 28, y + 23, c["title"], size=13, weight=500)
               + swatches(x0 + w0 - 32 - 5 * 15, y + 12, c["palette"][:5], size=11, gap=4) + "</g>")

# 02 / CURATE: one capture read, then the wiki it lands in
x1, w1 = COLS[1]
first = caps[0]
out.append(connector(x0 + w0 + 4, x1 - 4, PANEL_Y + 80, 3.0))
out.append(f'<g {appear(3.4)}>' + t(x1 + 16, PANEL_Y + 32, "vision model reads", size=12, fill=C["muted"], family=MONO)
           + t(x1 + 16, PANEL_Y + 54, first["title"], size=15, weight=600, family=SERIF) + "</g>")
out.append(f'<g {appear(3.8)}>' + t(x1 + 16, PANEL_Y + 80, "traits", size=11, fill=C["muted"], family=MONO)
           + t(x1 + 16, PANEL_Y + 98, first["traits"], size=12, family=MONO) + "</g>")
out.append(f'<g {appear(4.2)}>' + t(x1 + 16, PANEL_Y + 124, "palette, measured from pixels", size=11, fill=C["muted"], family=MONO) + "</g>")
for i, h in enumerate(first["palette"][:6]):
    out.append(f'<g {appear(4.3 + i * 0.1, 0.25)}>' + swatches(x1 + 16 + i * 40, PANEL_Y + 134, [h], size=34) + "</g>")
out.append(f'<g {appear(5.0)}>' + t(x1 + 16, PANEL_Y + 204, "filed into wiki/", size=11, fill=C["muted"], family=MONO) + "</g>")
rows = [topic for topic, _ in topics.most_common()] + ["taste.md", "DESIGN.md"]
counts = [f"×{n}" for _, n in topics.most_common()] + ["counts", "tokens"]
for i, (row, count) in enumerate(zip(rows, counts)):
    y = PANEL_Y + 216 + i * 30
    lit = 5.2 + i * 0.25
    out.append(f'<g {appear(5.05 + i * 0.12, 0.25)}>'
               f'<rect x="{x1 + 12}" y="{y}" width="{w1 - 24}" height="24" rx="{R}" fill="{C["accent"] if row == "DESIGN.md" else C["bg"]}" {highlight(lit, HOLD_END if row == "DESIGN.md" else lit + 0.6)}/>'
               + t(x1 + 20, y + 16, row, size=12, family=MONO, fill=C["ink"])
               + t(x1 + w1 - 20, y + 16, count, size=11, family=MONO, fill=C["on_accent"] if row == "DESIGN.md" else C["muted"], anchor="end") + "</g>")

# 03 / DESIGN.md: the generated file's front matter
x2, w2 = COLS[2]
out.append(connector(x1 + w1 + 4, x2 - 4, PANEL_Y + 80, 6.9))
yaml = [
    ("---", None), (f'name: "{style_name}"', None), ("colors:", None),
    (f'  primary: "{colors["primary"]}"', colors["primary"]), (f'  tertiary: "{colors["tertiary"]}"', colors["tertiary"]),
    (f'  neutral: "{colors["neutral"]}"', colors["neutral"]), (f'  on-surface: "{colors["on-surface"]}"', colors["on-surface"]),
    ("typography:", None), (f'  headline: "{heading_font}"', None), ("rounded:", None), (f'  md: "{rounded.get("md", "")}"', None), ("---", None),
]
for i, (line, sw) in enumerate(yaml):
    y = PANEL_Y + 34 + i * 23
    out.append(f'<g {appear(7.2 + i * 0.12, 0.2)}>' + t(x2 + 16, y, line, size=13, family=MONO,
                                                        fill=C["muted"] if line in ("---",) else C["ink"])
               + (swatches(x2 + w2 - 36, y - 12, [sw], size=16) if sw else "") + "</g>")
ly = PANEL_Y + 34 + len(yaml) * 23 + 10
out.append(f'<g {appear(8.9)}><rect x="{x2 + 12}" y="{ly}" width="{w2 - 24}" height="54" rx="{R}" fill="{C["bg"]}" stroke="{C["line"]}"/>'
           + t(x2 + 22, ly + 22, "Google Labs DESIGN.md format", size=12, weight=600)
           + t(x2 + 22, ly + 41, lint or "spec-compliant, derived by code", size=12, family=MONO, fill=C["muted"]) + "</g>")

# 04 / BUILD: a card built only from those tokens
x3, w3 = COLS[3]
out.append(connector(x2 + w2 + 4, x3 - 4, PANEL_Y + 80, 9.4))
out.append(f'<g {appear(9.8)}>' + t(x3 + 16, PANEL_Y + 32, "Claude Code · Cursor · any agent", size=12, fill=C["muted"], family=MONO) + "</g>")
by = PANEL_Y + 52
out.append(f'<g {appear(10.1, 0.4, rise=-10)}><rect x="{x3 + 16}" y="{by}" width="{w3 - 32}" height="250" rx="{R + 2}" fill="{C["bg"]}" stroke="{C["line"]}"/>'
           + t(x3 + 34, by + 36, "FIELD NOTES · 04", size=11, weight=700, fill=C["muted"], family=MONO, extra='letter-spacing="1"')
           + t(x3 + 34, by + 78, "Built with", size=30, weight=500, family=SERIF)
           + t(x3 + 34, by + 112, "your taste", size=30, weight=500, family=SERIF, fill=C["accent"]) + "</g>")
out.append(f'<g {appear(10.6)}>' + t(x3 + 34, by + 146, "Paper ground, ink text, one hot", size=13, fill=C["muted"])
           + t(x3 + 34, by + 165, "accent: tokens, not guesses.", size=13, fill=C["muted"]) + "</g>")
out.append(f'<g {appear(11.0, 0.3)}><rect x="{x3 + 34}" y="{by + 190}" width="118" height="38" rx="{R}" fill="{C["accent"]}"/>'
           + t(x3 + 93, by + 214, "Save a look", size=13, weight=600, fill=C["on_accent"], anchor="middle")
           + f'<rect x="{x3 + 164}" y="{by + 198}" width="70" height="22" rx="11" fill="{C["second"]}"/>'
           + t(x3 + 199, by + 213, "serif", size=12, fill=C["on_second"], anchor="middle") + "</g>")
out.append(f'<g {appear(11.4)}>' + t(x3 + 16, by + 290, "“build it with my taste”", size=14, family=SERIF, fill=C["ink"])
           + t(x3 + 16, by + 312, "reads wiki/DESIGN.md first", size=12, family=MONO, fill=C["muted"]) + "</g>")

# Footer
out.append(f'<line x1="40" y1="{H - 56}" x2="{W - 40}" y2="{H - 56}" stroke="{C["line"]}"/>')
out.append(t(40, H - 28, f"This image is styled with the DESIGN.md second-brain generated from its sample wiki ({style_name}).",
             size=12, fill=C["muted"]))
out.append(t(W - 40, H - 28, "getdesign.md gives you Stripe's DESIGN.md. second-brain gives you yours.", size=12,
             weight=600, anchor="end"))

svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
       f'aria-label="second-brain: share references from any app, a vision model files them into a wiki, the wiki becomes a DESIGN.md, and your coding agent builds with it">\n'
       f'<style>{"".join(css)}</style>\n' + "\n".join(out) + "\n</svg>\n")
OUT.write_text(svg)
print(f"Wrote {OUT.relative_to(ROOT)} ({len(svg) / 1024:.1f} kB, {T:.0f}s loop, {len(caps)} sample captures"
      f"{', ' + lint if lint else ''})")
