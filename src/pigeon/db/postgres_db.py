"""PostgreSQL database backend — for remote access and dashboards."""

import logging

from pigeon.db.base import Database, SessionRecord, UsageRecord

log = logging.getLogger("pigeon")


class PostgresDatabase(Database):
    """PostgreSQL/Supabase database for session and usage logging.

    Requires: pip install pigeon-imessage[postgres]
    Set database.url in config to your connection string.
    """

    def __init__(self, url: str = "", **kwargs):
        self._url = url
        self._conn = None

    def _get_conn(self):
        if self._conn is None or self._conn.closed:
            try:
                import psycopg2
                self._conn = psycopg2.connect(self._url)
                self._conn.autocommit = True
            except ImportError:
                raise RuntimeError(
                    "psycopg2 not installed. Run: pip install pigeon-imessage[postgres]"
                )
        return self._conn

    def initialize(self) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS pigeon_sessions (
                id SERIAL PRIMARY KEY,
                emoji TEXT NOT NULL,
                number INTEGER NOT NULL,
                topic_label TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                session_id TEXT DEFAULT '',
                prompt_preview TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS pigeon_usage (
                id SERIAL PRIMARY KEY,
                session_id TEXT DEFAULT '',
                source TEXT DEFAULT 'pigeon',
                model TEXT DEFAULT '',
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                cost_usd REAL DEFAULT 0.0,
                created_at TIMESTAMP DEFAULT NOW()
            );
        """)
        cur.close()
        log.info("PostgreSQL database initialized")

    def log_session(self, record: SessionRecord) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM pigeon_sessions WHERE emoji = %s AND number = %s",
            (record.emoji, record.number),
        )
        cur.execute(
            """INSERT INTO pigeon_sessions
            (emoji, number, topic_label, status, session_id, prompt_preview)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (record.emoji, record.number, record.topic_label,
             record.status, record.session_id, record.prompt_preview[:200]),
        )
        cur.close()

    def update_session(self, emoji: str, number: int, **fields) -> None:
        if not fields:
            return
        allowed = {"topic_label", "status", "session_id", "prompt_preview"}
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return
        set_clause = ", ".join(f"{k} = %s" for k in filtered)
        values = list(filtered.values()) + [emoji, number]
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            f"UPDATE pigeon_sessions SET {set_clause}, updated_at = NOW() "
            f"WHERE emoji = %s AND number = %s",
            values,
        )
        cur.close()

    def delete_session(self, emoji: str, number: int) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM pigeon_sessions WHERE emoji = %s AND number = %s",
            (emoji, number),
        )
        cur.close()

    def clear_sessions(self) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute("DELETE FROM pigeon_sessions")
        cur.close()

    def log_usage(self, record: UsageRecord) -> None:
        conn = self._get_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO pigeon_usage
            (session_id, source, model, input_tokens, output_tokens, cost_usd)
            VALUES (%s, %s, %s, %s, %s, %s)""",
            (record.session_id, record.source, record.model,
             record.input_tokens, record.output_tokens, record.cost_usd),
        )
        cur.close()

    def get_sessions(self, active_only: bool = False) -> list[SessionRecord]:
        conn = self._get_conn()
        cur = conn.cursor()
        query = ("SELECT emoji, number, topic_label, status, session_id, prompt_preview "
                 "FROM pigeon_sessions")
        if active_only:
            query += " WHERE status = 'active'"
        query += " ORDER BY number ASC"
        cur.execute(query)
        rows = cur.fetchall()
        cur.close()
        return [
            SessionRecord(
                emoji=row[0], number=row[1], topic_label=row[2],
                status=row[3], session_id=row[4], prompt_preview=row[5],
            )
            for row in rows
        ]
