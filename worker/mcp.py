#!/usr/bin/env python3
"""The wiki over MCP, for clients that don't load skills (Claude Desktop, Cursor…).

    bin/second-brain-mcp                     # what a client runs: loads .env, then this
    BRAIN_WIKI=~/wiki python -m worker.mcp   # the same, by hand

A Model Context Protocol server on stdio, without dependencies: one JSON-RPC
message per line in, one per line out, logs on stderr. It only reads the local
wiki folder: no tool writes, calls a model or reaches the network, so nothing
leaves the machine except what the client itself sends on. Tools:

    get_index         the map: topics, what each holds, uses, latest captures
    search            words across topic pages and source notes, topics first
    get_topic         a topic page by name
    get_page          any wiki page by its path (index, taste, DESIGN.md, a source note)
    recent_captures   the latest captures, newest first
    get_frames        what a visual capture looked like, as an image
    get_design_md     the taste, its light or dark twin, or a style (one of its looks) as a DESIGN.md
"""
from __future__ import annotations

import base64
import contextlib
import json
import re
import sys
from pathlib import Path

from . import design_md
from . import wiki

NAME, VERSION = "second-brain", "1.0.0"
# Newest first. The tools here mean the same in all of them.
PROTOCOLS = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
CATEGORY = {"type": "string", "enum": list(wiki.CATEGORIES), "description": "Only this category"}
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}

INSTRUCTIONS = """The user's personal knowledge base: interface patterns and styles, product
features, tools and working practices they saved from posts and pages, filed by
a model into a Markdown wiki. Check it before designing or building UI, choosing
a tool or approaching agent work, in case they saved a reference.

Start with get_index and open only the topics that match (get_topic), matching
on the blocks each topic lists, not only on its title. Use search when the index
doesn't obviously cover it. Topic pages cite their sources as [n]; open a source
note with get_page for the specifics, and look at get_frames before building a
look, a layout or an interaction: the text describes the reference, the image is
the reference. With no style given by the user or the project, build from
get_design_md. Say which pages you used. The wiki holds references and ideas
written by a model, not specs."""

TOOLS = [
    {"name": "get_index",
     "title": "Wiki index",
     "description": "The wiki's map: every topic by category with a one-line summary, the patterns, styles, "
                    "options or ideas it holds and how often it was used in a build, plus the latest captures. "
                    "Read it first, then open only the matching topics.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "search",
     "title": "Search the wiki",
     "description": "Find the topic pages and source notes that mention words, the pages with the most of them "
                    "first, topic pages before source notes on a tie. Everything is in English.",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "Words to look for, in English"},
         "category": CATEGORY,
         "limit": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10}}}},
    {"name": "get_topic",
     "title": "Topic page",
     "description": "A topic page by its title or slug (\"loading states\", \"design/loading-states\"): one "
                    "block per pattern, style, option or idea, then Choosing, See also and the Sources that "
                    "its [n] citations point to.",
     "inputSchema": {"type": "object", "required": ["name"], "properties": {
         "name": {"type": "string", "description": "The topic's title, slug or category/slug"}}}},
    {"name": "get_page",
     "title": "Wiki page",
     "description": "Any Markdown page of the wiki by its path, as the index and the pages link it: a source "
                    "note (sources/2026-09/0007-….md, with the user's note, the measured palette and the link "
                    "to the original), a topic page, taste.md, DESIGN.md or usage.md.",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {
         "path": {"type": "string", "description": "Path inside the wiki, like design/loading-states.md or "
                                                   "../sources/2026-09/0007-x.md"}}}},
    {"name": "recent_captures",
     "title": "Recent captures",
     "description": "The latest captures, newest first: date, number, title, topic, the source note's path "
                    "and the original link.",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
         "category": CATEGORY}}},
    {"name": "get_frames",
     "title": "Capture frames",
     "description": "What a visual capture looked like, as one image: up to four frames in time order, left "
                    "to right and top to bottom, or the shared image itself. Look at it before building from "
                    "the capture.",
     "inputSchema": {"type": "object", "required": ["capture"], "properties": {
         "capture": {"type": "integer", "minimum": 1,
                     "description": "The capture number: the 0007 in sources/2026-09/0007-….md, or [n] "
                                    "resolved through a topic's Sources"}}}},
    {"name": "get_design_md",
     "title": "DESIGN.md",
     "description": "Design tokens to build UI from, in the Google Labs DESIGN.md format: color roles tuned "
                    "to WCAG AA, type, radius, spacing, components and rules. Without a style, the user's "
                    "taste across all their captures (with tone, its light or dark twin when the captures "
                    "split between the two). With a style topic, that look; with look, one of the topic's "
                    "other looks. A primary marked Low confidence may be a photo's color: check the frames.",
     "inputSchema": {"type": "object", "properties": {
         "style": {"type": "string", "description": "A style topic's slug, like style-editorial or editorial"},
         "look": {"type": "string", "description": "With style: one of the topic's looks, by name"},
         "tone": {"type": "string", "enum": ["light", "dark"],
                  "description": "Without style: the taste for that background tone"}}}},
]
for tool in TOOLS:
    tool["annotations"] = READ_ONLY


