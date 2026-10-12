#!/usr/bin/env python3
"""Lint pass: keeps the wiki organized as it grows.

    python -m worker.lint                  # plan, apply, rewrite changed topics, rebuild the index
    python -m worker.lint --dry-run        # only print the validated plan
    python -m worker.lint --recompose-all  # also rewrite every topic page from its sources

The model proposes merging duplicate topics, splitting catch-all topics, moving
misfiled captures and relating topics. A topic far larger than the rest of its
category (a catch-all) also gets its own split request, since in the plan of the
whole wiki the model rarely splits anything. The code validates the plan (every source
note ends up in exactly one topic, nothing is dropped) and applies only what
passes. It then refreshes the taste profile (worker/taste.py) and its DESIGN.md
(worker/design_md.py). Runs weekly on GitHub Actions (.github/workflows/lint.yml).
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
from datetime import date

from . import design_md
from . import hypar
from . import pipeline as p
from . import run
from . import taste
from . import wiki

PLAN = """You are the librarian of a personal knowledge base of UI patterns,
product features and tools. An AI coding assistant finds things through its index,
so topics must be specific, not overlapping, and named after what they contain.
Categories:
__CATEGORIES__

You get every topic with its source notes. For each note: its path, title, summary
and the patterns it shows. Return ONLY JSON:

{"merge": [{"topics": ["category/slug", "..."],
            "into": {"category": "...", "slug": "...", "title": "...", "summary": "..."}}],
 "split": [{"topic": "category/slug",
            "into": [{"category": "...", "slug": "...", "title": "...", "summary": "...",
                      "sources": ["sources/..."]}]}],
 "move": [{"source": "sources/...", "to": "category/slug"}],
 "related": [["category/slug", "category/slug"]],
 "notes": ["short observations for the owner: contradictions, gaps, doubts"]}

Rules:
- Be conservative: leave empty lists when the wiki is fine. Every change rewrites
  pages, so only propose changes that make finding things clearly easier.
- merge: two or more topics about the same subject.
- split: only a topic with at least 4 sources that clearly covers different
  subjects, typically a catch-all ("micro-interactions", "ui-patterns"). Split into
  as few parts as possible, and every part must group at least 2 sources: a note
  often shows several patterns, so fragmenting into one-note topics makes things
  harder to find, not easier. Together the parts must list every source of the
  topic exactly once. A part may reuse the slug of the topic being split.
- move: a single note filed under the wrong topic. The target can be an existing
  topic or one created by your merge or split.
- related: pair topics a builder would want to read together while building ONE
  thing: alternatives for the same goal, patterns often combined in the same
  screen, a style and the patterns that use it. Never pair topics just because both
  involve AI, design or code. Both topics must be in the same category. Up to 3
  per topic, using the final topic names after your merges and splits; an empty
  list is fine.
- A topic is a subject many captures can share, named in kebab-case and specific
  ("expand-collapse-disclosure", "hover-reveals", "tab-transitions"). Titles are
  short Title Case; summaries are one line.
- Categories: design, features, tools or practices only. Topics that collect a
  visual look keep a slug starting with "style-".
""".replace("__CATEGORIES__", "\n".join(f"- {k}: {v}" for k, v in wiki.CATEGORIES.items()))


SPLIT = """You are the librarian of a personal knowledge base. One topic has grown
into a catch-all: it holds far more captures than the other topics of its
category, so an AI coding assistant can't tell from its name what is inside.
Split it into specific topics, each named after the one job or subject its
captures share ("browser-automation", "local-llm-runners", "agent-skills").

You get the topic, its source notes (path, title, summary and what each covers)
and the other topics of the category. Return ONLY JSON:

{"into": [{"category": "...", "slug": "...", "title": "...", "summary": "...",
           "sources": ["sources/..."]}]}

Rules:
- Every source of the topic appears in exactly one part. Copy the paths exactly.
- Each part groups at least 2 sources. Captures that fit no group stay together
  in one part that may reuse the topic's slug.
