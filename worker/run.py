#!/usr/bin/env python3
"""Worker: processes the pending inbox and files each capture into the wiki.

Runs on GitHub Actions (Supabase triggers it when a capture arrives) or on any
machine that can reach Ollama:

    python -m worker.run --once                  # process what's pending and exit
    python -m worker.run                         # keep polling
    python -m worker.run --url URL [--note N]    # direct ingestion, no inbox
    python -m worker.run --url URL --reanalyze   # run the model again
    python -m worker.run --reanalyze             # the whole wiki (after changing prompts)

It keeps no state of its own: a capture is filed if a source note with its URL
exists in wiki/sources, and the next capture number comes from the existing notes.
"style: name" (or "estilo: name") in the note files it under design/style-<name>.
Shared as "Idea to grow", the note is also planted as an embryo in hypar.
"""
import argparse
import os
import re
import subprocess
import sys
import time
from datetime import date

import httpx

from . import hypar
from . import pipeline as p
from . import wiki

INBOX = os.environ.get("INBOX_URL", "http://localhost:8000")
TOKEN = os.environ.get("INBOX_TOKEN", "")
INTERVAL = int(os.environ.get("POLL_INTERVAL", "60"))

# Phone push when each Shortcut capture is done (ntfy app subscribed to the
# topic). The topic is the only protection: make it long and random.
NTFY_URL = os.environ.get("NTFY_URL", "https://ntfy.sh")
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# Supabase inbox, when configured: the Shortcut calls capture() and the worker
# pending()/retry()/claim(). Each function checks its token against a hash stored
# in the database. The publishable key is public by design.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN", "")

# Automatic commit and push of the wiki after each capture.
GIT_SYNC = os.environ.get("BRAIN_GIT_SYNC") == "1"

# A transient failure leaves the item pending; past this many attempts it's given up.
MAX_ATTEMPTS = 5

STYLE_TAG = re.compile(r"\b(?:style|estilo):\s*([a-z0-9][a-z0-9-]*)", re.I)
INTENT_TAG = re.compile(r"\bintent:\s*(pattern to reuse|visual style|tool to try|idea to read|idea to grow|just save)[\s—–:-]*", re.I)
# Below this many words, with no image, video or note, there's nothing to file:
# the model would have to make the capture up.
MIN_WORDS = 25
# Text past this many words (an article, a long thread) also gets its ideas extracted.
IDEA_WORDS = 150
TRANSIENT = re.compile(r"\b(408|425|429|50[0-4])\b|timed? ?out|No route to host|"
                       r"Connection (reset|refused|aborted)|Temporary failure|Name or service not known",
                       re.I)


def parse_note(note: str | None) -> tuple[str | None, str | None, str | None]:
    """What a note says besides free text: "style: name" picks the topic and
    "intent: …" (the Shortcut's menu) hints the category. The rest goes to the
    model as the user's note."""
    style = intent = None
    rest = note or ""
    if m := STYLE_TAG.search(rest):
        style, rest = m.group(1).lower(), rest[:m.start()] + rest[m.end():]
    if m := INTENT_TAG.search(rest):
        intent, rest = m.group(1).lower(), rest[:m.start()] + rest[m.end():]
    return style, intent, rest.strip(" \n,;.—–-") or None


def is_transient(e: Exception) -> bool:
    """Network down, Ollama overloaded or a rate limit: worth retrying. A page
    that doesn't exist or a post with nothing to analyze is not."""
    if isinstance(e, httpx.TransportError):
        return True
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in (408, 425, 429) or e.response.status_code >= 500
    return bool(TRANSIENT.search(str(e)))