class ToolError(Exception):
    """A tool could not answer; the message goes back to the model."""


# ---------------------------------------------------------------- tools

def inside(rel: str, suffixes: tuple[str, ...] = (".md",)) -> Path:
    """A path inside the wiki, as pages link it (../sources/…), never outside it."""
    clean = re.sub(r"^(?:\.\.?/)+", "", rel.strip().replace("\\", "/")).removeprefix("wiki/")
    root = wiki.WIKI.resolve()
    path = (root / clean).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() not in suffixes:
        raise ToolError(f"{rel!r} is not a wiki page: give a path like design/loading-states.md")
    if not path.is_file():
        raise ToolError(f"no page {clean} in the wiki: check get_index")
    return path


def get_index() -> str:
    path = wiki.WIKI / "index.md"
    return path.read_text() if path.exists() else wiki.index_text()


def pages(category: str | None = None) -> list[tuple[Path, dict, str, bool]]:
    """Every topic page and source note: path, frontmatter, body, is a topic."""
    out = []
    for f in wiki.topic_files():
        if not category or f.parent.name == category:
            out.append((f, *wiki.read_page(f), True))
    for f in wiki.source_files():
        meta, body = wiki.read_page(f)
        if not category or str(meta.get("topic", "")).startswith(f"{category}/"):
            out.append((f, meta, body, False))
    return out


def search(query: str, category: str | None = None, limit: int = 10) -> str:
    limit = max(1, min(int(limit), 30))
    terms = [t for t in re.findall(r"[\w-]+", query.lower()) if len(t) > 1]
    if not terms:
        raise ToolError("give one or more words to look for")
    scored = []
    for f, meta, body, is_topic in pages(category):
        title, text = str(meta.get("title", f.stem)), body.lower()
        hits = {t: text.count(t) + 5 * title.lower().count(t) for t in terms}
        found = sum(1 for n in hits.values() if n)
        if found:
            scored.append((found, (2 if is_topic else 1) * sum(hits.values()), f, title, body))
    if not scored:
        return f"Nothing in the wiki mentions {query!r}."
    scored.sort(key=lambda s: (-s[0], -s[1], str(s[2])))  # most words matched, then most mentions
    lines = [f"{min(limit, len(scored))} of {len(scored)} matching pages, best first:", ""]
    for found, _, f, title, body in scored[:limit]:
        partial = f" ({found} of {len(terms)} words)" if found < len(terms) else ""
        lines.append(f"- {f.relative_to(wiki.WIKI).as_posix()} — {title}{partial}")
        snippets = [line.strip() for line in body.splitlines() if any(t in line.lower() for t in terms)]
        lines += [f"  > {s[:220]}{'…' if len(s) > 220 else ''}" for s in snippets[:2]]
    return "\n".join(lines)


def get_topic(name: str) -> str:
    want = wiki.slugify(name.removesuffix(".md").split("/")[-1])
    known = wiki.topics()
    exact = [t for t in known if want in (t["slug"], wiki.slugify(t["title"]))]
    near = exact or [t for t in known if want in t["slug"] or want in wiki.slugify(t["title"])]
    if len(near) == 1:
        return (wiki.WIKI / f"{near[0]['key']}.md").read_text()
    if near:
        return "Several topics match; ask for one of them:\n" + "\n".join(
            f"- {t['key']} — {t['title']}: {t['summary']}" for t in near)
    raise ToolError(f"no topic {name!r}: check get_index or search")


def recent_captures(limit: int = 10, category: str | None = None) -> str:
    limit, rows = max(1, min(int(limit), 50)), []
    for f, meta, _, _ in (page for page in pages(category) if not page[3]):
        rows.append((str(meta.get("captured", "")), wiki.capture_number(f.name), f, meta))
    if not rows:
        return "No captures yet."
    rows.sort(key=lambda r: (r[0], r[1]), reverse=True)
    lines = []
    for day, n, f, meta in rows[:limit]:
        url = wiki.shown_url(meta)
        lines.append(f"- {day} · #{n} {meta.get('title', f.stem)} → {meta.get('topic', 'unfiled')} · "
                     f"{f.relative_to(wiki.WIKI).as_posix()}" + (f" · {url}" if url else ""))
    return "\n".join(lines)


def get_frames(capture: int) -> list[dict]:
    notes = sorted((wiki.WIKI / "sources").glob(f"*/{int(capture):04d}-*.md"))
    if not notes:
        raise ToolError(f"no capture #{capture}")
    image = next((notes[0].with_suffix(s) for s in (".jpg", ".jpeg", ".png") if notes[0].with_suffix(s).exists()),
                 None)
    if not image:
        raise ToolError(f"capture #{capture} has no frames: it isn't a visual capture")
    mime = "image/png" if image.suffix == ".png" else "image/jpeg"
    return [{"type": "text", "text": f"Capture #{capture}, {notes[0].relative_to(wiki.WIKI).as_posix()}: up to "
                                     "four frames in time order, left to right and top to bottom."},
            {"type": "image", "data": base64.b64encode(image.read_bytes()).decode(), "mimeType": mime}]


