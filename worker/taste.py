#!/usr/bin/env python3
"""Taste profile: what the owner's captures have in common.

    python -m worker.taste             # rewrite wiki/taste.md and commit it
    python -m worker.taste --dry-run   # print the evidence and change nothing

A single capture says what one post looked like; many say what the owner keeps
choosing. The code counts what source notes record (style traits, facets,
animated properties, easing, background tone and accent hues of the measured
palettes, categories) and collects the owner's notes. The model only reads those
counts and writes a short default direction, citing them, so a bad answer can at
most spoil the prose. It runs at the end of the weekly lint pass.
"""
from __future__ import annotations

import argparse
import colorsys
import re
from collections import Counter
from datetime import date

from . import pipeline as p
from . import run
from . import wiki

PATH = "taste.md"

# Below this many captures with a look, there is no taste to speak of.
MIN_LOOKS = 5

# Looks and motion only count from these categories: a tool's landing page or an
# article's screenshot has a look too, but it wasn't saved for it.
LOOK_CATEGORIES = {"design"}

WRITE = """You describe the taste of the owner of a personal knowledge base of
interface references, for an AI coding assistant that designs for them when no
style has been given. You get counts measured by code over their captures and the
notes they wrote when saving. Write Markdown, in English.

Structure, only these sections, each a short bulleted list:
## Default look
Type, color, background, radius, spacing and depth to start from.
## Motion
How things should move: properties, easing and feel.
## Recurring subjects
What they keep saving: components, layouts, kinds of interaction.
## In their words
What their notes say they look for. Leave the section out if there are no notes.
## Not enough evidence
Choices the counts don't settle, so the assistant should ask or follow the project.

Rules:
- Each count line says "lead: <value>" or "no clear lead", decided by code. Only a
  lead can be a preference; everything with no clear lead that matters for a
  design goes under "Not enough evidence", with its top values.
- Every bullet ends with the evidence it rests on, as counts from the input,
  like "(grotesk 9 of 23)". No count, no bullet.
- Recurring subjects are specific components, layouts and kinds of motion, never
  the categories themselves.
- Only what the counts and notes support: no fonts, hex codes, durations or
  frameworks that aren't in the input.
- Direct and short: a builder reads it in half a minute.
- No title, no frontmatter, no evidence section: they are added by code. Return
  only the Markdown body.
"""

TRAIT_OF = {}
for key, values in p.STYLE.items():
    for v in values:
        TRAIT_OF.setdefault(v, []).append(key)
TRAIT_ORDER = list(p.STYLE)

EASING = re.compile(r"^(?:linear|spring|ease(?:-in|-out|-in-out)?|cubic-bezier\(.*\)|steps\(.*\))$", re.I)
PROPERTIES = re.compile(r"^[a-z-]+(?:\s*,\s*[a-z-]+)*$", re.I)  # a list of CSS properties, not a sentence

HUES = [(15, "red"), (45, "orange"), (70, "yellow"), (160, "green"), (200, "cyan"),
        (255, "blue"), (290, "purple"), (335, "pink"), (360, "red")]


def traits(line: str) -> dict[str, str]:
    """"Traits: grotesk · none · airy" → {typography: grotesk, radius: none, …}.
    "none" is both a radius and a motion feel: the traits come in STYLE's order,
    so it belongs to whichever key comes next after the last one matched."""
    out, last = {}, -1
    for value in (v.strip() for v in line.split("·")):
        keys = [k for k in TRAIT_OF.get(value, []) if TRAIT_ORDER.index(k) > last]
        if keys:
            out[keys[0]] = value
            last = TRAIT_ORDER.index(keys[0])
    return out


def tone(hex_: str) -> str:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    light = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "dark" if light < 0.35 else "light" if light > 0.7 else "mid-tone"


def hue(hex_: str) -> str:
    r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h = colorsys.rgb_to_hsv(r, g, b)[0] * 360
    return next(name for limit, name in HUES if h <= limit)


