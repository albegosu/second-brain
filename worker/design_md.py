#!/usr/bin/env python3
"""DESIGN.md: the owner's taste, or one saved style, as design tokens an agent follows.

    python -m worker.design_md                          # rewrite wiki/DESIGN.md from the taste and commit it
    python -m worker.design_md --style editorial        # one style topic (design/style-editorial), printed
    python -m worker.design_md --style editorial --out ~/code/app/DESIGN.md
    python -m worker.design_md --dry-run                # print the derived tokens and change nothing
    python -m worker.design_md --no-model               # template prose, no model call

The file follows the DESIGN.md format from Google Labs (version alpha,
github.com/google-labs-code/design.md): YAML tokens, then Overview, Colors,
Typography, Layout, Elevation & Depth, Shapes, Components and Do's and Don'ts,
plus a Motion section (the spec keeps sections it doesn't know).
The code derives every token from what source notes record: measured palettes
become color roles, tuned to WCAG AA contrast; the type family category becomes
a font; the radius, spacing and depth categories become scales. A model only
writes the overview and the do's and don'ts, so a bad answer can at most spoil
the prose; without a model a template writes them. The taste's DESIGN.md is
refreshed after the weekly lint pass, next to taste.md.

A style topic can hold several looks. Its DESIGN.md describes the dominant one:
each trait takes the value most of its captures share (the newest capture breaks
a tie), and the colors come from the one capture that matches those traits best
(the newest on a tie), so palettes of different looks are never mixed.
"""
from __future__ import annotations

import argparse
import colorsys
import json
import re
import sys
from collections import Counter
from pathlib import Path

from . import pipeline as p
from . import run
from . import taste
from . import wiki

PATH = "DESIGN.md"
SPEC = "https://github.com/google-labs-code/design.md"

# Type family category → an open font that is a common example of it (all on
# Google Fonts) and its fallback stack. The category is measured; the font is
# only a default, so the prose tells the agent to swap it for the project's own.
FONTS = {
    "geometric-sans": ("DM Sans", '"DM Sans", "Avenir Next", Futura, ui-sans-serif, system-ui, sans-serif'),
    "grotesk": ("Inter", 'Inter, "Helvetica Neue", Helvetica, Arial, sans-serif'),
    "humanist-sans": ("Source Sans 3", '"Source Sans 3", "Segoe UI", "Gill Sans", ui-sans-serif, sans-serif'),
    "serif": ("Source Serif 4", '"Source Serif 4", Georgia, "Times New Roman", serif'),
    "mono": ("JetBrains Mono", '"JetBrains Mono", "SF Mono", Menlo, Consolas, monospace'),
    "display": ("Bricolage Grotesque", '"Bricolage Grotesque", "Arial Black", ui-sans-serif, sans-serif'),
    None: ("system-ui", "system-ui, -apple-system, \"Segoe UI\", Roboto, sans-serif"),
}
# A display face is for headlines only, and a serif look keeps its labels in a
# sans: both read badly small.
BODY_FONT = {"display": "grotesk"}
LABEL_FONT = {"display": "grotesk", "serif": "grotesk"}
HEADLINE = {"display": (800, "-0.03em"), "serif": (500, "-0.01em"), "mono": (500, "0em"), None: (600, "-0.02em")}

# Corner radius in px for sm, md, lg and xl. Buttons and inputs use md, cards lg.
RADIUS = {"none": (0, 0, 0, 0), "subtle": (2, 4, 6, 8), "rounded": (6, 10, 16, 24), "pill": (8, 9999, 24, 32)}
SPACING = {
    "tight": {"xs": 2, "sm": 4, "md": 8, "lg": 12, "xl": 16, "gutter": 12, "margin": 16},
    "comfortable": {"xs": 4, "sm": 8, "md": 16, "lg": 24, "xl": 32, "gutter": 24, "margin": 32},
    "airy": {"xs": 8, "sm": 12, "md": 24, "lg": 40, "xl": 64, "gutter": 32, "margin": 64},
}
CONTROL_HEIGHT = {"tight": 32, "comfortable": 40, "airy": 48}
BODY_LINE = {"tight": "1.4", "comfortable": "1.5", "airy": "1.6"}
# What a trait has to fall back on when no capture records it.
DEFAULTS = {"radius": "subtle", "spacing": "comfortable", "depth": "flat", "motion_feel": "smooth"}

DEPTH = {
    "flat": "No shadows: layers are told apart by the step from neutral to surface and by 1px outline "
            "borders.",
    "soft-shadow": "Soft shadows lift cards, menus and dialogs: a large blur at low opacity, never a hard "
                   "edge. A starting point: `0 1px 2px rgb(0 0 0 / 0.06), 0 8px 24px rgb(0 0 0 / 0.08)`.",
    "layered": "Panels overlap and step up through surface tones, with a shadow only under the top layer.",
    "glass": "Panels are the surface color at 60-75% opacity with a background blur (a starting point: "
             "`backdrop-filter: blur(20px)`) and a 1px outline, over a background with enough color or "
             "image to blur.",
}
MOTION = {
    "snappy": "short, decisive transitions that settle fast.",
    "smooth": "unhurried, continuous transitions; nothing bounces.",
    "springy": "a little overshoot, like a spring settling.",
    "none": "state changes are instant or a plain fade.",
}
WORDS = {
    "geometric-sans": "geometric sans-serif", "grotesk": "grotesk", "humanist-sans": "humanist sans-serif",
    "serif": "serif", "mono": "monospaced", "display": "display",
    "none": "square", "subtle": "barely rounded", "rounded": "rounded", "pill": "pill-shaped",
    "flat": "flat", "soft-shadow": "softly shadowed", "layered": "layered", "glass": "glass",
}

