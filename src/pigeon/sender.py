"""Send iMessages via AppleScript."""

import logging
import subprocess
import tempfile
import time
from pathlib import Path

log = logging.getLogger("pigeon")

# PigeonSend.app location (relative to package or user-configured)
_send_app_path: Path | None = None


def _find_send_app() -> Path | None:
    """Locate PigeonSend.app."""
    global _send_app_path
    if _send_app_path and _send_app_path.exists():
        return _send_app_path

    # Check common locations
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

    Uses PigeonSend.app if available, falls back to direct osascript.
    """
    clean = text.replace("\x00", "")

    app_path = _find_send_app()
    if app_path:
        return _send_via_app(buddy, clean, app_path)
    return _send_via_osascript(buddy, clean)


def _send_via_app(buddy: str, text: str, app_path: Path) -> bool:
    """Send via PigeonSend.app (preferred — runs in GUI session)."""
    payload_file = Path(tempfile.gettempdir()) / "pigeon-send-payload.txt"
    error_file = Path(tempfile.gettempdir()) / "pigeon-send-error.log"

    # Write payload: line 1 = buddy, remaining = message
    payload_file.write_text(f"{buddy}\n{text}")
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
    """Fallback: send directly via osascript."""
    # Escape for AppleScript string
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "Messages"
        set targetService to 1st account whose service type = iMessage
        set targetBuddy to participant "{buddy}" of targetService
        send "{escaped}" to targetBuddy
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


def send_chunked(buddy: str, text: str, chunk_size: int = 2000, delay: float = 1.5) -> bool:
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
