#!/usr/bin/env python3
"""Usage log: which captures ended up shaping something that got built.

    python -m worker.used 7 21 --project acme-web --what "dot grid loader for the thinking state" \
        --ref https://github.com/acme/web/pull/42

An agent that builds from the wiki records it here (the second-brain skill tells
it how). Lines go to wiki/usage.md by capture number, which survives
re-analysis while titles and slugs don't. The index shows how often each topic
was used, so what proves useful stands out from what was only saved.

A use only rests on the agent's judgment, so `--ref` links the line to the commit
or pull request it shaped: anyone can open the diff and check the credit. The
index counts those uses apart, as verifiable.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date

from . import run
from . import wiki

PATH = "usage.md"
HEADER = ["# Usage", "",
          "Written by `python -m worker.used`: what was built from which captures. One line per use,",
          "captures by number (#n), newest last, linked to the commit or pull request when there is one.", ""]
LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · \*\*(.+?)\*\* · ((?:#\d+(?:, )?)+) · (.*?)"
                  r"(?: · \[[^\]]+\]\((https?://[^\s)]+)\))?$")
REF = re.compile(r"https?://[^\s)\]]+")


def sources_by_number() -> dict[int, tuple[str, dict]]:
    out = {}
    for f in wiki.source_files():
        meta, _ = wiki.read_page(f)
        out[int(meta.get("capture") or wiki.capture_number(f.name))] = (f.relative_to(wiki.WIKI).as_posix(), meta)
    return out


def uses() -> list[dict]:
    path = wiki.WIKI / PATH
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if m := LINE.match(line):
            out.append({"date": m.group(1), "project": m.group(2),
                        "captures": [int(n) for n in re.findall(r"#(\d+)", m.group(3))], "what": m.group(4),
                        "ref": m.group(5)})
    return out


def topic_uses(verifiable: bool = False) -> Counter:
    """Uses per topic key, resolving capture numbers to where they are filed now.
    verifiable: only the uses linked to a commit or pull request."""
    known = sources_by_number()
    counts = Counter()
    for use in uses():
        if verifiable and not use["ref"]:
            continue
        counts.update({known[n][1].get("topic") for n in use["captures"] if n in known} - {None})
    return counts


def ref_label(url: str) -> str:
    """owner/repo#42 for a pull or merge request, owner/repo@abc1234 for a commit
    (GitHub and GitLab URLs), else the URL without its scheme."""
    if m := re.match(r"https?://[^/]+/(.+?)/(?:-/)?(?:pull|merge_requests)/(\d+)", url):
        return f"{m.group(1)}#{m.group(2)}"
    if m := re.match(r"https?://[^/]+/(.+?)/(?:-/)?commits?/([0-9a-f]{7,40})\b", url):
        return f"{m.group(1)}@{m.group(2)[:7]}"
    return url.split("://", 1)[1]


def record(captures: list[int], project: str, what: str, ref: str | None = None) -> str:
    known = sources_by_number()
    missing = [n for n in captures if n not in known]
    if missing:
        raise SystemExit(f"no capture {', '.join(f'#{n}' for n in missing)} in {wiki.WIKI}")
    if ref is not None and not REF.fullmatch(ref):
        raise SystemExit(f"--ref takes the URL of the commit or pull request, not {ref!r}")
    clean = lambda s: re.sub(r"\s+", " ", s.replace("·", "-").replace("**", "")).strip()
    line = f"- {date.today().isoformat()} · **{clean(project)}** · {', '.join(f'#{n}' for n in captures)} · {clean(what)}"
    if ref:
        line += f" · [{ref_label(ref)}]({ref})"
    path = wiki.WIKI / PATH
    text = path.read_text().rstrip("\n") + "\n" if path.exists() else "\n".join(HEADER) + "\n"
    path.write_text(text + line + "\n")
    return line


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="+", type=int, help="capture numbers, as in the source note file names")
    ap.add_argument("--project", required=True, help="what was being built (repository or product name)")
    ap.add_argument("--what", required=True, help="what was taken from them, in one line")
    ap.add_argument("--ref", help="URL of the commit or pull request the work landed in, so the use can be checked")
    args = ap.parse_args()
    line = record(args.captures, args.project, args.what, args.ref)
    wiki.build_index()
    print(line)
    try:
        run.commit_wiki(f"docs(wiki): used in {args.project}", line[2:])
    except Exception as e:
        print(f"[used] recorded, not pushed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