ROLE_USE = {
    "primary": "the main action on each screen, active states and key highlights",
    "on-primary": "text and icons on primary",
    "secondary": "muted text: captions, metadata, placeholders and secondary icons",
    "tertiary": "a second accent for tags, charts and secondary highlights, never the main action",
    "on-tertiary": "text and icons on tertiary",
    "neutral": "the page background",
    "surface": "cards, inputs, menus and other containers, one step from the page",
    "on-surface": "body text, headings and icons",
    "outline": "1px borders and dividers",
}

WRITE = """You write the prose of a DESIGN.md: the design system file an AI coding
assistant follows when it builds an interface. Its design tokens are fixed and
written by code; you get them with the evidence they come from. Return ONLY JSON:

{"overview": "3-5 sentences: the look and feel, what it suits and the response it should evoke",
 "dos": ["up to 5 short rules that keep the look, each starting with a verb"],
 "donts": ["up to 5 short things that would break it, each starting with a verb, without \"don't\" or \"avoid\""]}

Rules:
- Only what the tokens and the evidence support. Name colors by their role
  (primary, surface, on-surface...), never by a hex code, and name no font,
  framework or number that isn't in the input.
- Where the evidence says "no clear lead", don't present it as a preference.
- Plain sentences: no Markdown, no headings, no links.
- English.
"""


# ---------------------------------------------------------------- color

def rgb(hex_: str) -> tuple[int, int, int]:
    return tuple(int(hex_[i:i + 2], 16) for i in (1, 3, 5))


def to_hex(color) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c))) for c in color)


def luminance(hex_: str) -> float:
    """WCAG relative luminance."""
    def linear(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (linear(c) for c in rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def mix(a: str, b: str, amount: float) -> str:
    return to_hex(x + (y - x) * amount for x, y in zip(rgb(a), rgb(b)))


def vivid(hex_: str) -> bool:
    """Saturated and bright enough to be a brand color rather than a photo's shade.
    Palettes include content colors, so a muted accent is often a picture's."""
    _, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb(hex_)))
    return s >= 0.6 and v >= 0.55


def hue_gap(a: str, b: str) -> float:
    """Degrees between two colors' hues, 0-180."""
    h1, h2 = (colorsys.rgb_to_hsv(*(c / 255 for c in rgb(x)))[0] * 360 for x in (a, b))
    return min(abs(h1 - h2), 360 - abs(h1 - h2))


def readable(fg: str, backgrounds: list[str], target: float = 4.5) -> str:
    """fg, darkened or lightened along its own hue until it reaches target on every
    background. Pure black or white reaches 4.58:1 on any single color, so this
    only fails between two backgrounds far apart, and then returns the best."""
    h, l, s = colorsys.rgb_to_hls(*(c / 255 for c in rgb(fg)))
    darker_first = min(map(luminance, backgrounds)) > 0.18
    best, best_ratio = fg, 0.0
    for direction in ((-1, 1) if darker_first else (1, -1)):
        for step in range(101):
            color = to_hex(c * 255 for c in colorsys.hls_to_rgb(h, min(1, max(0, l + direction * step / 100)), s))
            ratio = min(contrast(color, bg) for bg in backgrounds)
            if ratio >= target:
                return color
            if ratio > best_ratio:
                best, best_ratio = color, ratio
    return best


def on_color(fill: str, inks: list[str]) -> str:
    """Text on a filled color: the palette's own ink or paper when it reads, else
    black or white, whichever reads better."""
    ink = max(inks, key=lambda c: contrast(c, fill))
    return ink if contrast(ink, fill) >= 4.5 else max(("#ffffff", "#000000"), key=lambda c: contrast(c, fill))


def medoid(colors: list[str]) -> str:
    """The measured color closest to all the others: a real color, never an average."""
    return min(colors, key=lambda c: sum(sum((x - y) ** 2 for x, y in zip(rgb(c), rgb(o))) for o in colors))


def nearest(colors: list[str], base: str, low: float, high: float, aim: float) -> str | None:
    """The color whose contrast with base falls in [low, high], closest to aim."""
    fits = [c for c in colors if low <= contrast(c, base) <= high]
    return min(fits, key=lambda c: abs(contrast(c, base) - aim)) if fits else None