def ingest(url: str, note: str | None = None, reanalyze: bool = False) -> dict:
    """Returns {"text": log line} plus "entry" (what was filed), "already" or
    "error" (with "transient" when a retry makes sense)."""
    url = p.canonical_url(url)
    source = p.detect_source(url)

    existing = wiki.find_source(url)
    if existing and note is None:
        note = existing[1].get("note")  # re-analysis without --note keeps the note
    style, intent, vlm_note = parse_note(note)

    # Already filed: nothing to do, unless the note carries a style.
    if existing and not reanalyze and not style:
        return {"text": f"already filed: #{existing[0]}", "already": True}

    cid = existing[0] if existing else wiki.next_capture_id()
    captured = str(existing[1].get("captured")) if existing else date.today().isoformat()
    try:
        media = p.fetch_media(url, source, cid)
        if media["kind"] == "video":
            frames = p.keyframes(media["path"], cid)
        else:
            frames = [media["path"], *media.get("extra", [])] if media["kind"] == "image" else []
        words = p.readable_words(media)
        if not frames and not vlm_note and words < MIN_WORDS:
            raise RuntimeError("Nothing to read: share it again with a note")
        analysis = p.analyze(frames, vlm_note, media.get("text")) if frames else {}
        patterns = p.clean_patterns(analysis.get("patterns") or [])
        look = p.clean_style(analysis.get("style"), frames) if frames else None
        key_ideas = []
        if media.get("article") or (not patterns and words >= IDEA_WORDS):
            text = "\n\n".join(x for x in (media.get("text"), (media.get("page") or {}).get("excerpt")) if x)
            key_ideas = p.ideas(text, vlm_note)
        entry = wiki.file_capture(cid=cid, captured=captured, url=url, source=source, media=media,
                                  note=note, patterns=patterns, style=look, style_name=style,
                                  ideas=key_ideas, intent=intent, frames=frames)
    except Exception as e:
        transient = is_transient(e)
        return {"text": f"#{cid} {'will retry' if transient else 'failed'}: {e}",
                "error": str(e), "transient": transient}

    try:
        commit_wiki(f"docs(wiki): add {entry['title']}",
                    f"Capture #{cid} filed under {entry['category']}/{entry['topic']}.\n{url}")
    except Exception as e:
        if os.environ.get("GITHUB_ACTIONS") == "true":  # not on GitHub means not filed: retry it
            return {"text": f"#{cid} will retry: {e}", "error": str(e), "transient": True}
        # On a computer the capture stays in the local wiki and goes out with the next push.
        print(f"[worker] wiki commit failed: {e} {getattr(e, 'stderr', '') or ''}", file=sys.stderr)
    result = {"text": f"#{cid}: {entry['category']}/{entry['topic']} · {entry['title']}", "entry": entry}
    if intent == hypar.INTENT and not reanalyze:
        result.update(grow(url, vlm_note, entry))
        result["text"] += (f" · planted in hypar ({result['embryo']['id']})" if "embryo" in result
                           else f" · not planted in hypar: {result['hypar_error']}")
    return result


def grow(url: str, note: str | None, entry: dict) -> dict:
    """Plants the note in hypar. The capture is already filed, so a failure here
    is reported, not retried: share it again once hypar is back and it's planted
    (hypar ignores a URL it already has)."""
    if not hypar.enabled():
        return {"hypar_error": "HYPAR_URL and HYPAR_TOKEN aren't set"}
    if not note:
        return {"hypar_error": "no note: the seed has to be your own thought"}
    try:
        return {"embryo": hypar.plant(note, url, hypar.source_link(wiki.WIKI, entry["source"]))}
    except Exception as e:
        print(f"[worker] hypar unreachable: {e}", file=sys.stderr)
        return {"hypar_error": str(e)[:200]}


