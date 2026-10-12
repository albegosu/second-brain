#!/usr/bin/env python3
"""stack.md: the saved tools by the job they do, and which are worth depending on.

    python -m worker.stack                 # rewrite wiki/stack.md and commit it
    python -m worker.stack --dry-run       # print the map, change nothing
    python -m worker.stack --offline       # no GitHub calls: only the facts source notes recorded
    GITHUB_TOKEN=$(gh auth token) python -m worker.stack   # locally, past the 60 calls an hour without one

Each tools topic is a job and each "### Tool [n]" block of its page a tool.
Everything is decided by code, no model:

- Used: a capture behind the tool shaped a build (the usage log, worker/used.py).
- To try: saved, never used.
- Stale: its repository is archived, gone, or has had no commit for STALE_DAYS.

A tool's repository is the GitHub repository its Link points to, or, when a
source note describes that tool alone, the repository the note captured. The
facts are read from GitHub on every rewrite; when it can't be reached (offline,
a rate limit) the facts a source note recorded at capture time stand in, and if
GitHub refuses halfway through, the previous stack.md is kept: a partial
refresh would drop facts it had. Uses
are by capture, so a capture that names several tools counts for all of them.
The skill tells the agent to check this file before adding a dependency.
Refreshed after the weekly lint pass.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date

import httpx

from . import pipeline as p
from . import run
from . import used
from . import wiki

PATH = "stack.md"
STALE_DAYS = 365
URL = re.compile(r"https?://[^\s<>\"'`)\]]+")


def first_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    text = (m.group(1) if m else text).strip()
    return text if not text or text[-1] in ".!?" else text + "."


def tools() -> list[dict]:
    """Every tool block of the tools topics, with its job, captures, uses and
    repository (by name, plus the facts a source note recorded for it)."""
    uses = used.uses()
    out = []
    for t in wiki.topics():
        if t["category"] != "tools":
            continue
        meta, body = wiki.read_page(wiki.WIKI / f"{t['key']}.md")
        sources = meta.get("sources") or []
        found = wiki.blocks(body, "Options")
        cited_by = Counter(n for b in found for n in set(b["cites"]))
        for b in found:
            rels = {n: sources[n - 1] for n in b["cites"] if 1 <= n <= len(sources)}
            notes = {n: wiki.read_page(wiki.WIKI / rel)[0] for n, rel in rels.items() if (wiki.WIKI / rel).exists()}
            captures = sorted({int(m.get("capture") or wiki.capture_number(rels[n])) for n, m in notes.items()})
            if not captures:
                continue
            link = next(iter(URL.findall(b["fields"].get("link", ""))), None)
            # Where the tool was seen (a post) is not the tool.
            link = link.rstrip(".,;:!?*") if link and not wiki.POST_HOSTS.match(link) else None
            repo = p.github_name(link)
            if not repo:  # a note about this tool alone: the repository it captured
                repo = next((name for n, m in notes.items() if cited_by[n] == 1
                             and (name := (m.get("repo") or {}).get("name") or p.github_name(m.get("url")))), None)
            recorded = next((m["repo"] for m in notes.values() if repo and (m.get("repo") or {}).get("name") == repo),
                            None)
            out.append({"name": b["name"], "job": t, "what": first_sentence(b["fields"].get("what it does", "")),
                        "link": link, "captures": captures, "repo": repo, "recorded": recorded,
                        "uses": [u for u in uses if set(u["captures"]) & set(captures)]})
    return out


def facts(items: list[dict], online: bool = True) -> tuple[dict[str, dict], bool]:
    """Each repository's facts, read from GitHub now, and whether GitHub refused.
    A repository that is gone is marked so. After a refusal no more calls are
    made and the facts a source note recorded stand in."""
    out, refused = {}, False
    for name in sorted({i["repo"] for i in items if i["repo"]}):
        if online:
            try:
                out[name] = p.github_facts(name) or {"name": name, "gone": True, "checked": date.today().isoformat()}
                continue
            except (httpx.HTTPError, ValueError, KeyError) as e:  # a rate limit, no network: stop asking
                print(f"[stack] GitHub unreachable, using recorded facts: {e}", file=sys.stderr)
                online, refused = False, True
        if recorded := next((i["recorded"] for i in items if i["repo"] == name and i["recorded"]), None):
            out[name] = recorded
    return out, refused


def stale(f: dict | None, today: date) -> str | None:
    """Why a repository isn't worth depending on, or None."""
    if not f:
        return None
    if f.get("gone"):
        return "repository gone"
    if f.get("archived"):
        return "archived"
    last = f.get("last_commit")
    if last and (today - date.fromisoformat(last)).days > STALE_DAYS:
        return f"no commit since {last}"
    return None


