"""Local inbox, the alternative to the Supabase one.

It processes nothing: it accepts URLs from the Shortcut and keeps them until the
worker claims them, so a phone capture is never lost because the laptop is
closed.

Deploy on any small server, or on localhost if the Mac is always on.
"""
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, HttpUrl

DB = os.environ.get("INBOX_DB", str(Path(__file__).resolve().parent.parent / "data" / "inbox.db"))
TOKEN = os.environ["INBOX_TOKEN"]

app = FastAPI(title="second-brain inbox")


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


@app.on_event("startup")
def init():
    Path(DB).parent.mkdir(parents=True, exist_ok=True)
    with closing(db()) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS inbox (
            id INTEGER PRIMARY KEY,
            url TEXT NOT NULL UNIQUE,
            note TEXT,
            claimed_at TEXT,
            created_at TEXT NOT NULL)""")
        c.commit()


def auth(header: str | None):
    if header != f"Bearer {TOKEN}":
        raise HTTPException(401, "unauthorized")


class Capture(BaseModel):
    url: HttpUrl
    note: str | None = None


@app.post("/capture", status_code=202)
def capture(body: Capture, authorization: str = Header(None)):
    """The Shortcut calls this. It answers in milliseconds: waiting for the model
    would leave the share sheet hanging and you'd stop using it."""
    auth(authorization)
    with closing(db()) as c:
        # Sharing the same URL again re-queues it with the new note (e.g.
        # "style: x" on something already captured); the worker won't re-analyze
        # what's already filed.
        c.execute(
            "INSERT INTO inbox (url, note, created_at) VALUES (?,?,?) "
            "ON CONFLICT(url) DO UPDATE SET note = excluded.note, claimed_at = NULL",
            (str(body.url), body.note, datetime.now(timezone.utc).isoformat()),
        )
        c.commit()
    return {"status": "queued"}


@app.get("/pending")
def pending(authorization: str = Header(None)):
    """The worker polls here."""
    auth(authorization)
    with closing(db()) as c:
        rows = c.execute(
            "SELECT id, url, note FROM inbox WHERE claimed_at IS NULL ORDER BY id LIMIT 20"
        ).fetchall()
    return [dict(r) for r in rows]


@app.post("/claim/{item_id}")
def claim(item_id: int, authorization: str = Header(None)):
    """Explicit confirmation after processing. If the worker dies halfway, the
    item stays pending and is retried on the next cycle."""
    auth(authorization)
    with closing(db()) as c:
        c.execute("UPDATE inbox SET claimed_at = ? WHERE id = ?",
                  (datetime.now(timezone.utc).isoformat(), item_id))
        c.commit()
    return {"status": "claimed"}
