"""SQLite database backend — local, zero-config."""

import logging
import sqlite3
from pathlib import Path

from pigeon.db.base import Database, SessionRecord, UsageRecord

log = logging.getLogger("pigeon")


class SQLiteDatabase(Database):
    """Local SQLite database for session and usage logging."""

    def __init__(self, path: str = "", **kwargs):
        self._path = path or str(Path.home() / ".pigeon" / "pigeon.db")

    def _connect(self):
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def initialize(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._connect()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emoji TEXT NOT NULL,
                number INTEGER NOT NULL,
                topic_label TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                session_id TEXT DEFAULT '',
                prompt_preview TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT DEFAULT '',
                source TEXT DEFAULT 'pigeon',
                model TEXT DEFAULT '',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_emoji TEXT,
                role TEXT,
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.close()
        log.info("SQLite database initialized at %s", self._path)

    def log_session(self, record: SessionRecord) -> None:
        conn = self._connect()
        # Delete existing then insert (upsert pattern)
        conn.execute(
            "DELETE FROM sessions WHERE emoji = ? AND number = ?",
            (record.emoji, record.number),
        )
        conn.execute(
            """INSERT INTO sessions (emoji, number, topic_label, status, session_id, prompt_preview)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (record.emoji, record.number, record.topic_label,
             record.status, record.session_id, record.prompt_preview[:200]),
        )
        conn.commit()
        conn.close()

    def update_session(self, emoji: str, number: int, **fields) -> None:
        if not fields:
            return
        allowed = {"topic_label", "status", "session_id", "prompt_preview"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return
        set_clause = ", ".join(f"{k} = ?" for k in filtered)
        values = list(filtered.values()) + [emoji, number]
        conn = self._connect()
        conn.execute(
            f"UPDATE sessions SET {set_clause}, updated_at = CURRENT_TIMESTAMP "
            f"WHERE emoji = ? AND number = ?",
            values,
        )
        conn.commit()
        conn.close()

    def delete_session(self, emoji: str, number: int) -> None:
        conn = self._connect()
        conn.execute(
            "DELETE FROM sessions WHERE emoji = ? AND number = ?",
            (emoji, number),
        )
        conn.commit()
        conn.close()

    def clear_sessions(self) -> None:
        conn = self._connect()
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()

    def log_usage(self, record: UsageRecord) -> None:
        conn = self._connect()
        conn.execute(
            """INSERT INTO usage (session_id, source, model, input_tokens, output_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (record.session_id, record.source, record.model,
             record.input_tokens, record.output_tokens, record.cost_usd),
        )
        conn.commit()
        conn.close()

    def get_sessions(self, active_only: bool = False) -> list[SessionRecord]:
        conn = self._connect()
        query = "SELECT * FROM sessions"
        if active_only:
            query += " WHERE status = 'active'"
        query += " ORDER BY number ASC"
        rows = conn.execute(query).fetchall()
        conn.close()
        return [
            SessionRecord(
                emoji=row["emoji"],
                number=row["number"],
                topic_label=row["topic_label"],
                status=row["status"],
                session_id=row["session_id"],
                prompt_preview=row["prompt_preview"],
            )
            for row in rows
        ]