def commit_wiki(subject: str, body: str = ""):
    """Commit and push the wiki folder (after a capture or a lint pass) in the git
    repository that holds it, usually the private wiki repository. Only that
    folder, unsigned: the worker runs without a terminal to ask for the GPG
    passphrase. If the push clashes with something pushed earlier, rebase and
    retry; if it still fails (no network), the commit goes out with the next one.
    A wiki outside any repository (a test copy) is left alone."""
    if not GIT_SYNC:
        return
    git = ["git", "-C", str(wiki.WIKI), "-c", "commit.gpgsign=false"]
    if subprocess.run([*git, "rev-parse", "--show-toplevel"], capture_output=True).returncode:
        return
    subprocess.run([*git, "add", "-A", "--", "."], check=True, capture_output=True, text=True)
    if subprocess.run([*git, "diff", "--cached", "--quiet", "--", "."]).returncode == 0:
        return  # nothing new to commit
    subprocess.run(
        [*git, "commit", "-q", "-m", subject, *(["-m", body] if body else []), "--", "."],
        check=True, capture_output=True, text=True,
    )
    push = subprocess.run([*git, "push", "-q"], capture_output=True, text=True, timeout=120)
    if push.returncode:
        rebase = subprocess.run([*git, "pull", "--rebase", "--autostash", "-q"], capture_output=True, text=True, timeout=120)
        if rebase.returncode:  # a conflict (index.md, a reused capture number) leaves a detached, half-done rebase
            subprocess.run([*git, "rebase", "--abort"], capture_output=True, text=True)
        push = subprocess.run([*git, "push", "-q"], capture_output=True, text=True, timeout=120)
    if push.returncode:
        reason = push.stderr.strip()[:200]
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # The runner is thrown away and an unpushed capture with it. Go back to
            # what's on GitHub and fail, so the item stays pending and is filed again.
            branch = subprocess.run([*git, "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True).stdout.strip()
            subprocess.run([*git, "fetch", "-q", "origin", branch], capture_output=True, text=True, timeout=120)
            subprocess.run([*git, "reset", "-q", "--hard", f"origin/{branch}"], capture_output=True, text=True)
            raise RuntimeError(f"push rejected, filed again on the next run: {reason}")
        print(f"[worker] push pending: {reason}", file=sys.stderr)


def notify(url: str, result: dict):
    """Reports the result through ntfy. It goes to an external service: the title
    and summary of what was filed and the post URL, nothing else."""
    if not NTFY_TOPIC:
        return
    if entry := result.get("entry"):
        title = f"Saved to {entry['category']}/{entry['topic']}"
        if entry["new_topic"]:
            title += " (new topic)"
        message, tags = f"{entry['title']}\n{entry['summary']}".strip(), ["white_check_mark"]
        if embryo := result.get("embryo"):
            message += "\nPlanted in hypar as a latent embryo"
            url = hypar.embryo_url(embryo["id"])
        elif "hypar_error" in result:
            message += f"\nNot planted in hypar: {result['hypar_error']}"
    elif result.get("already"):
        title, message, tags = "Already saved", url, ["information_source"]
    else:
        title, message, tags = "Capture failed", result.get("error") or result["text"], ["warning"]

    try:
        httpx.post(NTFY_URL, timeout=10, json={
            "topic": NTFY_TOPIC, "title": title, "message": message or url,
            "tags": tags, "click": url,
        })
    except Exception as e:
        print(f"[worker] ntfy unreachable: {e}", file=sys.stderr)


def inbox(action: str, item_id: int | None = None, reason: str | None = None):
    """pending, retry or claim, against Supabase or the local inbox."""
    if SUPABASE_URL:
        params = {"token": WORKER_TOKEN}
        if item_id is not None:
            params["item_id"] = item_id
        if reason:
            params["reason"] = reason[:500]
        r = httpx.post(f"{SUPABASE_URL}/rest/v1/rpc/{action}", json=params, timeout=30,
                       headers={"apikey": SUPABASE_KEY})
    elif action == "pending":
        r = httpx.get(f"{INBOX}/pending", headers={"Authorization": f"Bearer {TOKEN}"}, timeout=30)
    elif action == "claim":
        r = httpx.post(f"{INBOX}/claim/{item_id}", headers={"Authorization": f"Bearer {TOKEN}"},
                       timeout=30)
    else:
        return None  # the local inbox doesn't count attempts: anything unclaimed comes back next pass
    r.raise_for_status()
    return r.json()


def poll_once() -> int:
    try:
        items = inbox("pending")
    except Exception as e:
        print(f"[worker] inbox unreachable: {e}", file=sys.stderr)
        return 0

    for item in items:
        url = p.canonical_url(item["url"])
        print(f"[worker] {url}")
        result = ingest(url, item.get("note"))
        print(f"         {result['text']}")
        try:
            if result.get("transient") and int(item.get("attempts") or 0) + 1 < MAX_ATTEMPTS:
                inbox("retry", item["id"], result["error"])  # no notification: it'll be tried again
                continue
            notify(url, result)
            # Claim only after processing: if the worker dies halfway, the item
            # stays pending and comes back on the next pass.
            inbox("claim", item["id"], result.get("error"))
        except Exception as e:
            print(f"[worker] couldn't update #{item['id']} in the inbox: {e}", file=sys.stderr)

    return len(items)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--note")
    ap.add_argument("--reanalyze", action="store_true",
                    help="analyze again even if already filed (without --url: every note the current "
                         "pipeline hasn't analyzed yet, so an interrupted run resumes)")
    args = ap.parse_args()

    if args.url:
        print(ingest(args.url, args.note, reanalyze=args.reanalyze)["text"])
        return

    if args.reanalyze:
        for f in wiki.source_files():
            if not f.exists():  # renamed by an earlier re-analysis in this run
                continue
            meta = wiki.read_page(f)[0]
            if int(meta.get("analyzed") or 1) >= wiki.ANALYZED:
                continue
            result = ingest(meta["url"], meta.get("note"), reanalyze=True)
            print(f"[worker] {meta['url']}\n         {result['text']}")
            if result.get("transient"):
                print("[worker] stopped on a transient error (quota or network): run it again to resume")
                return
        return

    if args.once:
        print(f"[worker] {poll_once()} item(s)")
        return

    print(f"[worker] polling {SUPABASE_URL or INBOX} every {INTERVAL}s")
    while True:
        poll_once()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
