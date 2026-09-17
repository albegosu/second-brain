"""Plants a capture's note as a latent embryo in hypar (github.com/albegosu/hypar).

Only when the capture was shared as "Idea to grow" and carries a note: the seed
is the user's own thought, never the model's summary of the post. The original
URL and a link to the source note travel beside it. Optional: without
HYPAR_URL and HYPAR_TOKEN nothing is sent.

What leaves the wiki: the note, the original URL and the source note's GitHub
URL (readable only by who can read the private wiki repository).
"""
import os
import re
import subprocess

import httpx

HYPAR_URL = os.environ.get("HYPAR_URL", "").rstrip("/")
HYPAR_TOKEN = os.environ.get("HYPAR_TOKEN", "")

INTENT = "idea to grow"

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


def plant(seed: str, url: str, source_ref: str | None) -> dict:
    """Returns {"id", "created"}; raises on any failure (the caller reports it)."""
    r = httpx.post(f"{HYPAR_URL}/api/integrations/embryos", timeout=30,
                   headers={"Authorization": f"Bearer {HYPAR_TOKEN}"},
                   json={"seed": seed, "sourceUrl": url, **({"sourceRef": source_ref} if source_ref else {})})
    r.raise_for_status()
    body = r.json()
    return {"id": body["embryo"]["id"], "created": body["created"]}


def embryo_url(embryo_id: str) -> str:
    return f"{HYPAR_URL}/embryo/{embryo_id}"
