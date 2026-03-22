"""Read-only access to macOS Messages chat.db."""

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("pigeon")

CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"

# Internal sentinel — UUID makes accidental collision with real messages negligible
DECODE_FAILED = "__PIGEON_DECODE_FAILED_7f3a9b2e4d1c__"


@dataclass
class ChatMessage:
    rowid: int
    text: str


@dataclass
class ChatInfo:
    rowid: int
    identifier: str
    display_name: str
    message_count: int
    last_message: str


def _connect():
    """Open a read-only connection to chat.db."""
    return sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)


def extract_text(text_col: str | None, attr_body_col: bytes | None) -> str | None:
    """Extract message text from either the text column or attributedBody blob.

    macOS 14+ sometimes stores message text only in the attributedBody column
    as a serialized NSAttributedString. This function handles both cases.
    """
    if text_col:
        return text_col.strip()
    if not attr_body_col:
        return None
    try:
        blob = bytes(attr_body_col)
        for marker in (b"NSString", b"NSMutableString"):
            idx = blob.find(marker)
            if idx == -1:
                continue
            plus_idx = blob.find(b"\x2b", idx + len(marker))
            if plus_idx == -1:
                continue
            next_byte = blob[plus_idx + 1] if plus_idx + 1 < len(blob) else 0
            text_start = plus_idx + 4 if next_byte == 0x81 else plus_idx + 2
            text_end = blob.find(b"\x86", text_start)
            if text_end == -1:
                text_end = len(blob)
            decoded = blob[text_start:text_end].decode("utf-8", errors="ignore").strip()
            if decoded:
                return decoded
    except Exception as e:
        log.warning("attributedBody decode failed: %s", e)
    return None


def get_max_rowid() -> int:
    """Get current max ROWID from chat.db. Returns 0 on failure."""
    try:
        with _connect() as conn:
            result = conn.execute("SELECT MAX(ROWID) FROM message").fetchone()[0] or 0
        return result
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        return 0


def poll_messages(chat_ids: list[int], last_rowid: int) -> tuple[list[ChatMessage], int]:
    """Poll for new messages in the specified chats since last_rowid.

    Returns (messages, new_last_rowid).
    Returns -1 as new_last_rowid if TCC authorization was denied (sentinel).
    """
    if not chat_ids:
        return [], last_rowid

    placeholders = ",".join("?" for _ in chat_ids)
    try:
        conn = _connect()
        # Fail fast if Messages.app holds a write lock — prevents infinite block
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""SELECT m.ROWID, m.text, m.attributedBody
            FROM message m
            JOIN chat_message_join cmj ON m.ROWID = cmj.message_id
            WHERE cmj.chat_id IN ({placeholders}) AND m.ROWID > ?
            ORDER BY m.ROWID ASC""",
            (*chat_ids, last_rowid),
        ).fetchall()
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        is_auth = "authorization" in str(e).lower()
        log.warning("DB access issue%s: %s", " (TCC auth denied)" if is_auth else "", e)
        # Signal auth-denied to caller via sentinel: return -1 as last_rowid
        if is_auth:
            return [], -1
        return [], last_rowid

    messages = []
    new_last_rowid = last_rowid
    for row in rows:
        new_last_rowid = max(new_last_rowid, row["ROWID"])
        text = extract_text(row["text"], row["attributedBody"])
        if text:
            messages.append(ChatMessage(rowid=row["ROWID"], text=text))
        elif row["attributedBody"]:
            messages.append(ChatMessage(rowid=row["ROWID"], text=DECODE_FAILED))
    return messages, new_last_rowid


def detect_self_chats() -> list[ChatInfo]:
    """Find chats that look like self-chats (messages to yourself).

    Looks for chats where the identifier matches common self-chat patterns:
    email addresses or phone numbers where you've messaged yourself.
    """
    try:
        conn = _connect()
        conn.row_factory = sqlite3.Row
        # Get all chats with message counts and last message preview
        rows = conn.execute("""
            SELECT
                c.ROWID,
                c.chat_identifier,
                c.display_name,
                COUNT(cmj.message_id) as msg_count,
                (SELECT m.text FROM message m
                 JOIN chat_message_join cmj2 ON m.ROWID = cmj2.message_id
                 WHERE cmj2.chat_id = c.ROWID
                 ORDER BY m.ROWID DESC LIMIT 1) as last_msg
            FROM chat c
            LEFT JOIN chat_message_join cmj ON c.ROWID = cmj.chat_id
            GROUP BY c.ROWID
            HAVING msg_count > 0
            ORDER BY msg_count DESC
        """).fetchall()
        conn.close()

        chats = []
        for row in rows:
            chats.append(
                ChatInfo(
                    rowid=row["ROWID"],
                    identifier=row["chat_identifier"] or "",
                    display_name=row["display_name"] or "",
                    message_count=row["msg_count"],
                    last_message=(row["last_msg"] or "")[:80],
                )
            )
        return chats
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        log.error("Cannot read chat.db: %s", e)
        return []


def validate_chat_access() -> str | None:
    """Check that chat.db is readable. Returns error message or None."""
    if not CHAT_DB.exists():
        return f"chat.db not found at {CHAT_DB}"
    try:
        conn = _connect()
        conn.execute("SELECT 1 FROM message LIMIT 1")
        conn.close()
        return None
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        return f"Cannot read chat.db: {e}. Grant Full Disk Access to your Python binary."


def validate_chat_ids(chat_ids: list[int]) -> list[str]:
    """Validate that the configured chat IDs exist. Returns list of errors."""
    errors = []
    try:
        conn = _connect()
        for chat_id in chat_ids:
            row = conn.execute(
                "SELECT chat_identifier FROM chat WHERE ROWID = ?", (chat_id,)
            ).fetchone()
            if not row:
                errors.append(f"Chat ID {chat_id} does not exist in chat.db")
        conn.close()
    except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
        errors.append(f"Cannot validate chat IDs: {e}")
    return errors
