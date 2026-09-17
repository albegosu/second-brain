#!/usr/bin/env python3
"""Usage log: which captures ended up shaping something that got built.

    python -m worker.used 7 21 --project acme-web --what "dot grid loader for the thinking state"

An agent that builds from the wiki records it here (the second-brain skill tells
it how). Lines go to wiki/usage.md by capture number, which survives
re-analysis while titles and slugs don't. The index shows how often each topic
was used, so what proves useful stands out from what was only saved.
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
          "captures by number (#n), newest last.", ""]
LINE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · \*\*(.+?)\*\* · ((?:#\d+(?:, )?)+) · (.*)$")


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
                        "captures": [int(n) for n in re.findall(r"#(\d+)", m.group(3))], "what": m.group(4)})
    return out


def topic_uses() -> Counter:
    """Uses per topic key, resolving capture numbers to where they are filed now."""
    known = sources_by_number()
    counts = Counter()
    for use in uses():
        counts.update({known[n][1].get("topic") for n in use["captures"] if n in known} - {None})
    return counts


def record(captures: list[int], project: str, what: str) -> str:
    known = sources_by_number()
    missing = [n for n in captures if n not in known]
    if missing:
        raise SystemExit(f"no capture {', '.join(f'#{n}' for n in missing)} in {wiki.WIKI}")
    clean = lambda s: re.sub(r"\s+", " ", s.replace("·", "-").replace("**", "")).strip()
    line = f"- {date.today().isoformat()} · **{clean(project)}** · {', '.join(f'#{n}' for n in captures)} · {clean(what)}"
    path = wiki.WIKI / PATH
    text = path.read_text().rstrip("\n") + "\n" if path.exists() else "\n".join(HEADER) + "\n"
    path.write_text(text + line + "\n")
    return line


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="+", type=int, help="capture numbers, as in the source note file names")
    ap.add_argument("--project", required=True, help="what was being built (repository or product name)")
    ap.add_argument("--what", required=True, help="what was taken from them, in one line")
    args = ap.parse_args()
    line = record(args.captures, args.project, args.what)
    wiki.build_index()
    print(line)
    try:
        run.commit_wiki(f"docs(wiki): used in {args.project}", line[2:])
    except Exception as e:
        print(f"[used] recorded, not pushed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
