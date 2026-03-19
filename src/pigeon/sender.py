"""Send iMessages via AppleScript.

Security: All message content is passed via temp files, never embedded in
AppleScript string literals, to prevent AppleScript injection attacks.
"""

import logging
import os
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("pigeon")

# PigeonSend.app location (relative to package or user-configured)
_send_app_path: Path | None = None

# Serialize send operations to prevent payload file races
_send_lock = threading.Lock()

# Secure temp directory for payloads (under ~/.pigeon/, not world-readable /tmp)
_PAYLOAD_DIR = Path.home() / ".pigeon" / "tmp"


def _find_send_app() -> Path | None:
    """Locate PigeonSend.app."""
    global _send_app_path
    if _send_app_path and _send_app_path.exists():
        return _send_app_path

    candidates = [
        Path.home() / ".pigeon" / "PigeonSend.app",
        Path(__file__).parent.parent.parent / "scripts" / "PigeonSend.app",
    ]
    for path in candidates:
        if path.exists():
            _send_app_path = path
            return path
    return None


def send_imessage(buddy: str, text: str) -> bool:
    """Send an iMessage to the specified buddy (phone or email).

    Uses PigeonSend.app if available, falls back to file-based osascript.
    Both paths pass message content via temp files — never inline in scripts.
    """
    clean = text.replace("\x00", "")

    app_path = _find_send_app()
    if app_path:
        return _send_via_app(buddy, clean, app_path)
    return _send_via_osascript(buddy, clean)


def _send_via_app(buddy: str, text: str, app_path: Path) -> bool:
    """Send via PigeonSend.app (preferred — runs in GUI session)."""
    with _send_lock:
        _PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)
        _PAYLOAD_DIR.chmod(0o700)

        payload_file = _PAYLOAD_DIR / "pigeon-send-payload.txt"
        error_file = _PAYLOAD_DIR / "pigeon-send-error.log"

        # Write payload with restrictive permissions
        fd = os.open(str(payload_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, f"{buddy}\n{text}".encode("utf-8"))
        finally:
            os.close(fd)

        error_file.unlink(missing_ok=True)

        try:
            subprocess.run(["open", str(app_path)], check=True, timeout=5)
        except (subprocess.SubprocessError, subprocess.TimeoutExpired) as e:
            log.error("Failed to launch PigeonSend.app: %s", e)
            payload_file.unlink(missing_ok=True)
            return False

        # Wait for completion
        for _ in range(10):
            time.sleep(1)
            if error_file.exists():
                error_msg = error_file.read_text()
                log.error("PigeonSend.app error: %s", error_msg)
                payload_file.unlink(missing_ok=True)
                error_file.unlink(missing_ok=True)
                return False
            if not payload_file.exists():
                break

        payload_file.unlink(missing_ok=True)
        log.info("iMessage sent via app (%d chars)", len(text))
        return True


def _send_via_osascript(buddy: str, text: str) -> bool:
    """Fallback: send via osascript using file-based payload.

    Message content is read from a temp file inside the AppleScript,
    never embedded in the script string, preventing injection attacks.
    """
    _PAYLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _PAYLOAD_DIR.chmod(0o700)

    with _send_lock:
        msg_file = _PAYLOAD_DIR / "pigeon-osascript-msg.txt"
        fd = os.open(str(msg_file), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, text.encode("utf-8"))
        finally:
            os.close(fd)

        # Escape only the buddy identifier (phone/email — no user content)
        safe_buddy = buddy.replace("\\", "\\\\").replace('"', '\\"')
        msg_path = str(msg_file).replace("\\", "\\\\").replace('"', '\\"')

        # Read message from file inside AppleScript — never inline user text
        script = f'''
        set msgContent to read POSIX file "{msg_path}" as «class utf8»
        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant "{safe_buddy}" of targetService
            send msgContent to targetBuddy
        end tell
        '''

        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                log.error("osascript send failed: %s", result.stderr[:200])
                return False
            log.info("iMessage sent via osascript (%d chars)", len(text))
            return True
        except (subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            log.error("Send failed: %s", e)
            return False
        finally:
            msg_file.unlink(missing_ok=True)


def send_chunked(
    buddy: str, text: str, chunk_size: int = 2000, delay: float = 1.5,
) -> bool:
    """Send a long message in chunks."""
    chunks = []
    remaining = text
    while remaining:
        if len(remaining) <= chunk_size:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, chunk_size)
        if cut <= 0:
            cut = chunk_size
        chunks.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")

    success = True
    for i, chunk in enumerate(chunks):
        log.info("Sending chunk %d/%d (%d chars)", i + 1, len(chunks), len(chunk))
        if not send_imessage(buddy, chunk):
            success = False
        if i < len(chunks) - 1:
            time.sleep(delay)
    return success
