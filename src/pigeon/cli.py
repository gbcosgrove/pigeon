"""Pigeon CLI — install, start, stop, status, detect-chat."""

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

from pigeon import __version__
from pigeon.config import (
    CONFIG_DIR,
    CONFIG_FILE,
    DEFAULT_CONFIG,
    LOG_DIR,
    ensure_dirs,
    load_config,
    save_config,
)

LABEL = "com.pigeon.imessage-agent"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"

log = logging.getLogger("pigeon")


def cmd_install(args):
    """Interactive installer — detects chat, configures LLM, sets up launchd."""
    print("=== Pigeon Installer ===\n")

    ensure_dirs()

    # Step 1: Check prerequisites
    print("Checking prerequisites...")
    python_bin = sys.executable
    if not python_bin:
        print("ERROR: Cannot determine Python binary path")
        return 1

    # Step 2: Detect chat
    print("\nDetecting self-chats in iMessage...")
    chat_ids, identifier = _interactive_detect_chat()
    if not chat_ids:
        print("ERROR: No chat selected. Cannot continue.")
        return 1

    # Step 3: Choose LLM backend
    print("\nChoose your LLM backend:")
    print("  1. claude-cli  (Claude Code CLI — no API key needed)")
    print("  2. anthropic   (Anthropic API — needs ANTHROPIC_API_KEY)")
    print("  3. openai      (OpenAI API — needs OPENAI_API_KEY)")
    print("  4. ollama      (Local models — needs Ollama running)")
    choice = input("\nBackend [1]: ").strip() or "1"
    backend_map = {"1": "claude-cli", "2": "anthropic", "3": "openai", "4": "ollama"}
    backend = backend_map.get(choice, "claude-cli")

    # Step 4: Triage model
    print(f"\nMain backend: {backend}")
    use_triage = input("Use a separate (cheaper) model for triage? [y/N]: ").strip().lower()
    triage_backend = backend
    triage_model = None
    if use_triage == "y":
        print("  Triage backend options: claude-cli, anthropic, openai, ollama")
        triage_backend = input(f"  Triage backend [{backend}]: ").strip() or backend
        triage_model = input(
            "  Triage model name (e.g., claude-haiku-4-5-20251001): "
        ).strip() or None

    # Step 5: Trigger keyword
    keyword = input("\nTrigger keyword [pigeon]: ").strip() or "pigeon"

    # Step 6: Database
    print("\nDatabase for session/usage logging:")
    print("  1. none    (no database, state via JSON only)")
    print("  2. sqlite  (local SQLite — zero config)")
    print("  3. postgres (PostgreSQL/Supabase — needs connection URL)")
    db_choice = input("Database [1]: ").strip() or "1"
    db_map = {"1": "none", "2": "sqlite", "3": "postgres"}
    db_backend = db_map.get(db_choice, "none")

    db_url = ""
    if db_backend == "postgres":
        db_url = input("  PostgreSQL connection URL: ").strip()

    # Step 7: Build config
    config = dict(DEFAULT_CONFIG)
    config["chat"] = {"ids": chat_ids, "identifier": identifier}
    config["trigger"] = {
        "keyword": keyword,
        "expand_keyword": f"{keyword}:cc",
        "status_keyword": f"{keyword}:status",
        "off_keyword": f"{keyword}:off",
    }
    config["llm"] = {
        "main": {"backend": backend, "model": None},
        "triage": {"backend": triage_backend, "model": triage_model},
    }
    config["database"] = {
        "backend": db_backend, "path": str(CONFIG_DIR / "pigeon.db"), "url": db_url,
    }

    save_config(config)
    print(f"\nConfig saved to {CONFIG_FILE}")

    # Step 8: Build PigeonSend.app
    print("\nBuilding PigeonSend.app...")
    _build_send_app()

    # Step 9: Initialize state
    _init_state(chat_ids)

    # Step 10: Set up launchd
    print("\nSetting up launchd daemon...")
    _setup_launchd(python_bin)

    # Step 11: Print manual steps
    print(f"""
=== Pigeon installed! ===

  Config:  {CONFIG_FILE}
  Logs:    tail -f {LOG_DIR}/stderr.log
  Test:    Send '{keyword}: hello' to yourself in Messages

Manual steps required (one-time):
  1. System Settings > Privacy & Security > Full Disk Access
     Add: {python_bin}
  2. System Settings > Privacy & Security > Automation
     Allow: Python to control Messages.app

  Then restart: pigeon restart
""")
    return 0


