from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def database_path() -> Path:
    return Path(os.getenv("DATABASE_PATH", "./data/energytool.sqlite3"))


@contextmanager
def connection():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            closed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
            content TEXT NOT NULL,
            sources_json TEXT NOT NULL DEFAULT '[]',
            intent TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS session_facts (
            session_id TEXT PRIMARY KEY,
            facts_json TEXT NOT NULL DEFAULT '{}',
            stage TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE TABLE IF NOT EXISTS leads (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            full_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            company TEXT NOT NULL,
            summary TEXT NOT NULL,
            consent_to_contact INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id,id);
        """)


def create_session() -> dict:
    item = {"id": str(uuid4()), "created_at": utcnow()}
    with connection() as db:
        db.execute("INSERT INTO sessions (id,created_at) VALUES (?,?)", (item["id"], item["created_at"]))
    return item


def session_exists(session_id: str, *, active_only: bool = False) -> bool:
    with connection() as db:
        sql = "SELECT 1 FROM sessions WHERE id=?" + (" AND closed_at IS NULL" if active_only else "")
        return db.execute(sql, (session_id,)).fetchone() is not None


def close_session(session_id: str) -> None:
    with connection() as db:
        db.execute("UPDATE sessions SET closed_at=? WHERE id=?", (utcnow(),session_id))


def list_sessions() -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT id,created_at,closed_at FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(x) for x in rows]


def add_message(session_id: str, role: str, content: str, sources: list[str] | None = None, intent: str | None = None) -> None:
    with connection() as db:
        db.execute(
            "INSERT INTO messages(session_id,role,content,sources_json,intent,created_at) VALUES (?,?,?,?,?,?)",
            (session_id, role, content, json.dumps(sources or [], ensure_ascii=False), intent, utcnow()),
        )


def list_messages(session_id: str) -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT id,role,content,sources_json,intent,created_at FROM messages WHERE session_id=? ORDER BY id", (session_id,)).fetchall()
        return [
            {**dict(row), "sources": json.loads(row["sources_json"])} | {"sources_json": None}
            for row in rows
        ]


def get_session_facts(session_id: str) -> dict:
    """Return the saved facts snapshot for a session, or a fresh empty dict."""
    with connection() as db:
        row = db.execute(
            "SELECT facts_json FROM session_facts WHERE session_id=?", (session_id,)
        ).fetchone()
    return json.loads(row["facts_json"]) if row else {}


def save_session_facts(session_id: str, facts: dict, stage: str | None = None) -> None:
    """Replace the snapshot after a successful AI turn (AI sends a full snapshot)."""
    if not isinstance(facts, dict):
        raise TypeError("session facts must be a dictionary")
    payload = json.dumps(facts, ensure_ascii=False)
    with connection() as db:
        db.execute(
            """INSERT INTO session_facts (session_id, facts_json, stage, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                   facts_json=excluded.facts_json,
                   stage=excluded.stage,
                   updated_at=excluded.updated_at""",
            (session_id, payload, stage, utcnow()),
        )


class LeadConflictError(Exception):
    """A session already has a lead with different contact details."""


def create_lead(session_id: str, full_name: str, phone: str, company: str, summary: str) -> tuple[dict, bool]:
    """Return (lead, created). Retries for the same lead reuse its original ID.

    One lead per session. BEGIN IMMEDIATE makes the check-and-insert atomic even
    when two requests arrive simultaneously. Existing database records are kept.
    """
    with connection() as db:
        db.execute("BEGIN IMMEDIATE")
        existing = db.execute(
            "SELECT id,session_id,full_name,phone,company,summary,created_at "
            "FROM leads WHERE session_id=? ORDER BY created_at,id LIMIT 1",
            (session_id,),
        ).fetchone()
        if existing:
            if (existing["full_name"], existing["phone"], existing["company"]) != (full_name, phone, company):
                raise LeadConflictError("This session already has a lead with different contact details")
            return {
                "id": existing["id"],
                "session_id": existing["session_id"],
                "summary": existing["summary"],
                "created_at": existing["created_at"],
            }, False

        lead_id = str(uuid4())
        created_at = utcnow()
        db.execute(
            "INSERT INTO leads(id,session_id,full_name,phone,company,summary,consent_to_contact,created_at) VALUES (?,?,?,?,?,?,1,?)",
            (lead_id, session_id, full_name, phone, company, summary, created_at),
        )
    return {"id": lead_id, "session_id": session_id, "summary": summary, "created_at": created_at}, True


def list_leads() -> list[dict]:
    with connection() as db:
        rows = db.execute("SELECT * FROM leads ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]