- Don't reuse the slug of another existing topic; the category stays the same.
- Slugs in kebab-case, titles short Title Case, summaries one line.
- If the captures really are about one subject, return {"into": []}.
"""


CATCH_ALL_MIN = 8
CATCH_ALL_RATIO = 2.5


def catch_alls(state: dict[str, dict]) -> list[str]:
    """Topics far larger than their category's typical topic: at least
    CATCH_ALL_MIN sources and CATCH_ALL_RATIO times the category's median. Visual
    styles are left alone: a look gathers many captures by nature."""
    by_cat: dict[str, list[int]] = {}
    for t in state.values():
        by_cat.setdefault(t["category"], []).append(len(t["sources"]))
    return sorted((k for k, t in state.items()
                   if not k.split("/")[1].startswith("style-")
                   and len(t["sources"]) >= max(CATCH_ALL_MIN, CATCH_ALL_RATIO * statistics.median(by_cat[t["category"]]))),
                  key=lambda k: -len(state[k]["sources"]))


def split_catch_alls(state: dict[str, dict]) -> list[dict]:
    """One focused split proposal per catch-all topic, in the plan's format, to be
    validated by apply_plan like any other."""
    splits = []
    for key in catch_alls(state):
        others = "\n".join(f"- {k}: {t['title']}" for k, t in sorted(state.items())
                            if k != key and t["category"] == state[key]["category"])
        prompt = f"{describe({key: state[key]})}\n\nOther topics in {state[key]['category']}:\n{others or '(none)'}"
        try:
            data = p.parse_json(p.chat(SPLIT, prompt, as_json=True, num_ctx=32768))
        except Exception as e:  # one topic's failure shouldn't stop the pass
            print(f"[lint] split of {key} not proposed: {e}", file=sys.stderr)
            continue
        parts = data.get("into") if isinstance(data, dict) else None
        if parts:
            splits.append({"topic": key, "into": parts})
    return splits


def snapshot() -> dict[str, dict]:
    """key → {title, summary, category, sources} for every topic page."""
    return {t["key"]: {"title": t["title"], "summary": t["summary"], "category": t["category"],
                       "sources": list(t["sources"]), "related": list(t["related"])}
            for t in wiki.topics()}


def describe(state: dict[str, dict]) -> str:
    blocks = []
    for key, t in sorted(state.items()):
        lines = [f"## {key}: {t['title']} — {t['summary']}"]
        if t["related"]:
            lines.append(f"related: {', '.join(t['related'])}")
        for rel in t["sources"]:
            meta, body = wiki.read_page(wiki.WIKI / rel)
            lines.append(f"- {rel}: {meta.get('title', '')} — {meta.get('summary', '')}"
                         + "".join(f" [{label}: {'; '.join(found)}]"
                                   for label, section in (("patterns", "What it shows"), ("ideas", "Key ideas"))
                                   if (found := headings(body, section))))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def headings(body: str, section: str) -> list[str]:
    """The "### " entries of one "## " section of a source note."""
    if f"## {section}" not in body:
        return []
    part = re.split(r"^## (?!#)", body.split(f"## {section}", 1)[1], maxsplit=1, flags=re.M)[0]
    return re.findall(r"^### (.+)$", part, re.M)


def key_of(spec: dict) -> str | None:
    category, slug = spec.get("category"), wiki.slugify(str(spec.get("slug") or spec.get("title") or ""))
    return f"{category}/{slug}" if category in wiki.CATEGORIES and slug != "untitled" else None


def apply_plan(state: dict[str, dict], plan: dict) -> tuple[dict[str, dict], list[str]]:
    """Validates each proposal against the current state and applies the ones that
    keep every source in exactly one topic. Returns the new state and a change log."""
    state = {k: {**v, "sources": list(v["sources"])} for k, v in state.items()}
    log = []

    def warn(msg):
        print(f"[lint] skipped: {msg}", file=sys.stderr)

    for m in plan.get("merge") or []:
        keys = [k for k in dict.fromkeys(m.get("topics") or []) if k in state]
        target = key_of(m.get("into") or {})
        if len(keys) < 2 or not target:
            warn(f"merge {m.get('topics')} → {m.get('into')}")
            continue
        sources = [s for k in keys for s in state[k]["sources"]]
        into = m["into"]
        base = state.get(target, {})
        for k in keys:
            state.pop(k)
        state[target] = {"title": into.get("title") or base.get("title") or target,
                         "summary": into.get("summary") or base.get("summary", ""),
                         "category": target.split("/")[0],
                         "sources": list(dict.fromkeys(base.get("sources", []) + sources)),
                         "related": base.get("related", [])}
        log.append(f"merged {', '.join(keys)} into {target}")

    for s in plan.get("split") or []:
        key, parts = s.get("topic"), s.get("into") or []
        if key not in state or len(parts) < 2 or len(state[key]["sources"]) < 4 \
                or any(len(part.get("sources") or []) < 2 for part in parts):
            warn(f"split {key}: needs a topic with 4+ sources and parts of 2+ sources each")
            continue
        listed = [src for part in parts for src in part.get("sources") or []]
        targets = [key_of(part) for part in parts]
        if (sorted(listed) != sorted(state[key]["sources"]) or None in targets
                or len(set(targets)) != len(targets) or any(not part.get("sources") for part in parts)
                or any(t in state and t != key for t in targets)):
            warn(f"split {key}: parts don't cover its sources exactly once, or clash with other topics")
            continue
        old = state.pop(key)
        for part, target in zip(parts, targets):
            state[target] = {"title": part.get("title") or target, "summary": part.get("summary", ""),
                             "category": target.split("/")[0], "sources": list(part["sources"]),
                             "related": old["related"] if target == key else []}
        log.append(f"split {key} into {', '.join(targets)}")

    for mv in plan.get("move") or []:
        rel, target = mv.get("source"), mv.get("to")
        current = next((k for k, t in state.items() if rel in t["sources"]), None)
        if not current or target not in state or target == current:
            warn(f"move {rel} → {target}")
            continue
        state[current]["sources"].remove(rel)
        state[target]["sources"].append(rel)
        log.append(f"moved {rel} from {current} to {target}")

    for key in [k for k, t in state.items() if not t["sources"]]:
        state.pop(key)
        log.append(f"removed empty topic {key}")

    pairs = plan.get("related")
    if pairs is not None:  # the plan states the full desired set of relations
        wanted = {k: set() for k in state}
        for pair in pairs:
            if isinstance(pair, list) and len(pair) == 2 and pair[0] != pair[1] and all(k in state for k in pair):
                wanted[pair[0]].add(pair[1])
                wanted[pair[1]].add(pair[0])
    else:
        wanted = {k: set(t.get("related") or []) for k, t in state.items()}
    for key, t in state.items():
        # Only within a category: across categories the model links topics that
        # merely share an area (an AI chat UI and a code sandbox tool), even when
        # asked about that single pair.
        new = sorted(k for k in wanted[key] if k in state and k.split("/")[0] == key.split("/")[0])[:5]
        if new != sorted(t.get("related") or []):
            log.append(f"related {key} → {', '.join(new) or 'none'}")
        t["related"] = new

    for t in state.values():
        t["sources"] = sorted(dict.fromkeys(t["sources"]), key=wiki.capture_number)
    return state, log


def write_state(before: dict[str, dict], after: dict[str, dict], recompose_all: bool) -> list[str]:
    """Writes pages, retargets moved notes and deletes topics that no longer exist.
    Returns the keys whose page was rewritten."""
    rewritten = []
    for key, t in after.items():
        path = wiki.WIKI / f"{key}.md"
        old = before.get(key)
        meta = {**(wiki.read_page(path)[0] if path.exists() else {}),
                "title": t["title"], "category": t["category"], "summary": t["summary"],
                "sources": t["sources"], "related": t["related"]}
        for rel in t["sources"]:
            if wiki.read_page(wiki.WIKI / rel)[0].get("topic") != key or not old or old["title"] != t["title"]:
                wiki.retarget_source(rel, key, t["title"])
        if recompose_all or not old or old["sources"] != t["sources"]:
            meta["updated"] = date.today().isoformat()
            wiki.write_topic(path, meta, wiki.compose(key, meta))
            rewritten.append(key)
        elif old.get("related") != t["related"] or old["summary"] != t["summary"] or old["title"] != t["title"]:
            wiki.write_topic(path, meta, wiki.read_page(path)[1])
    for key in before.keys() - after.keys():
        (wiki.WIKI / f"{key}.md").unlink(missing_ok=True)
    wiki.build_index()
    return rewritten


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the validated plan and change nothing")
    ap.add_argument("--recompose-all", action="store_true", help="rewrite every topic page from its sources")
    ap.add_argument("--no-plan", action="store_true", help="skip the reorganization, only rewrite pages")
    args = ap.parse_args()

    before = snapshot()
    plan = {}
    if not args.no_plan:
        plan = p.parse_json(p.chat(PLAN, describe(before), as_json=True, num_ctx=32768))
        if not isinstance(plan, dict):
            sys.exit(f"[lint] unexpected plan: {str(plan)[:200]}")
    after, log = apply_plan(before, plan)
    if not args.no_plan and (splits := split_catch_alls(after)):
        after, more = apply_plan(after, {"split": splits})
        log += more
    notes = [str(n) for n in plan.get("notes") or []]

    for line in log or ["no reorganization needed"]:
        print(f"[lint] {line}")
    for n in notes:
        print(f"[lint] note: {n}")
    if args.dry_run:
        return

    rewritten = write_state(before, after, args.recompose_all)
    print(f"[lint] rewrote {len(rewritten)} topic page(s): {', '.join(rewritten) or '-'}")
    try:
        refreshed = taste.build()
    except Exception as e:  # the profile is a bonus: never lose the lint pass over it
        print(f"[lint] taste profile not refreshed: {e}", file=sys.stderr)
        refreshed = False
    try:
        designed = design_md.build()
    except Exception as e:  # so is its DESIGN.md
        print(f"[lint] DESIGN.md not refreshed: {e}", file=sys.stderr)
        designed = False
    if refreshed or designed:
        wiki.build_index()
    if log or rewritten or refreshed or designed:
        run.commit_wiki("docs(wiki): lint pass",
                        "\n".join([*log, *(f"rewrote {k}" for k in rewritten), *(f"note: {n}" for n in notes),
                                    *(["refreshed taste profile"] if refreshed else []),
                                    *(["refreshed DESIGN.md"] if designed else [])]))
        hypar.sync_index(wiki.WIKI)


if __name__ == "__main__":
    main()