def cmd_detect_chat(args):
    """Detect self-chats in iMessage."""
    from pigeon.chatdb import detect_self_chats

    print("Scanning chats in Messages database...\n")
    chats = detect_self_chats()

    if not chats:
        print("No chats found. Is Full Disk Access enabled for Python?")
        return 1

    # Show chats for user to pick
    print(f"Found {len(chats)} chats. Showing top 20 by message count:\n")
    display = chats[:20]
    for i, chat in enumerate(display, 1):
        name = chat.display_name or chat.identifier
        preview = chat.last_message[:40] if chat.last_message else ""
        print(f"  {i:2d}. [{chat.rowid:5d}] {name} ({chat.message_count} msgs)")
        if preview:
            print(f"              Last: {preview}...")

    print("\nYour self-chat is typically your own phone number or Apple ID email.")
    selection = input("\nEnter the number(s) of your self-chat (comma-separated): ").strip()
    if not selection:
        print("No selection made.")
        return 1

    selected_ids = []
    identifier = ""
    for s in selection.split(","):
        try:
            idx = int(s.strip()) - 1
            if 0 <= idx < len(display):
                chat = display[idx]
                selected_ids.append(chat.rowid)
                if not identifier:
                    identifier = chat.identifier
        except ValueError:
            continue

    if selected_ids:
        # Update config
        try:
            config_data = {}
            if CONFIG_FILE.exists():
                import yaml
                with open(CONFIG_FILE) as f:
                    config_data = yaml.safe_load(f) or {}
            config_data.setdefault("chat", {})
            config_data["chat"]["ids"] = selected_ids
            config_data["chat"]["identifier"] = identifier
            save_config(config_data)
            print(f"\nSaved chat IDs {selected_ids} ({identifier}) to {CONFIG_FILE}")
        except Exception as e:
            print(f"\nDetected chat IDs: {selected_ids} ({identifier})")
            print(f"Error saving config: {e}")
            print(f"Add these manually to {CONFIG_FILE}")
    return 0


def cmd_start(args):
    """Start the daemon."""
    if PLIST_PATH.exists():
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
            capture_output=True,
        )
        print("Pigeon daemon started via launchd.")
        print(f"Logs: tail -f {LOG_DIR}/stderr.log")
    else:
        print("Pigeon not installed. Run 'pigeon install' first.")
        return 1
    return 0


def cmd_stop(args):
    """Stop the daemon."""
    uid = os.getuid()
    result = subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("Pigeon daemon stopped.")
    else:
        print("Pigeon daemon not running or already stopped.")
    return 0


def cmd_restart(args):
    """Restart the daemon."""
    cmd_stop(args)
    import time
    time.sleep(1)
    return cmd_start(args)


def cmd_status(args):
    """Check daemon status."""
    result = subprocess.run(
        ["launchctl", "list"],
        capture_output=True, text=True,
    )
    if LABEL in result.stdout:
        print("Pigeon daemon: RUNNING")
        # Show heartbeat age
        import time

        from pigeon.config import HEARTBEAT_FILE
        try:
            ts = float(HEARTBEAT_FILE.read_text())
            age = time.time() - ts
            print(f"Last heartbeat: {age:.0f}s ago")
        except (FileNotFoundError, ValueError):
            print("Last heartbeat: unknown")
    else:
        print("Pigeon daemon: STOPPED")

    # Show config summary
    config = load_config()
    print(f"\nConfig: {CONFIG_FILE}")
    print(f"Chat IDs: {config.chat_ids}")
    print(f"LLM backend: {config.llm_main_backend}")
    print(f"Trigger: {config.trigger_keyword}:")
    print(f"Database: {config.db_backend}")
    return 0


def cmd_uninstall(args):
    """Uninstall Pigeon — stop daemon, remove plist and state."""
    print("=== Pigeon Uninstall ===\n")

    # Stop daemon
    cmd_stop(args)

    # Remove plist
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        print(f"Removed {PLIST_PATH}")

    # Ask about state
    if CONFIG_DIR.exists():
        keep = input(f"\nKeep config and state at {CONFIG_DIR}? [Y/n]: ").strip().lower()
        if keep == "n":
            import shutil
            shutil.rmtree(CONFIG_DIR)
            print(f"Removed {CONFIG_DIR}")
        else:
            print(f"Kept {CONFIG_DIR}")

    print("\nPigeon uninstalled.")
    return 0


def cmd_run(args):
    """Run daemon in foreground (for debugging)."""
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stderr,
    )

    from pigeon.daemon import PigeonDaemon
    daemon = PigeonDaemon()
    daemon.run()


# ── Helper functions ──────────────────────────────────────

def _interactive_detect_chat() -> tuple[list[int], str]:
    """Run chat detection interactively. Returns (chat_ids, identifier)."""
    from pigeon.chatdb import detect_self_chats

    chats = detect_self_chats()
    if not chats:
        print("No chats found. Is Full Disk Access enabled for Python?")
        return [], ""

    print(f"Found {len(chats)} chats. Showing top 15 by message count:\n")
    display = chats[:15]
    for i, chat in enumerate(display, 1):
        name = chat.display_name or chat.identifier
        print(f"  {i:2d}. [{chat.rowid:5d}] {name} ({chat.message_count} msgs)")

    print("\nYour self-chat is typically your own phone number or Apple ID.")
    selection = input("Enter the number(s) of your self-chat (comma-separated): ").strip()

    selected_ids = []
    identifier = ""
    for s in selection.split(","):
        try:
            idx = int(s.strip()) - 1
            if 0 <= idx < len(display):
                chat = display[idx]
                selected_ids.append(chat.rowid)
                if not identifier:
                    identifier = chat.identifier
        except ValueError:
            continue

    return selected_ids, identifier


