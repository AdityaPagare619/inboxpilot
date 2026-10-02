"""Local SQLite store: emails, triage decisions, user corrections, thresholds.

Everything InboxPilot learns stays on this machine. The Jev API never sees
this database — only the per-email state strings built by triage.py.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

from .triage import DEFAULT_THRESHOLDS

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id TEXT PRIMARY KEY,
    thread_id TEXT,
    sender TEXT,
    subject TEXT,
    date TEXT,
    snippet TEXT,
    body TEXT,
    labels_json TEXT,
    triaged_at REAL
);
CREATE TABLE IF NOT EXISTS decisions (
    email_id TEXT PRIMARY KEY,
    category TEXT,
    category_confidence REAL,
    category_probs_json TEXT,
    urgency_p REAL,
    needs_reply_p REAL,
    action TEXT,
    label TEXT,
    reasons_json TEXT,
    suggested_json TEXT,
    model TEXT,
    input_tokens INTEGER,
    reviewed INTEGER DEFAULT 0,
    approved INTEGER,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id TEXT,
    correct_category TEXT,
    correct_urgent INTEGER,   -- 1 / 0 / NULL (unknown)
    created_at REAL
);
CREATE TABLE IF NOT EXISTS thresholds (
    name TEXT PRIMARY KEY,
    value REAL,
    updated_at REAL
);
"""


def default_db_path() -> Path:
    override = os.environ.get("INBOXPLOT_DB")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "inboxpilot" / "inboxpilot.db"


class Store:
    """Tiny typed wrapper over the SQLite audit store."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        # Migration for DBs created before suggested_json existed.
        try:
            self._conn.execute("ALTER TABLE decisions ADD COLUMN suggested_json TEXT")
        except sqlite3.OperationalError:
            pass

    # -- emails -----------------------------------------------------------
    def save_email(self, email: dict) -> None:
        self._conn.execute(
            """INSERT OR REPLACE INTO emails
               (id, thread_id, sender, subject, date, snippet, body, labels_json, triaged_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email.get("id"),
                email.get("thread_id"),
                email.get("from"),
                email.get("subject"),
                email.get("date"),
                email.get("snippet"),
                email.get("body"),
                json.dumps(email.get("labels", [])),
                time.time(),
            ),
        )
        self._conn.commit()

    # -- decisions --------------------------------------------------------
    def save_decision(self, email_id: str, decision: dict) -> None:
        usage = decision.get("usage", {}) or {}
        self._conn.execute(
            """INSERT OR REPLACE INTO decisions
               (email_id, category, category_confidence, category_probs_json,
                urgency_p, needs_reply_p, action, label, reasons_json,
                suggested_json, model, input_tokens, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                email_id,
                decision.get("category"),
                decision.get("category_confidence"),
                json.dumps(decision.get("category_probs", {})),
                decision.get("urgency_p"),
                decision.get("needs_reply_p"),
                decision.get("action"),
                decision.get("label"),
                json.dumps(decision.get("reasons", [])),
                json.dumps(decision.get("suggested")),
                decision.get("model"),
                usage.get("input_tokens"),
                time.time(),
            ),
        )
        self._conn.commit()

    def get_decision(self, email_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM decisions WHERE email_id = ?", (email_id,)
        ).fetchone()
        return dict(row) if row else None

    def pending_digest(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM decisions WHERE action = 'digest' AND reviewed = 0"
            " ORDER BY urgency_p DESC, created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def digest_items(self) -> list[dict]:
        """Pending digest decisions joined with email subjects/senders."""
        rows = self._conn.execute(
            """SELECT d.*, e.sender, e.subject
               FROM decisions d
               JOIN emails e ON e.id = d.email_id
               WHERE d.action = 'digest' AND d.reviewed = 0
               ORDER BY d.urgency_p DESC, d.created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]

    def auto_handled_summary(self, since: float | None = None) -> dict:
        """Counts of auto actions (for the digest's 'handled' section)."""
        q = "SELECT action, label, COUNT(*) AS n FROM decisions WHERE action != 'digest'"
        params: tuple = ()
        if since is not None:
            q += " AND created_at >= ?"
            params = (since,)
        q += " GROUP BY action, label"
        rows = self._conn.execute(q, params).fetchall()
        return {(r["action"], r["label"]): r["n"] for r in rows}

    def mark_reviewed(self, email_id: str, approved: bool) -> None:
        self._conn.execute(
            "UPDATE decisions SET reviewed = 1, approved = ? WHERE email_id = ?",
            (1 if approved else 0, email_id),
        )
        self._conn.commit()

    # -- corrections (fuel for the tuner) ---------------------------------
    def record_correction(
        self, email_id: str, correct_category: str, correct_urgent: bool | None
    ) -> None:
        self._conn.execute(
            "INSERT INTO corrections (email_id, correct_category, correct_urgent, created_at)"
            " VALUES (?, ?, ?, ?)",
            (
                email_id,
                correct_category,
                None if correct_urgent is None else (1 if correct_urgent else 0),
                time.time(),
            ),
        )
        self._conn.commit()

    def correction_count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM corrections").fetchone()
        return int(row["n"])

    def get_corrections(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM corrections ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]

    def labeled_cases(self) -> list[dict]:
        """Corrections joined with the decisions + emails they correct.

        The fuel for the threshold tuner: each row carries the stored Jev
        probabilities (so decisions can be re-simulated) and the user's
        ground-truth correction.
        """
        rows = self._conn.execute(
            """SELECT d.*, c.correct_category, c.correct_urgent,
                      e.sender, e.subject
               FROM corrections c
               JOIN decisions d ON d.email_id = c.email_id
               JOIN emails e ON e.id = c.email_id
               ORDER BY c.created_at ASC"""
        ).fetchall()
        return [dict(r) for r in rows]

    # -- thresholds -------------------------------------------------------
    def get_thresholds(self) -> dict:
        merged = dict(DEFAULT_THRESHOLDS)
        for row in self._conn.execute("SELECT name, value FROM thresholds"):
            if row["name"] in merged:
                merged[row["name"]] = row["value"]
        return merged

    def set_threshold(self, name: str, value: float) -> None:
        if name not in DEFAULT_THRESHOLDS:
            raise KeyError(f"unknown threshold: {name}")
        self._conn.execute(
            "INSERT OR REPLACE INTO thresholds (name, value, updated_at)"
            " VALUES (?, ?, ?)",
            (name, value, time.time()),
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
