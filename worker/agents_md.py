#!/usr/bin/env python3
"""AGENTS.md: how the owner works, as rules a coding agent follows.

    python -m worker.agents_md                  # rewrite wiki/AGENTS.md and commit it
    python -m worker.agents_md --dry-run        # print each idea's evidence and tier, change nothing
    python -m worker.agents_md --no-model       # no topic filter, ideas worded as their pages state them
    python -m worker.agents_md --out ~/code/app/AGENTS.md

The DESIGN.md of how to work, in the AGENTS.md format that Claude Code, Cursor
and Codex read (agents.md: plain Markdown, no required fields). It comes from
the "## Ideas" blocks of practices topic pages, and code decides what goes in
and how firmly:

- Rules: ideas two or more captures support, or that come from a capture that
  already shaped a build (the usage log, worker/used.py).
- Worth trying: every other idea, up to TRY_PER_TOPIC per topic. Ideas with
  something to apply and a note from the owner come first, then the newest.

A model answers once per topic whether it tells a coding agent how to write,
test, review or ship code, or how to work with or build AI agents. The answer is
kept in the topic's frontmatter (`agents: true` or `false`), so the file doesn't
shift from week to week, and editing that field overrides the model. The model
also words each idea as one imperative rule and its reason; the code checks the
wording (short single lines, no links or capture numbers) and otherwise uses the
page's own "How to apply" and "Why it matters". A code block on a topic page
goes along only when it is found verbatim in a cited source note's "Code".
Every rule carries its capture numbers, so an agent that follows one can record
it in the usage log, and an idea that proves useful becomes a rule. Refreshed
after the weekly lint pass, next to DESIGN.md.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from . import pipeline as p
from . import run
from . import used
from . import wiki

PATH = "AGENTS.md"
TRY_PER_TOPIC = 3
RULE_CHARS = 220  # a worded rule or reason longer than this is not one line

# Wording that isn't a plain rule: links, capture numbers, Markdown.
BAD = re.compile(r"https?://|#\d|\[|\]|`|\*\*|^\s*[-*#>]", re.M)

FILTER = """You decide which topics of a personal knowledge base belong in an
AGENTS.md: the file a coding agent (Claude Code, Cursor, Codex) reads before it
works in a repository. A topic belongs when its ideas tell a coding agent how to
write, test, review or ship code, or how to work with or build AI agents.
Learning habits, marketing, business strategy, personal productivity or a
product's features don't.

You get each topic with its summary and the names of its ideas. Return ONLY JSON:
{"topics": {"category/slug": true}}, with true or false for every topic.
"""

WORD = """You turn ideas a user saved about how to work into the rules of an
AGENTS.md: the file a coding agent reads before it works in a repository. You get
the ideas by number, each with its claim, why it matters and how to apply it.
Return ONLY JSON:

{"rules": [{"n": 1, "rule": "one imperative sentence the agent can follow",
            "why": "one short sentence: the reason"}]}

Rules:
- One entry per idea, with its number. Keep the idea's meaning: no facts,
  numbers, tools or names that aren't in it.
