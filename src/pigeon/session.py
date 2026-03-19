"""Multi-session manager with emoji labels and queued processing."""

import json
import logging
import queue
import random
import threading
from pathlib import Path

from pigeon.config import STATE_DIR, STATE_FILE, PigeonConfig
from pigeon.db.base import Database, SessionRecord, UsageRecord
from pigeon.llm.base import LLMBackend
from pigeon.triage import TriageResult, generate_topic_label, triage_message
from pigeon.truncation import strip_markdown, truncate_response

log = logging.getLogger("pigeon")


class SessionManager:
    """Manages multiple concurrent AI sessions with emoji labels."""

    def __init__(self, config: PigeonConfig, main_backend: LLMBackend,
                 triage_backend: LLMBackend | None = None,
                 database: Database | None = None,
                 send_fn=None):
        self.config = config
        self.main_backend = main_backend
        self.triage_backend = triage_backend or main_backend
        self.database = database
        self._send = send_fn  # callable(text) -> bool
        self._sessions: dict[str, dict] = {}
        self._state_lock = threading.Lock()
        self._state = self._load_state()
        self._icon = config.icon

    # ── State persistence ─────────────────────────────────

    def _load_state(self) -> dict:
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
            if "last_rowid" not in state:
                raise ValueError("missing last_rowid")
            state.setdefault("last_full_response", "")
            state.setdefault("sessions", {})
            state.setdefault("front_session", None)
            return state
        except (json.JSONDecodeError, FileNotFoundError, ValueError) as e:
            log.warning("State file issue (%s), resetting", e)
            from pigeon.chatdb import get_max_rowid
            max_rowid = get_max_rowid()
            state = {"last_rowid": max_rowid, "last_full_response": "",
                     "sessions": {}, "front_session": None}
            self._save_state(state)
            return state

    def _save_state(self, state: dict | None = None):
        state = state or self._state
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)

    @property
    def last_rowid(self) -> int:
        with self._state_lock:
            return self._state["last_rowid"]

    @last_rowid.setter
    def last_rowid(self, value: int):
        with self._state_lock:
            self._state["last_rowid"] = value

    def save(self):
        with self._state_lock:
            self._save_state()

    # ── Ack messages ──────────────────────────────────────

    # Varied acknowledgment messages for natural feel
    _ACKS_NEW = ["Got it...", "On it...", "Copy that...", "Roger...",
                 "Heard...", "Working on it...", "Let me check..."]
    _ACKS_FOLLOWUP = ["Got it...", "Copy...", "Heard...", "Checking...",
                      "On it...", "Thinking..."]
    _ACKS_STATUS = ["Retrieving...", "Pulling status...", "Checking sessions...",
                     "Let me see..."]
    _ACKS_END = ["Wrapping up.", "Closing out.", "Done.", "Ended.", "Shutting down."]
    _ACKS_END_ALL = ["All sessions ended.", "Everything closed.", "All wrapped up.",
                      "Shutting it all down."]

    def _ack(self, pool: list[str]) -> str:
        return f"{self._icon} {random.choice(pool)}"

    def _send_msg(self, text: str):
        if self._send:
            self._send(text)

    # ── Session CRUD ──────────────────────────────────────

    def _session_tag(self, session: dict) -> str:
        num = session.get("number", "")
        topic = session.get("topic_label", "")
        emoji = session.get("emoji", "")
        parts = [emoji]
        if num:
            parts.append(str(num))
        if topic:
            parts.append(f" {topic}")
        return "".join(parts) + " "

    def get_available_slot(self) -> tuple[str | None, int | None]:
        used = set(self._sessions.keys())
        for i, e in enumerate(self.config.session_emojis):
            if e not in used:
                return e, i + 1
        return None, None

    def find_session_by_ref(self, ref: str) -> str | None:
        ref = ref.strip()
        if ref in self._sessions:
            return ref
        try:
            num = int(ref.rstrip(":"))
            for emoji, session in self._sessions.items():
                if session.get("number") == num:
                    return emoji
            return None
        except ValueError:
            pass
        for emoji in self._sessions:
            if ref.startswith(emoji):
                return emoji
        return None

    def create_session(self, prompt: str) -> str | None:
        emoji, number = self.get_available_slot()
        if not emoji:
            return None

        q = queue.Queue()
        session = {
            "emoji": emoji,
            "number": number,
            "session_id": None,
            "queue": q,
            "thread": None,
            "topic_raw": prompt[:50],
            "topic_label": "",
        }
        self._sessions[emoji] = session

        if self.database:
            self.database.log_session(SessionRecord(
                emoji=emoji, number=number, status="active",
                prompt_preview=prompt[:200],
            ))

        def _worker():
            log.info("[%s%d] Worker started: %s", emoji, number, prompt[:60])
            while True:
                try:
                    item = q.get(timeout=10)
                except queue.Empty:
                    if emoji not in self._sessions:
                        break
                    continue
                if item is None:
                    break
                self._process_message(
                    item["prompt"], item.get("first", False), session)
                q.task_done()
            log.info("[%s%d] Worker stopped", emoji, number)

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        session["thread"] = t
        q.put({"prompt": prompt, "first": True})

        with self._state_lock:
            self._state["front_session"] = emoji
            self._state["sessions"][emoji] = {
                "topic": prompt[:50], "session_id": None, "number": number,
            }
            self._save_state()

        return emoji

    def _process_message(self, prompt: str, is_first: bool, session: dict):
        tag = self._session_tag(session)

        if is_first:
            # Generate topic label in parallel
            topic_thread = threading.Thread(
                target=self._generate_topic, args=(prompt, session), daemon=True)
            topic_thread.start()

            # Triage
            category, triage_text = triage_message(
                prompt, self.triage_backend, self.config.llm_triage_model)

            topic_thread.join(timeout=15)
            tag = self._session_tag(session)

            if category in (TriageResult.TASK, TriageResult.CHECKING):
                response = self.main_backend.chat(
                    prompt, model=self.config.llm_main_model)
            else:
                # Triage answered directly — send it
                self._send_response(triage_text, tag)
                response = self.main_backend.chat(
                    prompt, model=self.config.llm_main_model)
                # Don't send main response if triage already answered
                if response.session_id:
                    self._update_session_id(session, response.session_id)
                return

            if response.session_id:
                self._update_session_id(session, response.session_id)

            if response.cost_usd and self.database:
                self.database.log_usage(UsageRecord(
                    session_id=response.session_id or "",
                    model=response.model,
                    input_tokens=response.input_tokens or 0,
                    output_tokens=response.output_tokens or 0,
                    cost_usd=response.cost_usd or 0.0,
                ))

            self._send_response(response.text, tag)
        else:
            resume_id = session.get("session_id")
            response = self.main_backend.chat(
                prompt, model=self.config.llm_main_model,
                resume_session=resume_id)
            if response.session_id:
                self._update_session_id(session, response.session_id)
            self._send_response(response.text, tag)

    def _generate_topic(self, prompt: str, session: dict):
        label = generate_topic_label(
            prompt, self.triage_backend, self.config.llm_triage_model)
        if label:
            session["topic_label"] = label
            if self.database:
                self.database.update_session(
                    session["emoji"], session["number"], topic_label=label)
            log.info("[%s%d] Topic: %s", session["emoji"], session["number"], label)

    def _update_session_id(self, session: dict, session_id: str):
        session["session_id"] = session_id
        emoji = session["emoji"]
        with self._state_lock:
            sd = self._state["sessions"].setdefault(emoji, {})
            sd["session_id"] = session_id
            sd["topic_label"] = session.get("topic_label", "")
            self._save_state()

    def _send_response(self, response: str, tag: str = ""):
        response = strip_markdown(response)
        prefix = f"{tag}{self._icon} " if tag else f"{self._icon} "
        full = prefix + response

        truncated_text, was_truncated = truncate_response(
            full, self.config.truncation_limit, self.config.expand_keyword)

        if was_truncated and self.config.save_full_responses:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y-%m-%d-%H%M")
            save_dir = Path(self.config.save_directory)
            save_dir.mkdir(parents=True, exist_ok=True)
            save_path = save_dir / f"pigeon-response-{timestamp}.md"
            save_path.write_text(full)
            log.info("Full response saved to %s", save_path)

        self._send_msg(truncated_text if was_truncated else full)

        with self._state_lock:
            self._state["last_full_response"] = full if was_truncated else ""
            self._save_state()

    # ── Session operations ────────────────────────────────

    def end_session(self, emoji: str):
        session = self._sessions.pop(emoji, None)
        if session:
            session["queue"].put(None)
            log.info("[%s] Ended: %s",
                     emoji, session.get("topic_label") or session.get("topic_raw", ""))
            if self.database:
                self.database.update_session(
                    emoji, session.get("number", 0), status="completed")
        with self._state_lock:
            self._state["sessions"].pop(emoji, None)
            if self._state.get("front_session") == emoji:
                remaining = list(self._sessions.keys())
                self._state["front_session"] = remaining[0] if remaining else None
            self._save_state()

    def end_all_sessions(self):
        for emoji in list(self._sessions.keys()):
            self.end_session(emoji)
        with self._state_lock:
            self._state["sessions"] = {}
            self._state["front_session"] = None
            self._save_state()

    def switch_front(self, emoji: str) -> bool:
        if emoji in self._sessions:
            with self._state_lock:
                self._state["front_session"] = emoji
                self._save_state()
            return True
        return False

    def get_status(self) -> str:
        if not self._sessions:
            return "No active sessions."
        front = self._state.get("front_session")
        lines = []
        for emoji, session in self._sessions.items():
            num = session.get("number", "?")
            label = session.get("topic_label") or session.get("topic_raw", "?")[:30]
            depth = session["queue"].qsize()
            is_front = " << front" if emoji == front else ""
            queued = f" [{depth} queued]" if depth > 0 else ""
            lines.append(f"  {emoji}{num} {label}{queued}{is_front}")
        return "\n".join(lines)

    def expand_last(self) -> bool:
        if self._state.get("last_full_response"):
            from pigeon.sender import send_chunked
            # Get buddy from config to send chunks
            send_chunked(
                self.config.chat_identifier,
                self._state["last_full_response"],
                self.config.truncation_limit,
            )
            self._state["last_full_response"] = ""
            return True
        return False

    @property
    def sessions(self) -> dict:
        return self._sessions

    @property
    def front_session(self) -> str | None:
        return self._state.get("front_session")

    @property
    def has_sessions(self) -> bool:
        return bool(self._sessions)

    # ── Restore after restart ─────────────────────────────

    def restore_sessions(self):
        saved = self._state.get("sessions", {})
        if not saved:
            return
        restored = 0
        for emoji, info in saved.items():
            if emoji in self.config.session_emojis and emoji not in self._sessions:
                session_id = info.get("session_id")
                if not session_id:
                    continue
                number = info.get("number", self.config.session_emojis.index(emoji) + 1)
                q = queue.Queue()
                session = {
                    "emoji": emoji,
                    "number": number,
                    "session_id": session_id,
                    "queue": q,
                    "thread": None,
                    "topic_raw": info.get("topic", ""),
                    "topic_label": info.get("topic_label", ""),
                }
                self._sessions[emoji] = session

                if self.database:
                    self.database.log_session(SessionRecord(
                        emoji=emoji, number=number,
                        topic_label=session.get("topic_label", ""),
                        status="active", session_id=session_id,
                        prompt_preview=info.get("topic", "")[:200],
                    ))

                def _make_worker(e, s, q_ref):
                    def _worker():
                        log.info("[%s%d] Worker restored (session=%s)",
                                 e, s["number"],
                                 s["session_id"][:8] if s["session_id"] else "none")
                        while True:
                            try:
                                item = q_ref.get(timeout=10)
                            except queue.Empty:
                                if e not in self._sessions:
                                    break
                                continue
                            if item is None:
                                break
                            self._process_message(item["prompt"], False, s)
                            q_ref.task_done()
                    return _worker

                t = threading.Thread(target=_make_worker(emoji, session, q), daemon=True)
                t.start()
                session["thread"] = t
                restored += 1
        if restored:
            log.info("Restored %d session(s) from state", restored)