def _build_send_app():
    """Build PigeonSend.app from AppleScript source."""
    app_dir = CONFIG_DIR / "PigeonSend.app"
    if app_dir.exists():
        print("  PigeonSend.app already exists, skipping build.")
        return

    applescript = '''
on run
    set payloadPath to "/tmp/pigeon-send-payload.txt"
    set errorPath to "/tmp/pigeon-send-error.log"

    try
        set payloadContent to read POSIX file payloadPath as «class utf8»
        set AppleScript's text item delimiters to linefeed
        set payloadLines to text items of payloadContent
        set buddyId to item 1 of payloadLines
        set msgText to (items 2 thru -1 of payloadLines) as text
        set AppleScript's text item delimiters to ""

        tell application "Messages"
            set targetService to 1st account whose service type = iMessage
            set targetBuddy to participant buddyId of targetService
            send msgText to targetBuddy
        end tell

        -- Clean up payload to signal completion
        do shell script "rm -f " & quoted form of payloadPath

    on error errMsg number errNum
        -- Write error for the caller to read
        do shell script "echo " & quoted form of errMsg & " > " & quoted form of errorPath
        do shell script "rm -f " & quoted form of payloadPath
    end try
end run
'''

    # Write AppleScript source
    script_path = CONFIG_DIR / "PigeonSend.applescript"
    script_path.write_text(applescript)

    # Compile to .app
    result = subprocess.run(
        ["osacompile", "-o", str(app_dir), str(script_path)],
        capture_output=True, text=True,
    )
    script_path.unlink(missing_ok=True)

    if result.returncode == 0:
        print("  Built PigeonSend.app")
    else:
        print(f"  WARNING: Failed to build PigeonSend.app: {result.stderr}")
        print("  Falling back to direct osascript (may need Automation permission)")


def _init_state(chat_ids: list[int]):
    """Initialize state.json with current max ROWID."""
    import json

    from pigeon.chatdb import get_max_rowid
    from pigeon.config import STATE_FILE

    if STATE_FILE.exists():
        print("  state.json already exists, keeping it.")
        return

    max_rowid = get_max_rowid()
    state = {"last_rowid": max_rowid, "last_full_response": "",
             "sessions": {}, "front_session": None}
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)
    print(f"  Initialized state.json (ROWID: {max_rowid})")


def _setup_launchd(python_bin: str):
    """Generate and load launchd plist."""
    # Find pigeon entry point
    pigeon_bin = None
    for d in os.environ.get("PATH", "").split(":"):
        candidate = os.path.join(d, "pigeon")
        if os.path.isfile(candidate):
            pigeon_bin = candidate
            break

    # Fallback: use python -m pigeon.cli
    if pigeon_bin:
        program_args = f"""    <array>
        <string>{pigeon_bin}</string>
        <string>run</string>
    </array>"""
    else:
        program_args = f"""    <array>
        <string>{python_bin}</string>
        <string>-m</string>
        <string>pigeon.cli</string>
        <string>run</string>
    </array>"""

    home = str(Path.home())
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LABEL}</string>
    <key>ProgramArguments</key>
{program_args}
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>90</integer>
    <key>StandardOutPath</key>
    <string>{LOG_DIR}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:{home}/.pyenv/shims:{home}/.local/bin</string>
        <key>HOME</key>
        <string>{home}</string>
    </dict>
</dict>
</plist>"""

    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLIST_PATH.write_text(plist)
    print(f"  Wrote {PLIST_PATH}")

    # Unload existing if present
    uid = os.getuid()
    subprocess.run(
        ["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
        capture_output=True,
    )

    # Load new
    result = subprocess.run(
        ["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print("  Daemon started.")
    else:
        print(f"  WARNING: launchctl bootstrap failed: {result.stderr}")


def main():
    parser = argparse.ArgumentParser(
        prog="pigeon",
        description="Pigeon — Turn iMessage into an AI assistant interface.",
    )
    parser.add_argument("--version", action="version", version=f"pigeon {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    subparsers.add_parser("install", help="Interactive setup — detect chat, configure LLM")
    subparsers.add_parser("detect-chat", help="Detect and configure your self-chat ID")
    subparsers.add_parser("start", help="Start the daemon")
    subparsers.add_parser("stop", help="Stop the daemon")
    subparsers.add_parser("restart", help="Restart the daemon")
    subparsers.add_parser("status", help="Check daemon status and config")
    subparsers.add_parser("uninstall", help="Stop daemon and remove configuration")

    run_parser = subparsers.add_parser("run", help="Run daemon in foreground (for debugging)")
    run_parser.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "install": cmd_install,
        "detect-chat": cmd_detect_chat,
        "start": cmd_start,
        "stop": cmd_stop,
        "restart": cmd_restart,
        "status": cmd_status,
        "uninstall": cmd_uninstall,
        "run": cmd_run,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
