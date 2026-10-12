#!/usr/bin/env python3
"""Lint pass: keeps the wiki organized as it grows.

    python -m worker.lint                  # plan, apply, rewrite changed topics, rebuild the index
    python -m worker.lint --dry-run        # only print the validated plan
    python -m worker.lint --recompose-all  # also rewrite every topic page from its sources

The model proposes merging duplicate topics, splitting catch-all topics, moving
misfiled captures and relating topics. The code validates the plan (every source
note ends up in exactly one topic, nothing is dropped) and applies only what
passes. Then the code itself picks the topics grown too large for their category
and asks the model to group each one's notes into specific topics (SPLIT): in the
whole-wiki plan the model never proposed splitting them. It then refreshes the
taste profile (worker/taste.py) and its DESIGN.md (worker/design_md.py). Runs
weekly on GitHub Actions (.github/workflows/lint.yml).
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date

from . import design_md
from . import hypar
from . import pipeline as p
from . import run
from . import taste
from . import wiki

PLAN = """You are the librarian of a personal knowledge base of UI patterns,
product features, tools and practices. An AI coding assistant finds things
through its index, so topics must be specific, not overlapping, and named after
what they contain.
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

# A topic is a catch-all candidate from CATCH_ALL sources when it also holds
# CATCH_ALL_SHARE of its category, or from CATCH_ALL_ALWAYS sources whatever the
# share. A style topic grows by collecting one look, and design has many topics,
# so the share keeps it out until it's really large.
CATCH_ALL = 8
CATCH_ALL_SHARE = 0.25
CATCH_ALL_ALWAYS = 15
# A part named like this is a new catch-all: its notes stay where they were.
VAGUE = re.compile(r"(?:^|-)(?:misc|miscellaneous|other|others|general|generic|various|assorted|stuff)(?:-|$)")

SPLIT = """You reorganize one topic of a personal knowledge base that has grown into a
catch-all. An AI coding assistant finds things through the index, so a topic must
be one subject a builder would look for, named after what it holds.

You get the topic, the other topics of its category and the topic's numbered
source notes: title, summary, tags and what each one shows. Return ONLY JSON:

{"parts": [{"slug": "kebab-case", "title": "Short Title Case", "summary": "one line",
            "sources": [1, 4, 7]}]}

Rules:
- Group the notes by the job they do or the subject they cover
  ("screen-recorders", "terminal-coding-agents", "agent-code-review"), never by
  vendor, date, format or popularity.
- Each new part holds at least 2 notes. A part may instead join one of the other
  topics listed, using its slug; then one note is enough.
- Every note number goes in exactly one part.
- As few parts as make each one specific, usually 2 to 6. Keep the topic's own
  slug only for a part its name still describes precisely.
- Never a new catch-all: no "misc", "other", "general", "resources", "ai-tools".
- If the notes really are one subject, return {"parts": []}.
- Write in English.
"""


def snapshot() -> dict[str, dict]:
    """key → {title, summary, category, sources} for every topic page."""
    return {t["key"]: {"title": t["title"], "summary": t["summary"], "category": t["category"],
                       "sources": list(t["sources"]), "related": list(t["related"])}
            for t in wiki.topics()}


def note_line(rel: str, tags: bool = False) -> str:
    """A source note in one line: title, summary and the patterns or ideas it shows."""
    meta, body = wiki.read_page(wiki.WIKI / rel)
    body = wiki.without_code(body)
    shown = [head for section in ("What it shows", "Key ideas") if f"## {section}\n" in body
             for head in re.findall(r"^### (.+)$", body.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0], re.M)]
    return (f"{meta.get('title', '')} — {meta.get('summary', '')}"
            + (f" [tags: {', '.join(meta.get('tags') or [])}]" if tags and meta.get("tags") else "")
            + (f" [patterns: {'; '.join(shown)}]" if shown else ""))


def describe(state: dict[str, dict]) -> str:
    blocks = []
    for key, t in sorted(state.items()):
        lines = [f"## {key}: {t['title']} — {t['summary']}"]
        if t["related"]:
            lines.append(f"related: {', '.join(t['related'])}")
        lines += [f"- {rel}: {note_line(rel)}" for rel in t["sources"]]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


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


