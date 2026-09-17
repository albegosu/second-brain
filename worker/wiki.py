"""The wiki: what remains of each capture, in Markdown and in English.

    wiki/index.md                            written by code: topics and the patterns they hold
    wiki/<category>/<topic>.md               one page per topic; the model writes the body
    wiki/sources/<yyyy-mm>/<id>-<slug>.md    one note per capture; written by code

The model picks category and topic, and writes each topic page from all of its
source notes, so pages don't drift the way incremental merges do. The structure
(frontmatter, "See also", sources list, index) is written by code, so a bad model
answer can at most spoil a text, never the navigation. Reorganizing topics lives
in worker/lint.py. No git here: commit and push happen in run.commit_wiki().
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

from . import pipeline as p

WIKI = Path(os.environ.get("BRAIN_WIKI", p.ROOT / "wiki")).expanduser().resolve()

CATEGORIES = {
    "design": "UI patterns, interactions, motion and visual styles",
    "features": "Product functionality and behaviours worth building",
    "tools": "Tools, libraries and services",
    "practices": "How to work: engineering practices, agent workflows and lessons from articles",
}

# Version of the analysis a source note was written with. `run --reanalyze`
# without a URL only redoes notes below it, so an interrupted run resumes.
ANALYZED = 2

# What the Shortcut's intent menu tells the classifier.
INTENTS = {
    "pattern to reuse": "a UI pattern or a product feature to reuse (design or features)",
    "visual style": "a visual look to reuse (a design topic whose slug starts with style-)",
    "tool to try": "a tool to try (tools)",
    "idea to read": "ideas about how to work (practices)",
}

# Each category's block section on a topic page, as the index labels it.
SECTIONS = ("Patterns", "Options", "Ideas", "Styles")

# Characters of source notes a topic page is written from. Past this, each note
# is trimmed evenly (the head of a note holds what matters most).
SOURCE_BUDGET = 48_000

CLASSIFY = """You file captures into a personal knowledge base. Categories:
__CATEGORIES__

Return ONLY JSON:
{"category": "design | features | tools | practices",
 "topic": "slug of an existing topic, or a new kebab-case slug",
 "topic_title": "short Title Case name for the topic",
 "topic_summary": "one line: what the topic covers",
 "title": "short title for this capture",
 "summary": "1-2 sentences: what this capture is and why it is worth keeping",
 "tags": ["3-6 lowercase keywords"]}

Rules:
- Title, summary, category and topic come only from what the capture contains:
  what the vision model saw, the post or page text, its key ideas and the user's
  note. Never guess what a link or a short caption is about.
- Reuse an existing topic whenever the capture is about the same subject. Create a
  new topic only for a genuinely different subject.
- A topic is a subject many captures can share ("expand-collapse-disclosure",
  "toast-notifications", "ascii-art-generators"), never a single post
  ("jakub-demo"), and never a catch-all ("micro-interactions", "ui-patterns").
- design = how an interface looks and moves. features = what a product does for its
  user. tools = something you use to build (app, library, service, generator).
  practices = how to work: engineering practices, workflows with AI agents,
  learning, product thinking; usually an article or a thread with key ideas.
- A capture that is only a look (a design shot, poster, moodboard or composition,
  with no product, tool, interaction or feature behind it) goes to a design topic
  for that family of looks, with a slug starting with "style-"
  ("style-dark-high-contrast", "style-editorial-serif"). Reuse an existing style-
  topic when the look matches.
- The website, repository, launch, demo or announcement of a tool, library,
  product or AI model is filed by what it is (tools, or features), never as a
  style, even when only its look was analyzed.
- The user's intent, when given, says what they want from the capture: follow it
  unless the capture clearly contradicts it.
- Write in English, whatever the language of the capture.
""".replace("__CATEGORIES__", "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items()))

COMPOSE = """You write one topic page of a personal knowledge base. An AI coding
assistant reads it right before building something, so it has to be directly
actionable. Write Markdown, in English, from the numbered source notes you get.

Structure:
- Start with 1-2 sentences on what the topic covers. No heading before them.
- design and features topics: a "## Patterns" section with one block per distinct
  pattern found in the sources, headed "### <Pattern name> [n]". The same pattern
  seen in several sources is ONE block citing all of them, like [1, 3]. Inside each
  block, in this order, only the lines the sources support:
  **Use it when:** one line.
  **How it works:** numbered steps: initial state, trigger, what changes and in
  which order, end state.
  **Motion:** animated properties · easing (leave the line out if nothing moves).
  **Watch out:** trade-offs or pitfalls the sources state or clearly imply.
