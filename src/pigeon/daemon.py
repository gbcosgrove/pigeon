"""Main Pigeon daemon — polls iMessage and dispatches to LLM backends."""

import logging
import os
import queue  # noqa: F401 — used in _handle_message for queue.Full
import re
import signal
import sqlite3
import sys
import threading
import time

from pigeon.chatdb import poll_messages, validate_chat_access, validate_chat_ids
from pigeon.config import HEARTBEAT_FILE, PigeonConfig, ensure_dirs, load_config
from pigeon.db import get_database
from pigeon.llm import get_backend
from pigeon.sender import send_imessage
from pigeon.session import SessionManager

log = logging.getLogger("pigeon")

# TCC auth-denied: consecutive failures before self-restart (~60s)
AUTH_DENIED_RESTART_THRESHOLD = 12


class PigeonDaemon:
    """The main daemon that polls iMessage and routes messages to sessions."""

    def __init__(self, config: PigeonConfig | None = None):
        self.config = config or load_config()
        self._last_lock_log = 0.0
        self._sent_online = False
        self._shutdown = threading.Event()
        self._consecutive_auth_denied = 0

        # Initialize LLM backends
        self.main_backend = get_backend(
            self.config.llm_main_backend,
            working_directory=self.config.working_directory,
            stale_timeout=self.config.stale_timeout,
        )
        self.triage_backend = get_backend(
            self.config.llm_triage_backend,
            working_directory=self.config.working_directory,
        )

        # Initialize database
        self.database = get_database(
            self.config.db_backend,
            path=self.config.db_path,
            url=self.config.db_url,
        )
        if self.database:
            self.database.initialize()

        # The buddy to send responses to (first chat identifier)
        self._buddy = self.config.chat_identifier

        # Initialize session manager
        self.sessions = SessionManager(
            config=self.config,
            main_backend=self.main_backend,
            triage_backend=self.triage_backend,
            database=self.database,
            send_fn=lambda text: send_imessage(self._buddy, text),
        )

    def startup_checks(self) -> list[str]:
        """Run pre-flight checks. Returns list of errors (empty = OK).

        Retries chat.db access with backoff — TCC can be slow after wake.
        """
        errors = []

        # Check chat.db access with retry (TCC can be slow after Mac wake)
        db_ok = False
        for attempt in range(5):
            db_error = validate_chat_access()
            if not db_error:
                db_ok = True
                break
            if attempt < 4:
                wait = 2 ** (attempt + 1)
                log.warning(
                    "chat.db not ready (attempt %d/5): %s — retrying in %ds",
                    attempt + 1,
                    db_error,
                    wait,
                )
                time.sleep(wait)
        if not db_ok:
            errors.append(db_error)

        # Check chat IDs
        if self.config.chat_ids:
            errors.extend(validate_chat_ids(self.config.chat_ids))
        else:
            errors.append("No chat IDs configured. Run 'pigeon detect-chat'.")

        # Check main LLM backend
        if not self.main_backend.available:
            errors.append(
                f"Main LLM backend '{self.config.llm_main_backend}' is not available. "
                f"Check installation and credentials."
            )

        # Check buddy
        if not self._buddy:
            errors.append("No chat identifier configured. Run 'pigeon detect-chat'.")

        return errors

    def _start_watchdog(self):
        """Monitor heartbeat. Detects system sleep and stale heartbeats.

        If the heartbeat is stale, requests graceful shutdown first,
        then hard-kills after 10s if the main loop hasn't exited.
        """
        timeout = self.config.heartbeat_timeout

        def _watchdog():
            last_mono = time.monotonic()
            while not self._shutdown.is_set():
                self._shutdown.wait(timeout)
                if self._shutdown.is_set():
                    break

                # Detect system sleep: monotonic gap >> expected means Mac was asleep
                now_mono = time.monotonic()
                elapsed = now_mono - last_mono
                last_mono = now_mono
                if elapsed > timeout * 2:
                    log.info("Watchdog: detected system sleep (%.0fs gap), skipping check", elapsed)
                    continue

                try:
                    ts = float(HEARTBEAT_FILE.read_text())
                    age = time.time() - ts
                    if age > timeout:
                        log.error("Watchdog: heartbeat stale (%.0fs). Requesting shutdown.", age)
                        self._shutdown.set()
                        time.sleep(10)
                        if threading.main_thread().is_alive():
                            log.error("Main loop did not exit — forcing os._exit(1)")
                            sys.stderr.flush()
                            sys.stdout.flush()
                            os._exit(1)
                except (FileNotFoundError, ValueError):
                    pass

        t = threading.Thread(target=_watchdog, daemon=True)
        t.start()
        log.info("Watchdog started (timeout=%ds)", timeout)

    def run(self):
        """Start the daemon. Blocks forever (until shutdown signal)."""
        ensure_dirs()

        # Register signal handlers for graceful shutdown
        def _handle_signal(signum, _frame):
            name = signal.Signals(signum).name
            log.warning("Received %s — shutting down gracefully", name)
            self._shutdown.set()

        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGHUP, signal.SIG_IGN)

        errors = self.startup_checks()
        if errors:
            for e in errors:
                log.error("Startup check failed: %s", e)
            sys.exit(1)

        self.sessions.restore_sessions()
        self._start_watchdog()

        log.info(
            "Pigeon started. ROWID: %d, sessions: %d, buddy: %s",
            self.sessions.last_rowid,
            len(self.sessions.sessions),
            self._buddy,
        )

        while not self._shutdown.is_set():
            try:
                # Touch heartbeat before poll so watchdog doesn't fire on a slow DB lock
                HEARTBEAT_FILE.write_text(str(time.time()))

                self._poll_cycle()
            except (sqlite3.OperationalError, sqlite3.DatabaseError) as e:
                now = time.time()
                if now - self._last_lock_log > 60:
                    log.warning("DB issue: %s", e)
                    self._last_lock_log = now
            except Exception:
                log.exception("Unexpected error in poll loop")

            # Touch heartbeat after poll
            try:
                HEARTBEAT_FILE.write_text(str(time.time()))
            except OSError:
                pass
            self._shutdown.wait(self.config.poll_interval)

        self._graceful_shutdown()

    def _poll_cycle(self):
        messages, new_last_rowid = poll_messages(self.config.chat_ids, self.sessions.last_rowid)

        # TCC auth-denied detection: poll_messages returns -1 as sentinel
        if new_last_rowid == -1:
            self._consecutive_auth_denied += 1
            if self._consecutive_auth_denied >= AUTH_DENIED_RESTART_THRESHOLD:
                log.error(
                    "TCC auth denied %d consecutive polls — restarting for fresh grant",
                    self._consecutive_auth_denied,
                )
                icon = self.config.icon
                try:
                    send_imessage(self._buddy, f"{icon} TCC grant lost — restarting...")
                except Exception:
                    pass
                self.sessions.save()
                sys.exit(1)  # launchd restarts with fresh TCC grant
            return
        else:
            self._consecutive_auth_denied = 0

        if not self._sent_online:
            self._sent_online = True
            icon = self.config.icon
            if self.sessions.has_sessions:
                status = self.sessions.get_status()
                send_imessage(self._buddy, f"{icon} Back online. Active sessions:\n{status}")
            else:
                send_imessage(self._buddy, f"{icon} Back online.")

        for msg in messages:
            if self._shutdown.is_set():
                break
            # Always advance ROWID per message — never get stuck on a bad message
            self.sessions.last_rowid = max(self.sessions.last_rowid, msg.rowid)

            try:
                text = msg.text.strip()
                text_lower = text.lower()
            except Exception:
                log.warning("Bad message ROWID=%d, skipping", msg.rowid)
                continue

            # Skip our own responses
            icon = self.config.icon
            if text.startswith(icon) or text.startswith("[error:") or text.startswith("[truncated"):
                continue
            if icon in text:
                continue

            try:
                self._handle_message(text, text_lower)
            except Exception:
                log.exception("Error processing message ROWID=%d: %s", msg.rowid, text[:60])

        self.sessions.save()

    def _graceful_shutdown(self):
        """Clean up on shutdown: end sessions, flush state."""
        log.info("Graceful shutdown starting...")
        try:
            self.sessions.end_all_sessions()
        except Exception:
            pass
        try:
            self.sessions.save()
        except Exception as e:
            log.warning("Failed to save state during shutdown: %s", e)
        log.info("Graceful shutdown complete.")

    def _handle_message(self, text: str, text_lower: str):
        trigger = self.config.trigger_keyword.lower()
        off_trigger = self.config.off_keyword.lower()
        expand_trigger = self.config.expand_keyword.lower()
        status_trigger = self.config.status_keyword.lower()
        icon = self.config.icon

        # Normalize spacing: "pigeon: X" → "pigeon:X"
        text_norm = re.sub(rf"^{re.escape(trigger)}\s*:\s*", f"{trigger}:", text_lower)

        # Status
        if text_norm == status_trigger:
            send_imessage(self._buddy, self.sessions._ack(self.sessions._ACKS_STATUS))
            status = self.sessions.get_status()
            send_imessage(self._buddy, f"{icon} Sessions:\n{status}")
            return

        # Off
        if text_lower.startswith(off_trigger):
            rest = text[len(off_trigger) :].strip()
            if rest:
                target = self.sessions.find_session_by_ref(rest)
                if target:
                    tag = self.sessions._session_tag(self.sessions.sessions[target])
                    self.sessions.end_session(target)
                    remaining = self.sessions.get_status()
                    send_imessage(
                        self._buddy,
                        f"{tag}{self.sessions._ack(self.sessions._ACKS_END)}\n{remaining}",
                    )
                else:
                    msg = (
                        f"[unknown session '{rest}'. "
                        f"Use {self.config.status_keyword} to see active sessions.]"
                    )
                    send_imessage(self._buddy, msg)
            else:
                self.sessions.end_all_sessions()
                send_imessage(self._buddy, self.sessions._ack(self.sessions._ACKS_END_ALL))
            return

        # Expand
        if text_lower == expand_trigger:
            if not self.sessions.expand_last():
                send_imessage(self._buddy, "[no truncated response to expand]")
            return

        # Decode failure
        from pigeon.chatdb import DECODE_FAILED

        if text == DECODE_FAILED:
            if self.sessions.has_sessions:
                send_imessage(self._buddy, "[couldn't decode — resend as plain text]")
            return

        # Switch command: "pigeon:1", "pigeon:2" (just switch front, no message)
        switch_match = re.match(rf"^{re.escape(trigger)}:(\d+)$", text_norm)
        if switch_match:
            target = self.sessions.find_session_by_ref(switch_match.group(1))
            if target and target in self.sessions.sessions:
                self.sessions.switch_front(target)
                tag = self.sessions._session_tag(self.sessions.sessions[target])
                send_imessage(self._buddy, f"{icon} Switched to {tag.strip()}")
            else:
                send_imessage(
                    self._buddy,
                    f"[no session {switch_match.group(1)}. "
                    f"Use {self.config.status_keyword} to see active sessions.]",
                )
            return

        # Number prefix: "1: message" (colon required to avoid misrouting)
        num_match = re.match(r"^(\d):\s+(.+)", text, re.DOTALL)
        if num_match:
            target = self.sessions.find_session_by_ref(num_match.group(1))
            if target and target in self.sessions.sessions:
                prompt = num_match.group(2).strip()
                if prompt:
                    self.sessions.switch_front(target)
                    tag = self.sessions._session_tag(self.sessions.sessions[target])
                    try:
                        self.sessions.sessions[target]["queue"].put_nowait({"prompt": prompt})
                        send_imessage(
                            self._buddy, f"{tag}{self.sessions._ack(self.sessions._ACKS_FOLLOWUP)}"
                        )
                    except queue.Full:
                        send_imessage(
                            self._buddy, f"{tag}[queue full — wait for current request to finish]"
                        )
                return

        # Emoji prefix
        for emoji in list(self.sessions.sessions.keys()):
            if text.startswith(emoji):
                prompt = text[len(emoji) :].strip()
                if prompt:
                    self.sessions.switch_front(emoji)
                    tag = self.sessions._session_tag(self.sessions.sessions[emoji])
                    try:
                        self.sessions.sessions[emoji]["queue"].put_nowait({"prompt": prompt})
                        send_imessage(
                            self._buddy, f"{tag}{self.sessions._ack(self.sessions._ACKS_FOLLOWUP)}"
                        )
                    except queue.Full:
                        send_imessage(
                            self._buddy, f"{tag}[queue full — wait for current request to finish]"
                        )
                return

        # New session trigger
        trigger_with_colon = trigger + ":"
        if text_lower.startswith(trigger_with_colon):
            prompt = text[len(trigger_with_colon) :].strip()
            if not prompt:
                send_imessage(self._buddy, "[empty prompt]")
                return
            # Hard cap (0 = unlimited)
            if self.config.max_sessions and len(self.sessions.sessions) >= self.config.max_sessions:
                send_imessage(
                    self._buddy,
                    f"[max {self.config.max_sessions} sessions. End one first — "
                    f"{self.config.status_keyword} to see them.]",
                )
                return
            send_imessage(self._buddy, self.sessions._ack(self.sessions._ACKS_NEW))
            # Soft warning
            count = len(self.sessions.sessions)
            if count >= self.config.warn_at_sessions:
                send_imessage(
                    self._buddy,
                    f"[{icon} {count + 1} active sessions. "
                    f"Consider ending some with {self.config.off_keyword}]",
                )
            self.sessions.create_session(prompt)
            return

        # No trigger, sessions exist → route to front
        if (
            self.sessions.has_sessions
            and self.sessions.front_session
            and self.sessions.front_session in self.sessions.sessions
        ):
            front = self.sessions.front_session
            tag = self.sessions._session_tag(self.sessions.sessions[front])
            try:
                self.sessions.sessions[front]["queue"].put_nowait({"prompt": text})
                send_imessage(
                    self._buddy, f"{tag}{self.sessions._ack(self.sessions._ACKS_FOLLOWUP)}"
                )
            except queue.Full:
                send_imessage(
                    self._buddy, f"{tag}[queue full — wait for current request to finish]"
                )