def catch_alls(state: dict[str, dict]) -> list[str]:
    """Topics holding so much of their category that they're probably a
    catch-all. Decided by counting, not by the model."""
    per_category = Counter()
    for t in state.values():
        per_category[t["category"]] += len(t["sources"])
    return sorted(key for key, t in state.items()
                  if (n := len(t["sources"])) >= CATCH_ALL
                  and (n >= CATCH_ALL_ALWAYS or n >= CATCH_ALL_SHARE * per_category[t["category"]]))


def describe_topic(key: str, state: dict[str, dict]) -> str:
    """The split prompt's input: the topic, its category's other topics and its
    notes numbered, so the model answers with numbers instead of paths."""
    t = state[key]
    others = [f"- {k}: {o['title']} — {o['summary']}" for k, o in sorted(state.items())
              if o["category"] == t["category"] and k != key]
    return "\n".join([f"Topic: {key}: {t['title']} — {t['summary']}", "",
                      "Other topics in this category, which a part may join:", *(others or ["(none)"]), "",
                      "Source notes:", *(f"[{i}] {note_line(rel, tags=True)}" for i, rel in enumerate(t["sources"], 1))])


def apply_split(state: dict[str, dict], key: str, answer) -> tuple[dict[str, dict], list[str]]:
    """Applies the model's grouping of a catch-all's notes, within its category.
    The code keeps it safe: a note listed twice stays in its first part, a new
    part with a single note or a vague name ("misc-…") gives its notes back,
    every note no part takes stays in the topic, and nothing changes unless the
    notes end up in two topics or more."""
    old, category = state[key], state[key]["category"]
    numbered = list(old["sources"])
    taken, groups = set(), {}  # target key → {"spec", "sources"}
    for part in (answer.get("parts") if isinstance(answer, dict) else None) or []:
        if not isinstance(part, dict):
            continue
        # "tools/screen-recorders": the model sometimes repeats the category.
        slug = wiki.slugify(str(part.get("slug") or part.get("title") or "").rsplit("/", 1)[-1])
        numbers = [int(d) for n in part.get("sources") or [] if (d := re.sub(r"\D", "", str(n)))]
        mine = list(dict.fromkeys(numbered[n - 1] for n in numbers
                                  if 1 <= n <= len(numbered) and numbered[n - 1] not in taken))
        target = f"{category}/{slug}"
        joins = target in state and target != key
        if slug == "untitled" or len(mine) < (1 if joins else 2) or (VAGUE.search(slug) and not joins):
            continue
        taken.update(mine)
        groups.setdefault(target, {"spec": part, "sources": []})["sources"] += mine
    kept = groups.pop(key, None)
    rest = [s for s in numbered if s not in taken] + (kept["sources"] if kept else [])
    if len(groups) + bool(rest) < 2:
        return state, []

    joined = [k for k in groups if k in state]
    state = {k: {**t, "sources": list(t["sources"]), "related": list(t.get("related") or [])}
             for k, t in state.items()}
    if rest:
        spec = kept["spec"] if kept else {}
        state[key].update(title=spec.get("title") or old["title"], summary=spec.get("summary") or old["summary"],
                          sources=rest)
    else:
        state.pop(key)
    for target, g in groups.items():
        if target in state:
            state[target]["sources"] += g["sources"]
        else:
            state[target] = {"title": str(g["spec"].get("title") or target.split("/")[1].replace("-", " ").title()),
                             "summary": str(g["spec"].get("summary") or ""), "category": category,
                             "sources": g["sources"], "related": []}
    for t in state.values():
        t["sources"] = sorted(dict.fromkeys(t["sources"]), key=wiki.capture_number)
        t["related"] = [k for k in t["related"] if k in state]
    parts = ([key] if rest else []) + [k for k in groups if k not in joined]
    return state, [f"split {key} into {', '.join(parts) or '-'}"
                   + (f", moving notes to {', '.join(joined)}" if joined else "")]


def split_catch_alls(state: dict[str, dict]) -> tuple[dict[str, dict], list[str]]:
    """One model call per catch-all, each with only that topic's notes."""
    log = []
    for key in catch_alls(state):
        try:
            answer = p.parse_json(p.chat(SPLIT, describe_topic(key, state), as_json=True))
        except Exception as e:  # one topic's bad answer never costs the lint pass
            print(f"[lint] skipped: split {key}: {e}", file=sys.stderr)
            continue
        state, done = apply_split(state, key, answer)
        if not done:
            print(f"[lint] kept whole: {key} ({len(state[key]['sources'])} sources)", file=sys.stderr)
        log += done
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
    if not args.no_plan:
        after, split = split_catch_alls(after)
        log += split
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