- Topics marked "Kind: visual style" (instead of Patterns): a "## Styles" section
  with one "### <Style name> [n]" block per distinct look. Captures that share a
  look are ONE block citing all of them. Inside each block:
  **Tokens:** the measured palette colors that belong to the interface (hex codes
  from the notes), type family, radius, spacing, depth and motion feel from the
  notes' traits.
  **Composition:** layout, hierarchy and contrast.
  **Do:** and **Don't:** what the look depends on and what would break it.
  **Use it for:** one line.
- tools topics: an "## Options" section with one "### <Tool name> [n]" block per
  tool: **What it does:**, **Use it when:**, **Link:** (only a URL from that
  source's "Links", never one you make up), **Notes:** (limits, platform, pricing,
  only as stated). Tools a source describes in exactly the same words share one
  block headed with all their names ("### TypeUI · DesignMD [2]").
- practices topics: an "## Ideas" section with one "### <Idea name> [n]" block per
  idea: **Claim:**, **Why it matters:**, **How to apply:**, **Watch out:**.
- With two or more patterns, styles, options or ideas: a "## Choosing" section, a
  few bullets on which one fits which situation.

Rules:
- Nothing gets dropped: every "### " entry under a source note's "What it shows"
  (what the vision model actually saw) or "Key ideas" gets its own block, even if
  it only loosely fits the topic. For tools topics, every tool the notes describe
  gets a block.
- Leave out a field that has nothing to say; never write "None" or "Not stated".
- Ideas that only appear in a post's text or a page excerpt, not under "What it
  shows" (tip lists, generic advice), don't get blocks: list them briefly under a
  final "## Also mentioned" section, one bullet each with its [n].
