"""The capture page's color tokens, read from web/style.css, for the README images.

The page wears the DESIGN.md pair second-brain drew from its maintainer's wiki
(light in :root, dark in the prefers-color-scheme block). The README animation and
the link previews are drawn in the same tokens, so reading them from the
stylesheet keeps the three from drifting apart.
"""
from __future__ import annotations

import re
from pathlib import Path

CSS = Path(__file__).resolve().parents[2] / "web" / "style.css"
SANS = '"DM Sans", "Avenir Next", Futura, ui-sans-serif, system-ui, sans-serif'
MONO = '"DM Mono", ui-monospace, Menlo, Consolas, monospace'


def _block(css: str, start: str) -> str:
    """The declarations of the first rule that opens with `start`, up to its closing brace."""
    i = css.index(start)
    return css[i:css.index("}", i)]


def tokens(theme: str) -> dict[str, str]:
    """The page's tokens for "light" or "dark": every --name whose value is a hex or rgb() color."""
    css = CSS.read_text()
    root = _block(css, ":root {")
    found = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6}|rgb\([^)]*\))\s*;", root))
    if theme == "dark":
        dark = _block(css, "@media (prefers-color-scheme: dark) {\n  :root {")
        found |= dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6}|rgb\([^)]*\))\s*;", dark))
    elif theme != "light":
        raise ValueError(f"unknown theme {theme!r}")
    return found
