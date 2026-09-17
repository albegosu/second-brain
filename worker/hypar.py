"""Connects the wiki to hypar (github.com/albegosu/hypar). Optional: without
HYPAR_URL and HYPAR_TOKEN nothing is sent.

- A capture shared as "Idea to grow" with a note is planted as a latent embryo.
  The seed is the user's own thought, never the model's summary of the post.
  Beside it travel what sparked it: the original URL, the source note's GitHub
  URL (readable only by who can read the private wiki repository), and the
  capture's essence (title, summary, what it shows, key ideas, visual style).
- After each capture and lint pass, the index is sent so hypar keeps the latest
  one (topic and item names with their summaries).

Quoted post and page text never leave the wiki.
"""
import os
import re
import subprocess
import sys
from pathlib import Path

import httpx

HYPAR_URL = os.environ.get("HYPAR_URL", "").rstrip("/")
HYPAR_TOKEN = os.environ.get("HYPAR_TOKEN", "")

INTENT = "idea to grow"

# Source note sections that describe the capture in the model's own words. "Post
# text" and "Page" quote third parties, and "Note" is already the seed.
ESSENCE_SECTIONS = ("What it shows", "Key ideas", "Visual style")
MAX_ESSENCE = 12_000

GITHUB_REMOTE = re.compile(r"(?:https://(?:[^@/]+@)?github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?/?$")


def enabled() -> bool:
    return bool(HYPAR_URL and HYPAR_TOKEN)


def source_link(wiki: os.PathLike, rel: str) -> str | None:
    """The source note on GitHub, from the wiki repository's origin remote."""
    try:
        git = ["git", "-C", os.fspath(wiki)]
        top = subprocess.run([*git, "rev-parse", "--show-toplevel"], capture_output=True, text=True,
                             check=True).stdout.strip()
        remote = subprocess.run([*git, "remote", "get-url", "origin"], capture_output=True, text=True,
                                check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    m = GITHUB_REMOTE.match(remote)
    if not m:
        return None
    path = os.path.relpath(os.path.join(os.fspath(wiki), rel), top)
    return f"https://github.com/{m.group(1)}/blob/HEAD/{path}"


def essence(summary: str, body: str) -> str:
    """The capture as the wiki describes it: its summary plus the descriptive
    sections of the source note, as Markdown."""
    parts = [summary.strip()] if summary.strip() else []
    for section in re.split(r"^(?=## )", body, flags=re.M):
        heading = section.splitlines()[0][3:].strip() if section.startswith("## ") else ""
        if heading in ESSENCE_SECTIONS:
            parts.append(section.strip())
    text = "\n\n".join(parts)
    return text if len(text) <= MAX_ESSENCE else text[:MAX_ESSENCE].rsplit("\n", 1)[0] + "\n…"


def plant(seed: str, url: str, source_ref: str | None, title: str | None = None, context: str | None = None) -> dict:
    """Returns {"id", "created"}; raises on any failure (the caller reports it)."""
    extra = {k: v for k, v in {"sourceRef": source_ref, "sourceTitle": title, "sourceContext": context}.items() if v}
    r = httpx.post(f"{HYPAR_URL}/api/integrations/embryos", timeout=30,
                   headers={"Authorization": f"Bearer {HYPAR_TOKEN}"},
                   json={"seed": seed, "sourceUrl": url, **extra})
    r.raise_for_status()
    body = r.json()
    return {"id": body["embryo"]["id"], "created": body["created"]}


def push_index(wiki: os.PathLike) -> dict:
    """Sends index.md with the wiki's current commit. Raises on any failure."""
    markdown = (Path(wiki) / "index.md").read_text()
    try:
        commit = subprocess.run(["git", "-C", os.fspath(wiki), "rev-parse", "HEAD"], capture_output=True,
                                text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        commit = ""
    r = httpx.put(f"{HYPAR_URL}/api/integrations/references", timeout=30,
                  headers={"Authorization": f"Bearer {HYPAR_TOKEN}"},
                  json={"markdown": markdown, **({"commit": commit} if commit else {})})
    r.raise_for_status()
    return r.json()


def sync_index(wiki: os.PathLike) -> None:
    """push_index when hypar is configured; a failure is only logged, it never
    costs a capture or a lint pass."""
    if not enabled():
        return
    try:
        sent = push_index(wiki)
        print(f"[hypar] index sent: {sent.get('topics')} topics")
    except Exception as e:
        print(f"[hypar] index not sent: {e}", file=sys.stderr)


def embryo_url(embryo_id: str) -> str:
    return f"{HYPAR_URL}/embryo/{embryo_id}"
