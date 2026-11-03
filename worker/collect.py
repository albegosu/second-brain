#!/usr/bin/env python3
"""Collections: captures grouped by what you saved them for (a project, a client, a redesign).

    python -m worker.collect 7 21 checkout            # add captures #7 and #21 to the collection checkout
    python -m worker.collect 21 checkout --remove     # take #21 out of it

Topics are the model's organization, by what a capture shows; a collection is
yours, and no model can infer it. A capture joins one from its note when it's
filed ("collection: checkout", or "colección: checkout"), or later with this
command. Either way only the source note's frontmatter changes (`collections`):
no re-analysis, no model, and the capture stays in its topic. A capture can be
in several collections.

The index lists each collection with its captures, and
`python -m worker.design_md --collection <name>` writes the DESIGN.md of only
those captures.
"""
from __future__ import annotations

import argparse
import sys

from . import run
from . import wiki


def collect(captures: list[int], name: str, remove: bool = False) -> list[str]:
    """Adds the captures to the collection (or takes them out of it). Every
    capture is checked before any note changes. Returns one line per capture."""
    slug = wiki.slugify(name)
    known = {wiki.capture_number(f.name) for f in wiki.source_files()}
    missing = [n for n in captures if n not in known]
    if missing:
        raise SystemExit(f"no capture {', '.join(f'#{n}' for n in missing)} in {wiki.WIKI}")
    lines = []
    for n in dict.fromkeys(captures):
        now = wiki.join_collections(n, [slug], leave=remove)
        lines.append(f"#{n}: {', '.join(now) if now else 'in no collection'}")
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captures", nargs="+", type=int, help="capture numbers, as in the source note file names")
    ap.add_argument("name", help="the collection, in kebab-case (checkout, acme-web)")
    ap.add_argument("--remove", action="store_true", help="take the captures out of the collection")
    args = ap.parse_args()
    lines = collect(args.captures, args.name, args.remove)
    wiki.build_index()
    print("\n".join(lines))
    slug, numbers = wiki.slugify(args.name), ", ".join(f"#{n}" for n in dict.fromkeys(args.captures))
    try:
        run.commit_wiki(f"docs(wiki): {numbers} {'out of' if args.remove else 'into'} collection {slug}")
    except Exception as e:
        print(f"[collect] saved, not pushed: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
