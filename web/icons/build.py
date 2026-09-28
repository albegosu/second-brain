#!/usr/bin/env python3
"""Draws the capture page's icons: a page of ink with a bookmark, in the
Paper and Ink palette. The artwork stays inside the maskable safe zone, so one
512px PNG serves as both the regular and the maskable icon.

    python web/icons/build.py   # needs Pillow
"""
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
PAPER, INK, ACCENT = "#f3ede1", "#211e1a", "#d9481f"
PAGE = (136, 136, 376, 376)
LINES = [(172, 212, 292, 226), (172, 248, 292, 262), (172, 284, 252, 298)]
RIBBON = [(304, 112), (348, 112), (348, 300), (326, 278), (304, 300)]


def svg() -> str:
    lines = "".join(f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{PAPER}"/>'
                    for x0, y0, x1, y1 in LINES)
    ribbon = " ".join(f"{x},{y}" for x, y in RIBBON)
    x0, y0, x1, y1 = PAGE
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
            f'<rect width="512" height="512" fill="{PAPER}"/>'
            f'<rect x="{x0}" y="{y0}" width="{x1 - x0}" height="{y1 - y0}" fill="{INK}"/>'
            f'{lines}<polygon points="{ribbon}" fill="{ACCENT}"/></svg>\n')


def png(size: int) -> Image.Image:
    scale = 4  # draw large and downsample, for clean edges
    img = Image.new("RGB", (512 * scale, 512 * scale), PAPER)
    draw = ImageDraw.Draw(img)
    up = lambda box: [v * scale for v in box]
    draw.rectangle(up(PAGE), fill=INK)
    for line in LINES:
        draw.rectangle(up(line), fill=PAPER)
    draw.polygon([(x * scale, y * scale) for x, y in RIBBON], fill=ACCENT)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    (HERE / "icon.svg").write_text(svg())
    for size in (192, 512):
        png(size).save(HERE / f"icon-{size}.png", optimize=True)