- "rule" starts with a verb and says what to do, under 160 characters.
- "why" is a plain reason, under 160 characters.
- Plain sentences: no Markdown, no links, no capture numbers.
- English.
"""


# ---------------------------------------------------------------- evidence

def in_notes(code: str, rels: list[str]) -> bool:
    """Whether a code block is one a cited source note recorded under "Code"."""
    for rel in rels:
        path = wiki.WIKI / rel
        body = wiki.read_page(path)[1] if path.exists() else ""
        if "## Code" in body and any(code.strip() in m.group(3) for m in p.FENCE.finditer(body.split("## Code", 1)[1])):
            return True
    return False


def practices() -> list[dict]:
    """Every practices topic with its ideas and the evidence behind each one."""
    used_captures = {n for use in used.uses() for n in use["captures"]}
    out = []
    for t in wiki.topics():
        if t["category"] != "practices":
            continue
        meta, body = wiki.read_page(wiki.WIKI / f"{t['key']}.md")
        sources = meta.get("sources") or []
        ideas = []
        for b in wiki.blocks(body, "Ideas"):
            rels = [sources[n - 1] for n in b["cites"] if 1 <= n <= len(sources)]
            notes = [wiki.read_page(wiki.WIKI / rel)[0] for rel in rels if (wiki.WIKI / rel).exists()]
            captures = sorted({int(n.get("capture") or wiki.capture_number(rel)) for rel, n in zip(rels, notes)})
            if not captures:
                continue
            f = b["fields"]
            ideas.append({"name": b["name"], "claim": f.get("claim", ""), "why": f.get("why it matters", ""),
                          "apply": f.get("how to apply", ""), "captures": captures,
                          "used": sorted(set(captures) & used_captures),
                          "noted": any(run.parse_note(n.get("note"))[2] for n in notes),
                          "newest": max(str(n.get("captured") or "") for n in notes),
                          "code": [c for c in b["code"] if in_notes(c["code"], rels)]})
        out.append({"key": t["key"], "title": t["title"], "summary": t["summary"], "sources": len(sources),
                    "agents": meta.get("agents"), "ideas": ideas})
    return out


def tiers(topics: list[dict]) -> tuple[list[dict], list[dict]]:
    """Rules and ideas worth trying, each as [{"topic", "ideas"}], topics with
    more captures first. Decided by counting, not by the model."""
    rules, tries = [], []
    for t in sorted(topics, key=lambda t: (-t["sources"], t["title"].lower())):
        firm = [i for i in t["ideas"] if len(i["captures"]) >= 2 or i["used"]]
        firm.sort(key=lambda i: (-len(i["used"]), -len(i["captures"])))
        rest = sorted((i for i in t["ideas"] if i not in firm), key=lambda i: i["newest"], reverse=True)
        rest.sort(key=lambda i: (not i["apply"], not i["noted"]))  # stable: newest first within each group
        if firm:
            rules.append({"topic": t, "ideas": firm})
        if rest:
            tries.append({"topic": t, "ideas": rest[:TRY_PER_TOPIC]})
    return rules, tries


# ---------------------------------------------------------------- model

def decide_topics(topics: list[dict], model: bool = True, save: bool = True) -> list[dict]:
    """The topics that belong in AGENTS.md. A topic with `agents` in its
    frontmatter keeps that answer; the model answers for the others, and its
    answers are saved there (unless save is False). Without a model, or when it
    fails, an undecided topic is included and stays undecided."""
    undecided = [t for t in topics if not isinstance(t["agents"], bool)]
    if model and undecided:
        listing = "\n".join(f"- {t['key']}: {t['title']} — {t['summary']}"
                            + (f" (ideas: {'; '.join(i['name'] for i in t['ideas'])})" if t["ideas"] else "")
                            for t in undecided)
        try:
            data = p.parse_json(p.chat(FILTER, listing, as_json=True))
            answers = data.get("topics") if isinstance(data, dict) else None
        except Exception as e:  # no model, no network or no JSON: every undecided topic goes in
            print(f"[agents] topics not filtered: {e}", file=sys.stderr)
            answers = None
        for t in undecided:
            answer = (answers or {}).get(t["key"])
            if isinstance(answer, bool):
                t["agents"] = answer
                if save:
                    path = wiki.WIKI / f"{t['key']}.md"
                    meta, body = wiki.read_page(path)
                    wiki.write_page(path, {**meta, "agents": answer}, body)
    return [t for t in topics if t["agents"] is not False]


def first_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return (m.group(1) if m else text).strip()


def plain(text: str) -> str:
    text = first_sentence(text)
    return text if not text or text[-1] in ".!?" else text + "."


def worded(ideas: list[dict], model: bool = True) -> dict[int, dict]:
    """Each idea as {"rule", "why"}, by its position in `ideas`. The model's
    wording where it holds up, the page's own words otherwise."""
    out = {n: {"rule": plain(i["apply"] or i["claim"]), "why": plain(i["why"])} for n, i in enumerate(ideas)}
    if not model or not ideas:
        return out
    listing = "\n\n".join(f"[{n + 1}] {i['name']}\nClaim: {i['claim']}\nWhy it matters: {i['why']}\n"
                          f"How to apply: {i['apply']}" for n, i in enumerate(ideas))
    try:
        data = p.parse_json(p.chat(WORD, listing, as_json=True))
    except Exception as e:  # the page's own words are the rules
        print(f"[agents] page wording: {e}", file=sys.stderr)
        return out
    for item in (data.get("rules") if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict) or not str(item.get("n", "")).strip().isdigit():
            continue
        n = int(str(item["n"]).strip()) - 1
        rule, why = (re.sub(r"\s+", " ", str(item.get(k) or "")).strip() for k in ("rule", "why"))
        if n in out and 15 <= len(rule) <= RULE_CHARS and len(why) <= RULE_CHARS \
                and not BAD.search(rule) and not BAD.search(why):
            out[n] = {"rule": plain(rule), "why": plain(why)}
    return out


# ---------------------------------------------------------------- render

def cited(captures: list[int]) -> str:
    return f"({', '.join(f'#{n}' for n in captures)})"