def get_design_md(style: str | None = None, look: str | None = None, tone: str | None = None) -> str:
    if look and not style:
        raise ToolError("look needs style: the style topic it belongs to")
    if not style:  # the weekly files have the model's prose; the template's tokens are the same
        d = design_md.taste_design(tone) if tone else None
        twin = d and d["pair"] and d["pair"]["path"] != design_md.PATH
        stored = wiki.WIKI / (design_md.tone_path(tone) if twin else design_md.PATH)
        if (d or not tone) and stored.exists():
            return stored.read_text()
    try:
        made = design_md.generate(style, model=False, look=look, tone=tone)
    except design_md.NoLook as e:
        raise ToolError(str(e)) from None
    if made:
        return made[2]
    if style:
        known = ", ".join(t["slug"] for t in design_md.style_topics()) or "none"
        raise ToolError(f"no style topic {style!r} with a look (style topics: {known})")
    raise ToolError(f"no {tone} taste: the captures don't split between light and dark" if tone
                    else "not enough design captures with a look for a taste yet")


HANDLERS = {"get_index": get_index, "search": search, "get_topic": get_topic, "get_page": None,
            "recent_captures": recent_captures, "get_frames": get_frames, "get_design_md": get_design_md}


def call(name: str, args: dict) -> dict:
    """A tool's result. Errors the model can act on come back as isError results."""
    schema = next(t["inputSchema"] for t in TOOLS if t["name"] == name)
    unknown = set(args) - set(schema.get("properties", {}))
    missing = [k for k in schema.get("required", []) if args.get(k) in (None, "")]
    try:
        if unknown or missing:
            raise ToolError(f"{name} takes {', '.join(schema['properties']) or 'no arguments'}"
                            + (f"; missing {', '.join(missing)}" if missing else ""))
        if name == "get_page":
            out = inside(str(args["path"])).read_text()
        else:
            out = HANDLERS[name](**args)
    except ToolError as e:
        return {"content": [{"type": "text", "text": str(e)}], "isError": True}
    except (TypeError, ValueError) as e:  # an argument of the wrong type
        return {"content": [{"type": "text", "text": f"bad arguments for {name}: {e}"}], "isError": True}
    return {"content": out if isinstance(out, list) else [{"type": "text", "text": out}], "isError": False}


# ---------------------------------------------------------------- protocol

EMPTY = {"resources/list": "resources", "resources/templates/list": "resourceTemplates", "prompts/list": "prompts"}


class RpcError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def handle(msg) -> dict | None:
    """One JSON-RPC message in, its response out (None for a notification)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0" or not isinstance(msg.get("method"), str):
        if isinstance(msg, dict) and "method" not in msg and ("result" in msg or "error" in msg):
            return None  # a response to a request this server never sends
        return {"jsonrpc": "2.0", "id": msg.get("id") if isinstance(msg, dict) else None,
                "error": {"code": -32600, "message": "invalid request"}}
    method, params, notification = msg["method"], msg.get("params") or {}, "id" not in msg
    try:
        result = dispatch(method, params)
    except RpcError as e:
        return None if notification else {"jsonrpc": "2.0", "id": msg["id"],
                                          "error": {"code": e.code, "message": str(e)}}
    except Exception as e:  # a bug: report it, keep serving
        print(f"[mcp] {method} failed: {e!r}", file=sys.stderr)
        return None if notification else {"jsonrpc": "2.0", "id": msg["id"],
                                          "error": {"code": -32603, "message": f"internal error: {e}"}}
    return None if notification else {"jsonrpc": "2.0", "id": msg["id"], "result": result}


def dispatch(method: str, params: dict) -> dict:
    if method == "initialize":
        asked = params.get("protocolVersion")
        return {"protocolVersion": asked if asked in PROTOCOLS else PROTOCOLS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": NAME, "title": "second-brain wiki", "version": VERSION},
                "instructions": INSTRUCTIONS}
    if method == "ping" or method.startswith("notifications/"):
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in HANDLERS:
            raise RpcError(-32602, f"unknown tool: {name}")
        if not isinstance(args, dict):
            raise RpcError(-32602, "arguments must be an object")
        return call(name, args)
    if method in EMPTY:  # some clients ask even when the server doesn't offer them
        return {EMPTY[method]: []}
    raise RpcError(-32601, f"method not found: {method}")


def serve(stdin=sys.stdin, stdout=sys.stdout):
    """Reads messages until stdin closes. Anything the wiki code prints goes to
    stderr, so stdout only ever carries protocol messages."""
    print(f"[mcp] serving {wiki.WIKI}", file=sys.stderr)
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            out = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        else:
            with contextlib.redirect_stdout(sys.stderr):
                out = ([r for r in map(handle, msg) if r] or None) if isinstance(msg, list) else handle(msg)
        if out:
            stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