def evidence() -> dict:
    """Everything the profile is written from, counted by code."""
    c = {name: Counter() for name in ("category", "background", "accent", "property", "easing", *p.STYLE, *p.FACETS)}
    looks, captures, notes = 0, 0, []
    for f in wiki.source_files():
        meta, body = wiki.read_page(f)
        captures += 1
        c["category"][str(meta.get("topic", "")).split("/")[0] or "unfiled"] += 1
        rel = f.relative_to(wiki.WIKI).as_posix()
        _, _, note = run.parse_note(meta.get("note"))
        if note:
            notes.append((meta.get("title", f.stem), rel, note))

        if str(meta.get("topic", "")).split("/")[0] not in LOOK_CATEGORIES:
            continue
        if m := re.search(r"^Traits: (.+)$", body, re.M):
            looks += 1
            for key, value in traits(m.group(1)).items():
                c[key][value] += 1
        if m := re.search(r"^Palette, measured[^:]*: (.+)$", body, re.M):
            colors = re.findall(r"`(#[0-9a-f]{6})`( \(accent\))?", m.group(1))
            if colors:
                c["background"][tone(colors[0][0])] += 1  # the largest neutral area
            for h in {hue(x) for x, accent in colors if accent}:
                c["accent"][h] += 1

        seen = Counter()  # per capture, so a video with six patterns doesn't count six times
        for line in re.findall(r"^Motion: (.+)$", body, re.M):
            # "properties · easing · description", each part optional: tell them apart by shape.
            for part in (x.strip() for x in line.split("·")):
                if EASING.match(part):
                    seen[f"easing:{part.lower()}"] += 1
                elif PROPERTIES.match(part):
                    seen.update(f"property:{x.strip().lower()}" for x in part.split(","))
        for line in re.findall(r"^Facets: (.+)$", body, re.M):
            for group in line.split(";"):
                key, _, values = group.partition(":")
                if key.strip() in p.FACETS:
                    seen.update(f"{key.strip()}:{v.strip()}" for v in values.split(",") if v.strip())
        for item in seen:
            key, _, value = item.partition(":")
            c[key][value] += 1
    return {"captures": captures, "looks": looks, "counts": c, "notes": notes}


def lead(counts: Counter) -> str | None:
    """The value that clearly leads: at least 3 captures, a third of the total and
    half again as many as the runner-up."""
    counts = Counter({v: n for v, n in counts.items() if v not in ("other", "none")})  # not a choice
    top = counts.most_common(2)
    if not top:
        return None
    total, (value, n) = sum(counts.values()), top[0]
    runner = top[1][1] if len(top) > 1 else 0
    return value if n >= 3 and 3 * n >= total and 2 * n >= 3 * runner else None


def evidence_lines(ev: dict, verdict: bool = False) -> list[str]:
    labels = [("category", "Categories"), ("typography", "Typography"), ("radius", "Radius"),
              ("spacing", "Spacing"), ("depth", "Depth"), ("motion_feel", "Motion feel"),
              ("background", "Background tone"), ("accent", "Accent hues"), ("color", "Color"),
              ("layout", "Layout"), ("density", "Density"), ("component", "Components"),
              ("motion", "Motion kind"), ("property", "Animated properties"), ("easing", "Easing")]
    lines = []
    for key, label in labels:
        if counts := ev["counts"][key].most_common(8):
            line = f"- **{label}:** " + " · ".join(f"{v} {n}" for v, n in counts)
            if verdict and key != "category":
                line += f" (of {sum(ev['counts'][key].values())}; " + (
                    f"lead: {v})" if (v := lead(ev["counts"][key])) else "no clear lead)")
            lines.append(line)
    return lines


def write(ev: dict) -> str:
    counts = "\n".join(evidence_lines(ev, verdict=True))
    notes = "\n".join(f"- {title}: {note}" for title, _, note in ev["notes"]) or "(none)"
    prompt = (f"{ev['captures']} captures, {ev['looks']} with a measured look.\n\n"
              f"Counts:\n{counts}\n\nOwner's notes:\n{notes}")
    body = p.unfence(p.chat(WRITE, prompt)).strip()
    body = re.sub(r"\A# .*\n+", "", body)
    body = re.split(r"\n## Evidence\b", body, maxsplit=1)[0].strip()
    if len(body) < 200:
        raise RuntimeError(f"taste profile came back almost empty: {body[:120]!r}")
    return body


def build(dry_run: bool = False) -> bool:
    """Rewrites wiki/taste.md. False when there isn't enough to say."""
    ev = evidence()
    if dry_run:
        print(f"{ev['captures']} captures, {ev['looks']} looks, {len(ev['notes'])} notes")
        print("\n".join(evidence_lines(ev, verdict=True)))
        return False
    if ev["looks"] < MIN_LOOKS:
        print(f"[taste] only {ev['looks']} captures with a look: no profile yet")
        return False

    lines = ["What these captures have in common, as a starting point when there is no style",
             "given. The project's own design system and an explicit request always win.",
             "The evidence at the end is counted by code; the direction is a model's reading",
             "of that evidence.", "", write(ev), "", "## Evidence", "",
             f"{ev['captures']} captures, {ev['looks']} design captures with a measured look. Looks and motion "
             "count design captures only, once per capture.", "",
             *evidence_lines(ev), ""]
    if ev["notes"]:
        lines += ["## Your notes", ""]
        lines += [f"- [{title}]({rel}): {note}" for title, rel, note in ev["notes"]]
        lines.append("")
    wiki.write_page(wiki.WIKI / PATH,
                    {"title": "Taste", "summary": "Recurring choices across the captures",
                     "updated": date.today().isoformat(), "captures": ev["captures"]},
                    "# Taste\n\n" + "\n".join(lines))
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the evidence and change nothing")
    args = ap.parse_args()
    if build(args.dry_run):
        wiki.build_index()
        run.commit_wiki("docs(wiki): refresh taste profile")


if __name__ == "__main__":
    main()