def status(item: dict) -> str:
    if not item["uses"]:
        return "To try."
    last = item["uses"][-1]
    return f"Used {len(item['uses'])}×, last in {last['project']} on {last['date']}."


def repo_text(name: str, f: dict | None, today: date) -> str:
    if not f:
        return name
    if f.get("gone"):
        return f"{name}: gone"
    bits = [f.get("language"), f"{f['license']} license" if f.get("license") else "no license found",
            f"last commit {f['last_commit']}" if f.get("last_commit") else None,
            "archived" if f.get("archived") else None,
            f"checked {f['checked']}" if f.get("checked") and f["checked"] != today.isoformat() else None]
    return f"{name}: {', '.join(x for x in bits if x)}"


def line(item: dict, f: dict | None, today: date) -> str:
    why = stale(f, today)
    parts = [f"**{item['name']}**" + (f" — {item['what']}" if item["what"] else ""),
             f"Stale: {why}." if why else status(item)]
    if item["repo"]:
        parts.append(f"[{repo_text(item['repo'], f, today)}](https://github.com/{item['repo']})")
    elif item["link"]:
        parts.append(f"<{item['link']}>")
    return f"- {' '.join(parts)} ({', '.join(f'#{n}' for n in item['captures'])})"


def render(items: list[dict], found: dict[str, dict], today: date) -> str:
    lines = ["# Stack", "",
             "The tools you saved, by the job they do, written by code from the tools topics, the usage log and "
             "GitHub. Before adding a dependency, look for the job here: prefer a tool already used in a build, "
             "then one saved to try, and leave a stale one aside unless nothing else does the job. The project's "
             "own stack and the user's choice always win.", "",
             f"Repository facts as of {today.isoformat()}. Uses are by capture: a capture that names several "
             "tools counts for all of them.", ""]
    in_use = [i for i in items if i["uses"]]
    if in_use:
        lines += ["## Used in builds", ""]
        lines += [f"- **{i['name']}** ({i['job']['title']}): {status(i)} ({', '.join(f'#{n}' for n in i['captures'])})"
                  for i in sorted(in_use, key=lambda i: (-len(i["uses"]), i["name"].lower()))]
        lines.append("")
    jobs = {}
    for i in items:
        jobs.setdefault(i["job"]["key"], []).append(i)
    for key, mine in sorted(jobs.items(), key=lambda kv: kv[1][0]["job"]["title"].lower()):
        job = mine[0]["job"]
        lines += [f"## {job['title']}", "", f"[Topic page]({key}.md): {job['summary']}", ""]
        mine.sort(key=lambda i: (bool(stale(found.get(i["repo"]), today)), not i["uses"]))  # stable: page order
        lines += [line(i, found.get(i["repo"]), today) for i in mine]
        lines.append("")
    gone = [(i, why) for i in items if (why := stale(found.get(i["repo"]), today))]
    if gone:
        lines += ["## Stale", "", "Saved, but not worth a new dependency:", ""]
        lines += [f"- **{i['name']}** ({i['job']['title']}): {why}" for i, why in gone]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def generate(online: bool = True) -> tuple[str, bool] | None:
    """(the file's text, whether GitHub refused), or None when there are no tools."""
    items = tools()
    if not items:
        return None
    found, refused = facts(items, online)
    return render(items, found, date.today()), refused


def build(online: bool = True) -> bool:
    """Rewrites wiki/stack.md; removes it when there are no tools. Keeps the
    previous one when GitHub refused halfway. False when nothing was written."""
    made = generate(online)
    if not made:
        (wiki.WIKI / PATH).unlink(missing_ok=True)
        print("[stack] no tools topic with tools: no stack.md")
        return False
    text, refused = made
    if refused and (wiki.WIKI / PATH).exists():
        print("[stack] GitHub refused (a rate limit?): kept the previous stack.md. Locally, set GITHUB_TOKEN, "
              "for example GITHUB_TOKEN=$(gh auth token)", file=sys.stderr)
        return False
    (wiki.WIKI / PATH).write_text(text)
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the map, change nothing")
    ap.add_argument("--offline", action="store_true", help="no GitHub calls: only the facts source notes recorded")
    args = ap.parse_args()
    if args.dry_run:
        made = generate(not args.offline)
        sys.stdout.write(made[0] if made else "[stack] no tools yet\n")
        return
    build(not args.offline)
    wiki.build_index()
    run.commit_wiki("docs(wiki): refresh stack.md")


if __name__ == "__main__":
    main()