- Every block and every claim cites its sources with [n].
- Only what the sources say: no invented details, numbers or framework names.
- Pattern names are short and specific ("Slide-to-confirm", "Staggered card
  reveal"), never the post's title.
- Palettes, hex codes and style traits stay in the source notes, unless the topic
  is a visual style.
- If sources disagree, say so in the block.
- Plain Markdown: headings, lists, bold. No tables, LaTeX or HTML.
- Don't write the page title, frontmatter, "See also" or a sources list: they are
  added automatically. Return only the Markdown body.
"""


# ---------------------------------------------------------------- files

def slugify(text: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[:60].strip("-") or "untitled"


def read_page(path: Path) -> tuple[dict, str]:
    text = path.read_text()
    m = re.match(r"---\n(.*?)\n---\n?(.*)", text, re.S)
    if not m:
        return {}, text.strip()
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        try:
            meta[key.strip()] = json.loads(value.strip())
        except json.JSONDecodeError:  # hand-edited as plain YAML
            meta[key.strip()] = value.strip()
    return meta, m.group(2).strip()


def write_page(path: Path, meta: dict, body: str):
    """Frontmatter with JSON values: valid YAML, readable without dependencies."""
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in meta.items())
    path.write_text(f"---\n{head}\n---\n\n{body.strip()}\n")


def topic_files() -> list[Path]:
    return sorted(f for cat in CATEGORIES for f in (WIKI / cat).glob("*.md"))


def topic_key(path: Path) -> str:
    return f"{path.parent.name}/{path.stem}"


def topics() -> list[dict]:
    out = []
    for f in topic_files():
        meta, body = read_page(f)
        out.append({"key": topic_key(f), "category": f.parent.name, "slug": f.stem,
                    "title": meta.get("title", f.stem), "summary": meta.get("summary", ""),
                    "sources": meta.get("sources", []), "related": meta.get("related", []),
                    "patterns": pattern_names(body), "label": section_label(body)})
    return out


def source_files() -> list[Path]:
    return sorted((WIKI / "sources").glob("*/*.md"))


def capture_number(rel: str) -> int:
    name = rel.rsplit("/", 1)[-1]
    return int(name.split("-", 1)[0]) if name.split("-", 1)[0].isdigit() else 0


def find_source(url: str) -> tuple[int, dict] | None:
    """The note of an already filed URL. The wiki is the capture registry: there
    is no other database recording what was processed."""
    for f in source_files():
        meta, _ = read_page(f)
        if meta.get("url") == url:
            return int(meta.get("capture") or capture_number(f.name)), meta
    return None


def next_capture_id() -> int:
    return max((capture_number(f.name) for f in source_files()), default=0) + 1


def strip_generated(body: str) -> str:
    """The body the model wrote, without the sections the code appends."""
    return re.split(r"(?:^|\n)## (?:See also|Sources)\n", body, maxsplit=1)[0].strip()


def pattern_names(body: str) -> list[str]:
    """The ### blocks under "## Patterns", "## Options", "## Ideas" or "## Styles",
    without citations."""
    names, section = [], None
    for line in body.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
        elif line.startswith("### ") and section in SECTIONS:
            names.append(re.sub(r"\s*\[\d+(?:\s*,\s*\d+)*\]", "", line[4:]).strip())
    return names


def section_label(body: str) -> str:
    """The block section a topic page uses, for the index."""
    return next((s for s in SECTIONS if re.search(rf"^## {s}\s*$", body, re.M)), "Patterns")


def write_topic(path: Path, meta: dict, body: str):
    lines = [strip_generated(body), ""]
    related = [key for key in meta.get("related", []) if (WIKI / f"{key}.md").exists()]
    if related:
        lines += ["## See also", ""]
        for key in related:
            other, _ = read_page(WIKI / f"{key}.md")
            lines.append(f"- [{other.get('title', key)}](../{key}.md) — {other.get('summary', '')}")
        lines.append("")
    lines += ["## Sources", ""]
    for i, rel in enumerate(meta["sources"], 1):
        src = WIKI / rel
        m = read_page(src)[0] if src.exists() else {}
        lines.append(f"{i}. [{m.get('title', rel)}](../{rel}) — {m.get('url', '')}")
    write_page(path, meta, "\n".join(lines))


def retarget_source(rel: str, key: str, topic_title: str):
    """Point a source note at another topic: frontmatter and its "Filed under" link."""
    path = WIKI / rel
    meta, body = read_page(path)
    meta["topic"] = key
    body = re.sub(r"^Filed under \[[^\]]*\]\([^)]*\)",
                  f"Filed under [{topic_title}](../../{key}.md)", body, count=1, flags=re.M)
    write_page(path, meta, body)


def detach(cid: int):
    """Re-analysis: the previous note leaves its topic. The topic keeps its current
    text until it's rewritten; a topic left without sources is deleted."""
    for old in (WIKI / "sources").glob(f"*/{cid:04d}-*.md"):
        rel = old.relative_to(WIKI).as_posix()
        old.unlink()
        for page in topic_files():
            meta, body = read_page(page)
            if rel not in meta.get("sources", []):
                continue
            meta["sources"] = [s for s in meta["sources"] if s != rel]
            if meta["sources"]:
                write_topic(page, meta, body)
            else:
                page.unlink()


def build_index():
    known = topics()
    lines = ["# Second brain", "",
             "Generated by the worker from each page's frontmatter: edits here are overwritten.",
             "Find the topic (or pattern) you need here and open only that page; source notes",
             "hold the details and the links to the originals.", ""]
    for cat, about in CATEGORIES.items():
        mine = sorted((t for t in known if t["category"] == cat), key=lambda t: t["title"].lower())
        lines += [f"## {cat.capitalize()}", "", f"_{about}_", ""]
        for t in mine:
            n = len(t["sources"])
            lines.append(f"- [{t['title']}]({t['key']}.md) — {t['summary']} ({n} source{'' if n == 1 else 's'})")
            if t["patterns"]:
                lines.append(f"  {t['label']}: {' · '.join(t['patterns'])}")
        if not mine:
            lines.append("_Nothing yet._")
        lines.append("")

    recent = []
    for f in source_files():
        m, _ = read_page(f)
        recent.append((str(m.get("captured", "")), capture_number(f.name), f, m))
    if recent:
        recent.sort(key=lambda r: (r[0], r[1]), reverse=True)
        lines += ["## Recent captures", ""]
        lines += [f"- {day} · [{m.get('title', f.stem)}]({f.relative_to(WIKI).as_posix()}) → {m.get('topic', '')}"
                  for day, _, f, m in recent[:15]]
        lines.append("")

    WIKI.mkdir(parents=True, exist_ok=True)
    (WIKI / "index.md").write_text("\n".join(lines))


# ---------------------------------------------------------------- capture

def _quote(text: str, limit: int = 1500) -> str:
    text = text.strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + " …"
    return "\n".join(f"> {line}" if line.strip() else ">" for line in text.splitlines())


def source_body(*, note, text, page, patterns, style, ideas=(), long_text=False) -> str:
    """Everything known about the capture. It is both the classifier's input and
    the body of the note, so it doesn't depend on the model that writes the wiki.
    long_text keeps more of the page (an article is the capture itself)."""
    out = []
    if note:
        out += ["## Note", "", _quote(note), ""]

    shown = [pt for pt in patterns if isinstance(pt, dict) and pt.get("title")]
    if shown:
        out += ["## What it shows", ""]
        for pt in shown:
            out += [f"### {pt['title']}", ""]
            out += [line for key in ("summary", "behavior", "notes") if pt.get(key)
                    for line in (str(pt[key]), "")]
            m = pt.get("motion_spec") or {}
            motion = " · ".join(x for x in (", ".join(m.get("properties") or []),
                                            m.get("easing"), m.get("description")) if x)
            if motion:
                out += [f"Motion: {motion}", ""]
            facets = "; ".join(f"{k}: {', '.join(v if isinstance(v, list) else [v])}"
                               for k, v in (pt.get("facets") or {}).items() if v)
            if facets:
                out += [f"Facets: {facets}", ""]

    kept = [i for i in ideas if isinstance(i, dict) and i.get("title") and i.get("claim")]
    if kept:
        out += ["## Key ideas", ""]
        for idea in kept:
            out += [f"### {idea['title']}", "", str(idea["claim"]), ""]
            out += [f"{label}: {idea[key]}" for key, label in (("why", "Why"), ("apply", "Apply")) if idea.get(key)]
            out.append("")

    if style and (style.get("description") or style.get("palette")):
        out += ["## Visual style", ""]
        if traits := " · ".join(style[k] for k in p.STYLE if style.get(k)):
            out += [f"Traits: {traits}", ""]
        if style.get("description"):
            out += [style["description"], ""]
        if style.get("palette"):
            colors = ", ".join(f"`{c['hex']}`" + (" (accent)" if c.get("role") == "accent" else "")
                               for c in style["palette"])
            out += [f"Palette, measured from pixels (includes content colors): {colors}", ""]

    # The post's own words, unless they only repeat the page's title and description
    # (a post that links to a page keeps both).
    derived = "\n\n".join(x for x in ((page or {}).get("title"), (page or {}).get("description")) if x)
    if text and text.strip() not in derived:
        out += ["## Post text", "", _quote(text), ""]
    if page:
        out += ["## Page", ""]
        if page.get("title"):
            out += [f"**{page['title']}**", ""]
        if page.get("description"):
            out += [page["description"], ""]
        if page.get("excerpt"):
            out += [_quote(page["excerpt"], 6000 if long_text else 1200), ""]
    return "\n".join(out).strip()


def classify(header: str, body: str, known: list[dict], intent: str | None = None) -> dict:
    listing = "\n".join(f"- {t['key']}: {t['title']} — {t['summary']}" for t in known) or "(none yet)"
    hint = f"User's intent: {INTENTS[intent]}\n\n" if intent in INTENTS else ""
    data = p.parse_json(p.chat(CLASSIFY, f"Existing topics:\n{listing}\n\n{hint}Capture:\n{header}\n\n{body}",
                               as_json=True))
    if isinstance(data, list) and data and isinstance(data[0], dict):  # sometimes wrapped in [ ]
        data = data[0]
    if not isinstance(data, dict):
        raise RuntimeError(f"unexpected classification: {str(data)[:200]}")
    return data


URL = re.compile(r"https?://[^\s<>\"'`)\]]+")
# Where a post lives, not what it points to: no use as a tool's link.
POST_HOSTS = re.compile(r"https?://(?:[\w-]+\.)*(?:x\.com|twitter\.com|t\.co|twimg\.com|instagram\.com|linkedin\.com)(?:[/:?]|$)", re.I)


def links(meta: dict, body: str) -> list[str]:
    """The outside URLs a source note contains, for tools' Link lines. Found by
    code so the model can only pick among real ones."""
    found = [u.rstrip(".,;:!?*") for u in URL.findall(body)]
    if meta.get("source") not in ("x", "instagram", "linkedin"):  # a page or repository is itself the link
        found.insert(0, str(meta.get("url") or ""))
    return list(dict.fromkeys(u for u in found if u and not POST_HOSTS.match(u)))[:12]


def compose(key: str, meta: dict) -> str:
    """Write a topic page body from all of its source notes."""
    notes, looks = [], 0
    for i, rel in enumerate(meta["sources"], 1):
        src_meta, src_body = read_page(WIKI / rel)
        src_body = re.sub(r"\A# .*\n+", "", src_body)  # the note's own title
        src_body = re.sub(r"^Filed under .*\n+", "", src_body, flags=re.M)
        looks += "## Visual style" in src_body and "## What it shows" not in src_body
        found = links(src_meta, src_body)
        notes.append((f"[{i}] {src_meta.get('title', rel)} — {src_meta.get('url', '')}\n"
                      f"{src_meta.get('summary', '')}" + (f"\nLinks: {', '.join(found)}" if found else ""),
                      src_body))
    category, slug = key.split("/")
    # A style topic: named so, or a design topic whose captures are mostly looks.
    style_topic = slug.startswith("style-") or (category == "design" and looks * 2 > len(notes))
    per_note = SOURCE_BUDGET // max(len(notes), 1)
    listing = "\n\n".join(f"{head}\n{body[:per_note]}" for head, body in notes)
    prompt = (f"Topic: {meta['title']} ({key}) — {meta.get('summary', '')}\n"
              f"Category: {category}" + ("\nKind: visual style" if style_topic else "") +
              f"\n\nSource notes:\n\n{listing}")
    body = p.unfence(p.chat(COMPOSE, prompt, num_ctx=32768)).strip()
    # Fields the model filled with nothing, despite the prompt.
    body = re.sub(r"^\*\*[A-Za-z][^*\n]{0,40}:\*\*[ \t]*(?:none|n/?a|not (?:stated|specified|mentioned))\.?[ \t]*\n?",
                  "", body, flags=re.M | re.I)
    body = re.sub(r"\A# .*\n+", "", body)  # the code writes the title
    body = strip_generated(body)  # in case it writes its own "See also" or sources
    # Each "**Field:**" line as its own paragraph; otherwise Markdown joins them into one.
    body = re.sub(r"(?<!\n)\n(\*\*[A-Z][^*\n]{0,40}:\*\*)", r"\n\n\1", body)
    body = re.sub(r"^(### .+)\n(?!\n)", r"\1\n\n", body, flags=re.M)
    # Steps written inline ("1. … 2. …") become a real numbered list.
    body = re.sub(r"^(\*\*How it works:\*\*)[ \t]*(1\.\s.*\s2\.\s.*)$",
                  lambda m: m.group(1) + "\n\n" + re.sub(r"\s+(?=\d+\.\s)", "\n", m.group(2)).strip(),
                  body, flags=re.M)
    if len(body) < 200:
        raise RuntimeError(f"topic page for {key} came back almost empty: {body[:120]!r}")
    return body


def file_capture(*, cid: int, captured: str, url: str, source: str, media: dict,
                 note: str | None, patterns: list, style: dict | None,
                 style_name: str | None = None, ideas: list | None = None,
                 intent: str | None = None) -> dict:
    body = source_body(note=note, text=media.get("text"), page=media.get("page"),
                       patterns=patterns, style=style, ideas=ideas or [],
                       long_text=bool(media.get("article")))
    header = f"URL: {url}\nFrom: {source}" + (f" · @{media['author']}" if media.get("author") else "")

    detach(cid)
    known = topics()
    cls = classify(header, body, known, intent)

    category = cls.get("category") if cls.get("category") in CATEGORIES else "features"
    slug = slugify(str(cls.get("topic") or cls.get("topic_title") or "misc"))
    if style_name:  # the note wins: "style: x" files under design/style-x
        category, slug = "design", f"style-{slugify(style_name)}"
        cls["topic_title"] = f"Style: {style_name}"
        cls["topic_summary"] = f"Visual style '{style_name}', collected from several captures"
    for t in known:  # an existing topic wins: no duplicates from category hesitation
        if t["slug"] == slug:
            category = t["category"]
            break
    key = f"{category}/{slug}"

    title = str(cls.get("title") or (patterns[0].get("title") if patterns and isinstance(patterns[0], dict) else "")
                or url)
    summary = str(cls.get("summary") or "")
    tags = [slugify(str(t)) for t in (cls.get("tags") or []) if str(t).strip()][:6]

    page = WIKI / f"{key}.md"
    new_topic = not page.exists()
    if new_topic:
        meta = {"title": str(cls.get("topic_title") or slug.replace("-", " ").title()),
                "category": category, "summary": str(cls.get("topic_summary") or summary),
                "sources": []}
    else:
        meta, _ = read_page(page)

    rel = f"sources/{captured[:7]}/{cid:04d}-{slugify(title)}.md"
    write_page(WIKI / rel,
               {"title": title, "summary": summary, "url": url, "source": source,
                "author": media.get("author"), "captured": captured,
                "topic": key, "tags": tags, "capture": cid, "note": note, "analyzed": ANALYZED},
               f"# {title}\n\n{summary}\n\n"
               f"Filed under [{meta['title']}](../../{key}.md) · [original]({url})\n\n{body}")

    meta["sources"] = sorted({*meta.get("sources", []), rel}, key=capture_number)
    meta["updated"] = date.today().isoformat()
    write_topic(page, meta, compose(key, meta))
    build_index()
    return {"category": category, "topic": slug, "topic_title": meta["title"], "title": title,
            "summary": summary, "new_topic": new_topic, "source": rel}
