"""Configuration loading and validation."""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

CONFIG_DIR = Path.home() / ".pigeon"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
STATE_DIR = CONFIG_DIR
STATE_FILE = STATE_DIR / "state.json"
RESPONSES_DIR = CONFIG_DIR / "responses"
HEARTBEAT_FILE = STATE_DIR / "heartbeat"
LOG_DIR = CONFIG_DIR / "logs"

DEFAULT_CONFIG = {
    "chat": {
        "ids": [],
        "identifier": "",
    },
    "trigger": {
        "keyword": "pigeon",
        "expand_keyword": "pigeon:cc",
        "status_keyword": "pigeon:status",
        "off_keyword": "pigeon:off",
    },
    "llm": {
        "main": {
            "backend": "claude-cli",
            "model": None,
        },
        "triage": {
            "backend": "claude-cli",
            "model": None,
        },
    },
    "sessions": {
        "max": 0,  # 0 = unlimited
        "warn_at": 10,
        "emojis": [
            "\U0001f534",
            "\U0001f535",
            "\U0001f7e2",
            "\U0001f7e1",
            "\U0001f7e3",  # 🔴🔵🟢🟡🟣
            "\U0001f7e0",
            "\U0001f7e4",
            "\u26aa",
            "\u26ab",
            "\U0001f535",  # 🟠🟤⚪⚫🔵
            "\U0001f4a0",
            "\U0001f4a5",
            "\U0001f525",
            "\U00002b50",
            "\U0001f30a",  # 💠💥🔥⭐🌊
            "\U0001f341",
            "\U0001f33b",
            "\U0001f340",
            "\U0001f30d",
            "\U0001f680",  # 🍁🌻🍀🌍🚀
        ],
    },
    "response": {
        "truncation_limit": 2000,
        "save_full": True,
        "save_directory": str(RESPONSES_DIR),
    },
    "database": {
        "backend": "none",
        "path": str(CONFIG_DIR / "pigeon.db"),
        "url": "",
    },
    "daemon": {
        "poll_interval": 5,
        "heartbeat_timeout": 120,
        "working_directory": str(Path.home()),
        "icon": "\U0001f54a",  # 🕊 dove
    },
}


def _env_substitute(value: str) -> str:
    """Replace ${VAR_NAME} with environment variable values."""

    def _replace(match):
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    if isinstance(value, str):
        return re.sub(r"\$\{(\w+)\}", _replace, value)
    return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, recursively for dicts."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@dataclass
class PigeonConfig:
    chat_ids: list[int] = field(default_factory=list)
    chat_identifier: str = ""
    trigger_keyword: str = "pigeon"
    expand_keyword: str = "pigeon:cc"
    status_keyword: str = "pigeon:status"
    off_keyword: str = "pigeon:off"
    llm_main_backend: str = "claude-cli"
    llm_main_model: str | None = None
    llm_triage_backend: str = "claude-cli"
    llm_triage_model: str | None = None
    max_sessions: int = 0  # 0 = unlimited
    warn_at_sessions: int = 10
    session_emojis: list[str] = field(default_factory=lambda: DEFAULT_CONFIG["sessions"]["emojis"])
    stale_timeout: int = 600  # kill LLM process after N seconds of no output
    truncation_limit: int = 2000
    save_full_responses: bool = True
    save_directory: str = str(RESPONSES_DIR)
    db_backend: str = "none"
    db_path: str = str(CONFIG_DIR / "pigeon.db")
    db_url: str = ""
    poll_interval: int = 5
    heartbeat_timeout: int = 120
    working_directory: str = str(Path.home())
    icon: str = "\U0001f54a"  # 🕊

    @classmethod
    def from_dict(cls, data: dict) -> "PigeonConfig":
        chat = data.get("chat", {})
        trigger = data.get("trigger", {})
        llm = data.get("llm", {})
        llm_main = llm.get("main", {})
        llm_triage = llm.get("triage", {})
        sessions = data.get("sessions", {})
        response = data.get("response", {})
        database = data.get("database", {})
        daemon = data.get("daemon", {})

        return cls(
            chat_ids=chat.get("ids", []),
            chat_identifier=chat.get("identifier", ""),
            trigger_keyword=trigger.get("keyword", "pigeon"),
            expand_keyword=trigger.get("expand_keyword", "pigeon:cc"),
            status_keyword=trigger.get("status_keyword", "pigeon:status"),
            off_keyword=trigger.get("off_keyword", "pigeon:off"),
            llm_main_backend=llm_main.get("backend", "claude-cli"),
            llm_main_model=llm_main.get("model"),
            llm_triage_backend=llm_triage.get("backend", "claude-cli"),
            llm_triage_model=llm_triage.get("model"),
            max_sessions=sessions.get("max", 0),
            warn_at_sessions=sessions.get("warn_at", 10),
            session_emojis=sessions.get("emojis", DEFAULT_CONFIG["sessions"]["emojis"]),
            stale_timeout=daemon.get("stale_timeout", 600),
            truncation_limit=response.get("truncation_limit", 2000),
            save_full_responses=response.get("save_full", True),
            save_directory=response.get("save_directory", str(RESPONSES_DIR)),
            db_backend=database.get("backend", "none"),
            db_path=database.get("path", str(CONFIG_DIR / "pigeon.db")),
            db_url=_env_substitute(database.get("url", "")),
            poll_interval=daemon.get("poll_interval", 5),
            heartbeat_timeout=daemon.get("heartbeat_timeout", 120),
            working_directory=daemon.get("working_directory", str(Path.home())),
            icon=daemon.get("icon", "\U0001f54a"),
        )

    def validate(self) -> list[str]:
        errors = []
        if not self.chat_ids:
            errors.append("No chat IDs configured. Run 'pigeon detect-chat' first.")
        if self.llm_main_backend not in ("claude-cli", "anthropic", "openai", "ollama"):
            errors.append(f"Unknown main LLM backend: {self.llm_main_backend}")
        if self.llm_triage_backend not in ("claude-cli", "anthropic", "openai", "ollama"):
            errors.append(f"Unknown triage LLM backend: {self.llm_triage_backend}")
        if self.max_sessions < 0:
            errors.append("max_sessions must be 0 (unlimited) or positive")
        if self.truncation_limit < 500:
            errors.append("truncation_limit must be at least 500")
        # Validate save_directory is under home
        if self.save_directory:
            save_path = Path(self.save_directory).expanduser().resolve()
            home = Path.home().resolve()
            if not str(save_path).startswith(str(home)):
                errors.append(f"save_directory must be under your home directory, got: {save_path}")
        return errors


def load_config() -> PigeonConfig:
    """Load config from ~/.pigeon/config.yaml, merged with defaults."""
    if not CONFIG_FILE.exists():
        return PigeonConfig.from_dict(DEFAULT_CONFIG)

    with open(CONFIG_FILE) as f:
        user_config = yaml.safe_load(f) or {}

    merged = _deep_merge(DEFAULT_CONFIG, user_config)
    return PigeonConfig.from_dict(merged)


def save_config(data: dict) -> None:
    """Save config dict to ~/.pigeon/config.yaml."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(data, f, default_flow_style=False, sort_keys=False)


def ensure_dirs() -> None:
    """Create all required directories."""
    for d in [CONFIG_DIR, LOG_DIR, RESPONSES_DIR]:
        d.mkdir(parents=True, exist_ok=True)
    # Secure permissions on config dir
    CONFIG_DIR.chmod(0o700)