def roles(neutrals: list[str], accents: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Color roles from a palette, largest area first, accents in order of
    preference. Returns the colors and, per role, where each one comes from."""
    colors, origin = {}, {}
    neutral = neutrals[0] if neutrals else "#ffffff"
    rest = [c for c in dict.fromkeys(neutrals[1:]) if c != neutral]
    ink = max(rest, key=lambda c: contrast(c, neutral), default=neutral)
    rest = [c for c in rest if c != ink]

    def keep(role, color, measured, how="derived"):
        colors[role] = color
        origin[role] = ("measured" if color == measured else f"adjusted from `{measured}` for contrast"
                        ) if measured else how

    keep("neutral", neutral, neutrals[0] if neutrals else None)
    step = nearest(rest, neutral, 1.02, 1.25, 1.1)
    keep("surface", step or mix(neutral, ink, 0.05), step, "derived: neutral, 5% of the way to the text color")
    keep("on-surface", readable(ink, [neutral, colors["surface"]]), ink if ink != neutral else None,
         "derived from neutral for contrast")
    muted = nearest([c for c in rest if c != step], neutral, 2.5, contrast(ink, neutral), 5)
    keep("secondary", readable(muted or mix(colors["on-surface"], neutral, 0.35), [neutral, colors["surface"]]),
         muted, "derived: on-surface, 35% of the way to neutral, kept at 4.5:1")
    line = nearest([c for c in rest if c not in (step, muted)], neutral, 1.3, 3, 1.6)
    keep("outline", line or mix(neutral, colors["on-surface"], 0.18), line,
         "derived: neutral, 18% of the way to on-surface")

    inks = [colors["on-surface"], neutral]
    if accents:
        keep("primary", accents[0], accents[0])
        keep("on-primary", on_color(accents[0], inks), None, "picked for contrast on primary")
        # A second accent only if it reads as another color, not a shade of the first.
        second = next((c for c in accents[1:] if hue_gap(c, accents[0]) >= 45), None)
        if second:
            keep("tertiary", second, second)
            keep("on-tertiary", on_color(second, inks), None, "picked for contrast on tertiary")
    else:  # a monochrome look: the main action is ink on paper
        keep("primary", colors["on-surface"], None, "the ink: the palette has no accent")
        keep("on-primary", neutral, None, "the page color")
    order = ("primary", "on-primary", "secondary", "tertiary", "on-tertiary",  # the spec's convention first
             "neutral", "surface", "on-surface", "outline")
    return {r: colors[r] for r in order if r in colors}, origin


# ---------------------------------------------------------------- evidence

def looks(files: list[Path] | None = None) -> list[dict]:
    """What each source note records about its look: traits and measured palette,
    the same lines taste.evidence() counts."""
    out = []
    for f in wiki.source_files() if files is None else files:
        if not f.exists():
            continue
        meta, body = wiki.read_page(f)
        m = re.search(r"^Traits: (.+)$", body, re.M)
        traits = taste.traits(m.group(1)) if m else {}
        m = re.search(r"^Palette, measured[^:]*: (.+)$", body, re.M)
        colors = re.findall(r"`(#[0-9a-f]{6})`( \(accent\))?", m.group(1)) if m else []
        if traits or colors:
            out.append({"capture": int(meta.get("capture") or wiki.capture_number(f.name)),
                        "category": str(meta.get("topic", "")).split("/")[0], "traits": traits,
                        "neutrals": [c for c, accent in colors if not accent],
                        "accents": [c for c, accent in colors if accent]})
    return sorted(out, key=lambda look: look["capture"])


def choose(counts: Counter, fallback: str | None = None) -> tuple[str | None, str]:
    """The value to use and why, in taste.md's terms: its lead when there is one,
    otherwise the most frequent, said so."""
    total = sum(counts.values())
    if value := taste.lead(counts):
        return value, f"lead: {value} {counts[value]} of {total}"
    top = [(v, n) for v, n in counts.most_common() if v not in ("other", "none")]
    if top:
        return top[0][0], "no clear lead: " + " · ".join(f"{v} {n}" for v, n in top[:3])
    return fallback, "no evidence, a neutral default"


def tally(counts: Counter) -> str:
    """"centered 18 · stacked 12 · grid 9 (no clear lead)", as taste.md words it."""
    lead = taste.lead(counts)
    top = " · ".join(f"{v} {n}" for v, n in counts.most_common(4))
    return f"{top} ({f'lead: {lead}' if lead else 'no clear lead'})"


def majority(values: list[str | None], fallback: str | None) -> tuple[str | None, str]:
    """The value most captures of a topic share; values come oldest first, so on a
    tie the newest capture wins."""
    counts = Counter(v for v in values if v)
    if not counts:
        return fallback, "not recorded, a neutral default"
    top = max(counts.values())
    value = next(v for v in reversed(values) if counts.get(v) == top)
    return value, f"{top} of {len(values)} capture{'' if len(values) == 1 else 's'}"


def taste_design() -> dict | None:
    """The owner's default look: taste.md's counts for the traits. Colors come from
    the design captures with the leading background tone: the neutrals of the one
    whose page color is the most typical (one palette, so they belong together),
    and the most typical shade of the leading accent hue."""
    ev = taste.evidence()
    if ev["looks"] < taste.MIN_LOOKS:
        return None
    c = ev["counts"]
    traits = {"typography": choose(c["typography"])}
    traits.update({k: choose(c[k], DEFAULTS[k]) for k in ("radius", "spacing", "depth", "motion_feel")})

    mine = [look for look in looks() if look["category"] in taste.LOOK_CATEGORIES and look["neutrals"]]
    tone, tone_why = choose(c["background"])
    backgrounds = [look for look in mine if taste.tone(look["neutrals"][0]) == tone] or mine
    page = medoid([look["neutrals"][0] for look in backgrounds]) if backgrounds else None
    neutrals = next((look["neutrals"] for look in backgrounds if look["neutrals"][0] == page), [])

    def shade(hue):
        """Each capture's largest accent of that hue, preferring vivid ones: their medoid."""
        for group in (backgrounds, mine):  # an accent seen on the same kind of background first
            found = [sorted((a for a in look["accents"] if taste.hue(a) == hue), key=lambda a: not vivid(a))[:1]
                     for look in group]
            found = [a for first in found for a in first]
            if found:
                return medoid([a for a in found if vivid(a)] or found)
        return None

    hue, hue_why = choose(c["accent"])
    accents = [a for a in (shade(h) for h in [hue] + [h for h, _ in c["accent"].most_common() if h != hue]) if a] \
        if hue else []
    colors, origin = roles(neutrals, accents)
    origin = {role: "measured in the same capture as neutral" if how == "measured" else how
              for role, how in origin.items()}
    if backgrounds:
        origin["neutral"] = (f"the most typical page color of the {len(backgrounds)} captures with a "
                             f"{taste.tone(colors['neutral'])} background ({tone_why})")
    if accents:
        origin["primary"] = f"the most typical {hue} accent across the captures ({hue_why})"
    if "tertiary" in colors:
        origin["tertiary"] = (f"the most typical {taste.hue(colors['tertiary'])} accent, the most frequent hue "
                              "that reads apart from primary")

    unsettled = [name for name, why in (("background tone", tone_why), ("accent hue", hue_why),
                                        *((k.replace("_", " "), v[1]) for k, v in traits.items()))
                 if why.startswith("no ")]
    return {"kind": "taste", "name": "Taste", "key": None,
            "description": f"The default look across {ev['looks']} saved design captures, as design tokens.",
            "captures": [], "looks": ev["looks"], "traits": traits, "colors": colors, "origin": origin,
            "unsettled": unsettled, "evidence": taste.evidence_lines(ev, verdict=True),
            "counts": {k: tally(c[k]) for k in ("layout", "density", "easing", "property") if c[k]},
            "block": {}, "variants": []}


def style_topics() -> list[dict]:
    """Design topics that collect looks: named style-* or written as a Styles sheet."""
    return [t for t in wiki.topics() if t["category"] == "design"
            and (t["slug"].startswith("style-") or t["label"] == "Styles")]


def find_style(name: str) -> dict | None:
    slug = wiki.slugify(name.split("/")[-1])
    return next((t for t in style_topics() if t["slug"] in (slug, f"style-{slug}")), None)


def strip_cites(text: str) -> str:
    text = re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", text)
    text = re.sub(r"https?://\S+", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def style_blocks(body: str) -> list[dict]:
    """The "### Name [n]" blocks under "## Styles": name, cited sources and fields."""
    blocks, section, field = [], None, None
    for line in body.replace("’", "'").splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif section == "Styles" and line.startswith("### "):
            cites = [int(n) for group in re.findall(r"\[([\d,\s]+)\]", line) for n in re.findall(r"\d+", group)]
            blocks.append({"name": strip_cites(line[4:]), "cites": cites, "fields": {}})
            field = None
        elif section == "Styles" and blocks:
            if m := re.match(r"^\*\*([^*:]+):\*\*\s*(.*)$", line):
                field = m.group(1).strip().lower()
                blocks[-1]["fields"][field] = m.group(2)
            elif field and line.strip():
                blocks[-1]["fields"][field] += "\n" + line
    return blocks


def style_design(name: str) -> dict | None:
    topic = find_style(name)
    if not topic:
        return None
    mine = looks([wiki.WIKI / rel for rel in topic["sources"]])
    if not mine:
        return None
    traits = {k: majority([look["traits"].get(k) for look in mine], DEFAULTS.get(k))
              for k in ("typography", "radius", "spacing", "depth", "motion_feel")}
    # The capture that shares most of those traits carries the palette; newest on a tie.
    anchor = max((look for look in mine if look["neutrals"] or look["accents"]),
                 key=lambda look: (sum(look["traits"].get(k) == v for k, (v, _) in traits.items()), look["capture"]),
                 default=mine[-1])
    accents = sorted(anchor["accents"], key=lambda a: not vivid(a))  # stable: largest vivid first
    colors, origin = roles(anchor["neutrals"], accents)
    for role, how in origin.items():
        if how == "measured":
            origin[role] = f"measured in capture #{anchor['capture']}"

    blocks = style_blocks(wiki.read_page(wiki.WIKI / f"{topic['key']}.md")[1])
    # The block that cites the anchor capture, by its [n] in the topic's sources list.
    at = next((i for i, rel in enumerate(topic["sources"], 1) if wiki.capture_number(rel) == anchor["capture"]), None)
    block = next((b for b in blocks if at in b["cites"]),
                 blocks[0] if blocks else {"name": topic["title"], "fields": {}})
    return {"kind": "style", "name": topic["title"], "key": topic["key"],
            "description": strip_cites(topic["summary"]) or f"The look of the {topic['title']} topic.",
            "captures": [look["capture"] for look in mine], "looks": len(mine), "anchor": anchor["capture"],
            "traits": traits, "colors": colors, "origin": origin,
            "unsettled": [k.replace("_", " ") for k, (_, why) in traits.items() if why.startswith("not ")],
            "evidence": [], "counts": {},
            "block": {k: strip_cites(v) for k, v in block["fields"].items() if k != "tokens"},
            "variants": [b["name"] for b in blocks if b is not block]}


# ---------------------------------------------------------------- tokens

def tokens(d: dict) -> dict:
    t = {k: v for k, (v, _) in d["traits"].items()}
    family = t["typography"] if t["typography"] in FONTS else None
    spacing = t["spacing"] if t["spacing"] in SPACING else DEFAULTS["spacing"]
    radius = t["radius"] if t["radius"] in RADIUS else DEFAULTS["radius"]
    head, body, label = (FONTS[family][0], FONTS[BODY_FONT.get(family, family)][0],
                         FONTS[LABEL_FONT.get(family, family)][0])
    weight, tracking = HEADLINE.get(family, HEADLINE[None])
    line = BODY_LINE[spacing]

    def type_(font, size, w, height, spacing_=None):
        out = {"fontFamily": font, "fontSize": f"{size}px", "fontWeight": w, "lineHeight": height}
        return out | ({"letterSpacing": spacing_} if spacing_ else {})

    label_tracking = None if family == "mono" else "0.01em"
    typography = {
        "headline-display": type_(head, 48, weight, "1.1", tracking),
        "headline-lg": type_(head, 32, weight, "1.2", tracking),
        "headline-md": type_(head, 24, weight, "1.3"),
        "body-lg": type_(body, 18, 400, line),
        "body-md": type_(body, 16, 400, line),
        "body-sm": type_(body, 14, 400, line),
        "label-lg": type_(label, 14, 500, "1.2", label_tracking),
        "label-md": type_(label, 12, 500, "1.2", label_tracking),
        "label-sm": type_(label, 11, 500, "1.2", label_tracking),
    }
    sm, md, lg, xl = RADIUS[radius]
    height = f"{CONTROL_HEIGHT[spacing]}px"
    colors = d["colors"]
    chip_fill = "tertiary" if "tertiary" in colors else "surface"
    components = {
        "page": {"backgroundColor": "{colors.neutral}", "textColor": "{colors.on-surface}",
                 "typography": "{typography.body-md}"},
        "button-primary": {"backgroundColor": "{colors.primary}", "textColor": "{colors.on-primary}",
                           "typography": "{typography.label-lg}", "rounded": "{rounded.md}",
                           "padding": "{spacing.md}", "height": height},
        "button-secondary": {"backgroundColor": "{colors.surface}", "textColor": "{colors.on-surface}",
                             "typography": "{typography.label-lg}", "rounded": "{rounded.md}",
                             "padding": "{spacing.md}", "height": height},
        "card": {"backgroundColor": "{colors.surface}", "textColor": "{colors.on-surface}",
                 "rounded": "{rounded.lg}", "padding": "{spacing.lg}"},
        "input": {"backgroundColor": "{colors.neutral}", "textColor": "{colors.on-surface}",
                  "typography": "{typography.body-md}", "rounded": "{rounded.md}",
                  "padding": "{spacing.sm}", "height": height},
        "chip": {"backgroundColor": f"{{colors.{chip_fill}}}",
                 "textColor": "{colors.on-tertiary}" if chip_fill == "tertiary" else "{colors.on-surface}",
                 "typography": "{typography.label-md}",
                 "rounded": "{rounded.full}" if radius in ("rounded", "pill") else "{rounded.sm}",
                 "padding": "{spacing.xs}"},
        "text-muted": {"backgroundColor": "{colors.neutral}", "textColor": "{colors.secondary}",
                       "typography": "{typography.body-sm}"},
    }
    return {"version": "alpha", "name": d["name"], "description": d["description"],
            "colors": colors, "typography": typography,
            "rounded": {"none": "0px", "sm": f"{sm}px", "md": f"{md}px", "lg": f"{lg}px", "xl": f"{xl}px",
                        "full": "9999px"},
            "spacing": {k: f"{v}px" for k, v in SPACING[spacing].items()},
            "components": components}


def resolve(tok: dict, ref: str):
    node = tok
    for part in ref.strip("{}").split("."):
        node = node[part]
    return node


def contrast_pairs(tok: dict) -> dict[str, float]:
    """Text on fill for every component, as the DESIGN.md linter checks it."""
    return {name: contrast(resolve(tok, c["textColor"]), resolve(tok, c["backgroundColor"]))
            for name, c in tok["components"].items() if "textColor" in c and "backgroundColor" in c}


# ---------------------------------------------------------------- prose

def cap(text: str) -> str:
    return text[:1].upper() + text[1:]


def listed(words: list[str]) -> str:
    return ", ".join(words[:-1]) + f" and {words[-1]}" if len(words) > 1 else "".join(words)


def facts(d: dict, tok: dict) -> str:
    """What the model writes from: roles by tone and hue, never hex codes."""
    def say(hex_):  # a near-black keeps a hue in HSV, but reads as black
        _, s, v = colorsys.rgb_to_hsv(*(c / 255 for c in rgb(hex_)))
        return f"{taste.tone(hex_)} {taste.hue(hex_) if s > 0.25 and v > 0.25 else 'neutral'}"
    lines = [f"Name: {d['name']}", f"Description: {d['description']}", "", "Color roles:"]
    lines += [f"- {role}: {say(hex_)}, for {ROLE_USE[role]}" for role, hex_ in d["colors"].items()]
    lines += ["", "Traits:"] + [f"- {k.replace('_', ' ')}: {v} ({why})" for k, (v, why) in d["traits"].items()]
    lines.append(f"- fonts: {tok['typography']['headline-lg']['fontFamily']} for headlines, "
                 f"{tok['typography']['body-md']['fontFamily']} for body")
    if d["evidence"]:
        lines += ["", "Counts across the captures:", *d["evidence"]]
    if d["block"]:
        lines += ["", "The style as the wiki describes it:"]
        lines += [f"- {k}: {v}" for k, v in d["block"].items()]
    return "\n".join(lines)


BAD = re.compile(r"#[0-9a-f]{3,8}\b|https?://|^\s*#|\*\*|`", re.I | re.M)


def sentences(items, limit: int) -> list[str]:
    out = []
    for s in items if isinstance(items, list) else []:
        s = re.sub(r"\s+", " ", str(s)).strip()
        # "Do: …", "Don't use …", "Avoid …": the list already says do or don't.
        s = re.sub(r"^(?:[-*•]\s*)?(?:(?:do(?:n't| not)?|never|avoid)(?:\s*:)?\s+)?", "", s, flags=re.I)
        if 10 <= len(s) <= 240 and not BAD.search(s):
            out.append(cap(s) if s[-1] in ".!?" else cap(s) + ".")
    return out[:limit]


def written(d: dict, tok: dict) -> dict | None:
    """The model's overview and do's and don'ts, or None if they don't hold up."""
    try:
        data = p.parse_json(p.chat(WRITE, facts(d, tok), as_json=True))
    except Exception as e:  # no model, no network or no JSON: the template writes it
        print(f"[design] template prose: {e}", file=sys.stderr)
        return None
    overview = re.sub(r"\s+", " ", str(data.get("overview") or "")).strip() if isinstance(data, dict) else ""
    if not 80 <= len(overview) <= 1200 or BAD.search(overview):
        print(f"[design] template prose: unusable overview {overview[:80]!r}", file=sys.stderr)
        return None
    return {"overview": overview, "dos": sentences(data.get("dos"), 5), "donts": sentences(data.get("donts"), 5)}


def items(text: str) -> list[str]:
    """A Do or Don't field as separate rules: its bullets, or the whole line."""
    bullets = [b.strip() for b in re.findall(r"^\s*[-*]\s+(.+)$", text, re.M)]
    return [b if b[-1] in ".!?" else b + "." for b in bullets or [text.strip()] if b]


def template(d: dict) -> dict:
    t = {k: v for k, (v, _) in d["traits"].items()}
    feel = "almost no" if t["motion_feel"] == "none" else t["motion_feel"]
    look = (f"{WORDS.get(t['typography'], 'system sans-serif')} type on a {taste.tone(d['colors']['neutral'])} "
            f"background, {WORDS.get(t['radius'], 'barely rounded')} corners, {t['spacing']} spacing and "
            f"{WORDS.get(t['depth'], 'flat')} surfaces, with {feel} motion")
    if d["kind"] == "taste":
        overview = (f"The look the owner keeps saving, across {d['looks']} design captures: {look}. It is the "
                    "starting point when neither the user nor the project sets a style.")
        if d["unsettled"]:
            overview += (f" The captures don't settle the {listed(d['unsettled'])}: the tokens use the most "
                         "frequent value, so follow the project where it has an opinion.")
        return {"overview": overview, "dos": [], "donts": []}
    b = d["block"]
    overview = " ".join(x for x in (d["description"], b.get("composition"),
                                    f"Use it for: {b['use it for']}" if b.get("use it for") else "") if x)
    if not b.get("composition"):
        overview += f" The look: {look}."
    return {"overview": re.sub(r"\s+", " ", overview).strip(), "dos": items(b.get("do", "")),
            "donts": items(b.get("don't", ""))}


def guardrails(d: dict, tok: dict) -> tuple[list[str], list[str]]:
    """Rules that follow from the tokens themselves, whatever writes the prose."""
    t = {k: v for k, (v, _) in d["traits"].items()}
    c = d["colors"]
    dos, donts = ["Keep text at 4.5:1 or more on its background: on-surface and secondary are already "
                  "tuned to neutral and surface."], []
    if c["primary"] != c["on-surface"]:
        dos.append("Keep primary for the one main action on a screen.")
        ratio = contrast(c["primary"], c["neutral"])
        if ratio < 3:
            donts.append(f"Use primary for text or icons on neutral ({ratio:.1f}:1): only as a fill under on-primary.")
        elif ratio < 4.5:
            donts.append(f"Set body text in primary on neutral ({ratio:.1f}:1): use it as a fill under "
                         "on-primary, or for large text and icons.")
    if t["radius"] == "none":
        donts.append("Round corners: every radius is 0.")
    elif t["radius"] == "pill":
        dos.append("Make buttons, inputs and chips fully round.")
    donts.append({"soft-shadow": "Use hard or dark shadows.",
                  "layered": "Flatten stacked panels into one plane.",
                  "glass": "Put glass panels on an empty, flat background: the blur needs something behind it."
                  }.get(t["depth"], "Add drop shadows: separate layers with surface and outline instead."))
    if t["spacing"] == "airy":
        donts.append(f"Crowd: leave at least {tok['spacing']['xl']} between sections.")
    elif t["spacing"] == "tight":
        dos.append(f"Keep it dense: {tok['spacing']['md']} gaps inside groups, no oversized padding.")
    if t["typography"] == "serif":
        dos.append("Set headlines and reading text in the serif; keep buttons and labels in the sans.")
    elif t["typography"] == "mono":
        dos.append("Use the monospaced face for data and figures too, so columns align.")
    if d["unsettled"]:
        dos.append(f"Follow the project on the {listed(d['unsettled'])}: the captures don't settle "
                   f"{'them' if len(d['unsettled']) > 1 else 'it'}.")
    return dos, donts


def prose(d: dict, tok: dict, model: bool = True) -> dict:
    out = (written(d, tok) if model else None) or template(d)
    extra_dos, extra_donts = guardrails(d, tok)
    return {**out, "dos": out["dos"] + extra_dos, "donts": out["donts"] + extra_donts}


# ---------------------------------------------------------------- render

def yaml(data: dict, indent: int = 0) -> list[str]:
    """YAML with JSON-quoted strings, like the wiki's frontmatter: no dependency."""
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines += [" " * indent + f"{key}:", *yaml(value, indent + 2)]
        else:
            shown = json.dumps(value, ensure_ascii=False) if isinstance(value, str) else str(value)
            lines.append(" " * indent + f"{key}: {shown}")
    return lines


def render(d: dict, tok: dict, text: dict) -> str:
    c, t = d["colors"], {k: v for k, (v, _) in d["traits"].items()}
    why = {k: w for k, (_, w) in d["traits"].items()}
    ty, sp, ro = tok["typography"], tok["spacing"], tok["rounded"]
    if d["kind"] == "taste":
        source = f"from the taste of {d['looks']} saved design captures (`python -m worker.design_md`)"
    else:
        source = (f"from the style topic `{d['key']}`, captures {', '.join(f'#{n}' for n in d['captures'])} "
                  f"(`python -m worker.design_md --style {d['key'].split('/')[1]}`)")
    lines = ["---", *yaml(tok), "---", "", f"# {d['name']}", "",
             f"Generated by second-brain {source}, in the [DESIGN.md format]({SPEC}). Tokens are derived by "
             "code: measured palettes tuned to WCAG AA contrast, and the type, radius, spacing and depth "
             "the captures share. An explicit request or the project's own design system always wins.", ""]

    lines += ["## Overview", "", text["overview"], ""]
    if d["variants"]:
        lines += [f"This is the topic's dominant look. It also holds: {'; '.join(d['variants'])}.", ""]

    lines += ["## Colors", ""]
    for role, hex_ in c.items():
        on = "neutral" if role in ("on-surface", "secondary") else role[3:] if role.startswith("on-") else None
        ratio = f" {contrast(hex_, c[on]):.1f}:1 on {on}." if on else ""
        lines.append(f"- **{cap(role.replace('-', ' '))} ({hex_}):** {cap(ROLE_USE[role])}.{ratio} "
                     f"{cap(d['origin'][role])}.")

    head, body, label = (ty[k]["fontFamily"] for k in ("headline-lg", "body-md", "label-md"))
    stacks = {name: next(stack for font, stack in FONTS.values() if font == name) for name in (head, body, label)}
    lines += ["", "## Typography", "",
              f"The captures' type is {WORDS.get(t['typography'], 'not recorded')} ({why['typography']}). "
              f"{head} is a common open font of that family: a default, to swap for the project's own.", "",
              f"- **Headlines:** {head} {ty['headline-lg']['fontWeight']}, 24-48px, line height 1.1-1.3.",
              f"- **Body:** {body} 400, 14-18px, line height {ty['body-md']['lineHeight']}.",
              f"- **Labels:** {label} 500, 11-14px, for buttons, tabs, chips and metadata.",
              "- **Fallback stacks:** " + " · ".join(f"`{s}`" for s in stacks.values()), ""]

    counts = "".join(f" {name} across the captures: {d['counts'][k]}." for k, name in
                     (("layout", "Layouts"), ("density", "Density")) if k in d["counts"])
    lines += ["## Layout", "",
              f"Spacing is {t['spacing']} ({why['spacing']}): {sp['md']} inside controls and between related "
              f"items, {sp['lg']} inside cards, {sp['xl']} between sections, {sp['gutter']} gutters and "
              f"{sp['margin']} page margins, with {sp['xs']} and {sp['sm']} for fine steps.{counts}", ""]

    lines += ["## Elevation & Depth", "",
              f"Depth is {WORDS.get(t['depth'], t['depth'])} ({why['depth']}). {DEPTH.get(t['depth'], DEPTH['flat'])}"]
    if t["depth"] in ("soft-shadow", "layered") and taste.tone(c["neutral"]) == "dark":
        lines[-1] += " On a dark background shadows barely show, so let the lighter surface carry the step."

    shape = {"none": f"{ro['md']} everywhere, on controls, cards and images alike.",
             "subtle": f"{ro['md']} on buttons and inputs, {ro['lg']} on cards, {ro['sm']} on chips.",
             "rounded": f"{ro['md']} on buttons and inputs, {ro['lg']} on cards, fully round chips and avatars.",
             "pill": f"buttons, inputs and chips fully round, cards at {ro['lg']}."}
    lines += ["", "## Shapes", "",
              f"Corners are {WORDS.get(t['radius'], t['radius'])} ({why['radius']}): "
              f"{shape.get(t['radius'], shape['subtle'])}", ""]

    height = tok["components"]["button-primary"]["height"]
    edge = {"soft-shadow": "a soft shadow", "layered": "a tonal step, and a shadow when on top",
            "glass": "a background blur and a 1px outline"}.get(t["depth"], "a 1px outline")
    lines += ["## Components", "",
              f"- **Buttons:** primary is a primary fill with an on-primary label, {height} tall with {sp['md']} "
              f"side padding and {ro['md']} corners; secondary is on-surface on surface, same size.",
              f"- **Cards:** surface on neutral with {edge}, {ro['lg']} corners and {sp['lg']} padding.",
              f"- **Inputs:** a neutral fill with a 1px outline, {height} tall, {ro['md']} corners, body-md text.",
              "- **Chips:** " + ("tertiary with on-tertiary text" if "tertiary" in c
                                 else "surface with on-surface text") + ", label-md.",
              "- **Muted text:** secondary on neutral, body-sm, for captions and metadata.", ""]

    feel = t["motion_feel"] if t["motion_feel"] in MOTION else "smooth"
    counts = "".join(f" {name} across the captures: {d['counts'][k]}." for k, name in
                     (("easing", "Easing"), ("property", "Animated properties")) if k in d["counts"])
    lines += ["## Motion", "",
              f"Motion is {'still' if feel == 'none' else feel} ({why['motion_feel']}): {MOTION[feel]}{counts} "
              "Durations can't be measured from stills, so none is given.", ""]

    lines += ["## Do's and Don'ts", "", *(f"- **Do:** {x}" for x in text["dos"]),
              *(f"- **Don't:** {x}" for x in text["donts"])]
    return "\n".join(lines) + "\n"


def generate(style: str | None = None, model: bool = True) -> tuple[dict, dict, str] | None:
    """The design, its tokens and the DESIGN.md text; None when there is nothing to
    derive it from."""
    d = style_design(style) if style else taste_design()
    if not d:
        return None
    tok = tokens(d)
    return d, tok, render(d, tok, prose(d, tok, model))


def build(model: bool = True) -> bool:
    """Rewrites wiki/DESIGN.md from the taste. False when there isn't enough to say."""
    made = generate(model=model)
    if not made:
        print("[design] not enough captures with a look: no DESIGN.md yet")
        return False
    (wiki.WIKI / PATH).write_text(made[2])
    return True


def dry_run(d: dict, tok: dict):
    print(f"{d['name']}: {d['looks']} look{'' if d['looks'] == 1 else 's'}"
          + (f", colors from capture #{d['anchor']}" if d.get("anchor") else ""))
    for key, (value, why) in d["traits"].items():
        print(f"  {key}: {value} ({why})")
    for role, hex_ in d["colors"].items():
        print(f"  {role}: {hex_} ({d['origin'][role]})")
    for name, ratio in contrast_pairs(tok).items():
        print(f"  {name}: {ratio:.2f}:1")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--style", help="a style topic's slug (style-editorial, or editorial); default: the taste")
    ap.add_argument("--out", help="file to write, or - to print; default: wiki/DESIGN.md for the taste, "
                                  "printed for a style")
    ap.add_argument("--dry-run", action="store_true", help="print the derived tokens and change nothing")
    ap.add_argument("--no-model", action="store_true", help="write the prose from a template, without a model")
    args = ap.parse_args()

    d = style_design(args.style) if args.style else taste_design()
    if not d:
        known = ", ".join(t["slug"] for t in style_topics()) or "none"
        sys.exit(f"[design] no style topic {args.style!r} with a look (style topics: {known})" if args.style
                 else f"[design] fewer than {taste.MIN_LOOKS} captures with a look: no DESIGN.md yet")
    tok = tokens(d)
    if args.dry_run:
        return dry_run(d, tok)
    text = render(d, tok, prose(d, tok, model=not args.no_model))
    out = args.out or ("-" if args.style else None)
    if out == "-":
        sys.stdout.write(text)
    elif out:
        Path(out).expanduser().write_text(text)
        print(f"[design] wrote {out}", file=sys.stderr)
    else:
        (wiki.WIKI / PATH).write_text(text)
        wiki.build_index()
        run.commit_wiki("docs(wiki): refresh DESIGN.md")


if __name__ == "__main__":
    main()