def section(groups: list[dict], words: dict[int, dict], index: dict[int, int]) -> list[str]:
    lines = []
    for g in groups:
        lines += [f"### {g['topic']['title']}", ""]
        for idea in g["ideas"]:
            w = words[index[id(idea)]]
            lines.append(f"- {w['rule']}{' ' + w['why'] if w['why'] else ''} {cited(idea['captures'])}")
            for c in idea["code"]:
                fence = "`" * max([3, *(len(run_) + 1 for run_ in re.findall(r"`{3,}", c["code"]))])
                lines += ["", f"  {fence}{c['lang']}", *(f"  {x}" if x else "" for x in c["code"].splitlines()),
                          f"  {fence}"]
        lines.append("")
    return lines


def render(rules: list[dict], tries: list[dict], words: dict[int, dict], index: dict[int, int],
           captures: int) -> str:
    lines = ["# AGENTS.md", "",
             f"How the owner works, from {captures} saved capture{'' if captures == 1 else 's'} about engineering "
             "and agent work, distilled by second-brain. Code chose the ideas and how firmly to hold them from "
             "the evidence; a model only worded them. The project's own instructions and the user always win "
             "over this file.", "",
             "Each line ends with the captures it comes from (#12): the source notes in the owner's wiki. When "
             "one shapes what you build, record those numbers in the wiki's usage log, so the ideas that prove "
             "useful become rules.", "",
             "## Rules", ""]
    lines += ["Backed by two or more captures, or by one that already shaped a build. Follow them unless the "
              "task says otherwise.", "", *section(rules, words, index)] if rules else [
        "None yet: no idea has two captures behind it or a use in a build. Until one does, everything below "
        "is a suggestion.", ""]
    if tries:
        lines += ["## Worth trying", "",
                  f"From a single capture each, up to {TRY_PER_TOPIC} per subject: use them when they fit the task.",
                  ""]
        lines += section(tries, words, index)
    return "\n".join(lines).rstrip() + "\n"


def generate(model: bool = True, save: bool = True) -> tuple[list[dict], list[dict], str] | None:
    """(rules, ideas worth trying, the file's text), or None when no practices
    topic with ideas belongs in it."""
    topics = [t for t in decide_topics(practices(), model, save) if t["ideas"]]
    if not topics:
        return None
    rules, tries = tiers(topics)
    ideas = [i for g in rules + tries for i in g["ideas"]]
    index = {id(i): n for n, i in enumerate(ideas)}
    captures = len({n for g in rules + tries for i in g["ideas"] for n in i["captures"]})
    return rules, tries, render(rules, tries, worded(ideas, model), index, captures)


def build(model: bool = True) -> bool:
    """Rewrites wiki/AGENTS.md; removes it when nothing belongs in it. False then."""
    made = generate(model=model)
    if not made:
        (wiki.WIKI / PATH).unlink(missing_ok=True)
        print("[agents] no practices topic with ideas for a coding agent: no AGENTS.md")
        return False
    (wiki.WIKI / PATH).write_text(made[2])
    return True


def dry_run(model: bool):
    topics = practices()
    kept = {t["key"] for t in decide_topics(topics, model, save=False)}
    for t in topics:
        print(f"{t['key']}: {'in' if t['key'] in kept else 'out'}"
              f" (agents: {t['agents'] if isinstance(t['agents'], bool) else 'undecided'})")
    rules, tries = tiers([t for t in topics if t["key"] in kept and t["ideas"]])
    for label, groups in (("rule", rules), ("try", tries)):
        for g in groups:
            for i in g["ideas"]:
                print(f"  {label}: {g['topic']['key']} · {i['name']} {cited(i['captures'])}"
                      + (f" used {cited(i['used'])}" if i["used"] else "")
                      + (" · owner's note" if i["noted"] else "") + (f" · {len(i['code'])} code" if i["code"] else ""))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", help="file to write, or - to print; default: wiki/AGENTS.md, committed")
    ap.add_argument("--dry-run", action="store_true", help="print each idea's evidence and tier, change nothing")
    ap.add_argument("--no-model", action="store_true",
                    help="no topic filter and no rewording: every undecided topic, in its page's words")
    args = ap.parse_args()
    if args.dry_run:
        return dry_run(not args.no_model)
    if not args.out:
        built = build(model=not args.no_model)
        wiki.build_index()
        run.commit_wiki("docs(wiki): refresh AGENTS.md")
        return built
    made = generate(model=not args.no_model, save=False)
    if not made:
        sys.exit("[agents] no practices topic with ideas for a coding agent: no AGENTS.md")
    if args.out == "-":
        sys.stdout.write(made[2])
    else:
        Path(args.out).expanduser().write_text(made[2])
        print(f"[agents] wrote {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
