"""Abstract database interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class SessionRecord:
    emoji: str
    number: int
    topic_label: str = ""
    status: str = "active"
    session_id: str = ""
    prompt_preview: str = ""
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class UsageRecord:
    session_id: str = ""
    source: str = "pigeon"
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    created_at: datetime = field(default_factory=datetime.now)


class Database(ABC):
    """Abstract base class for database backends."""

    @abstractmethod
    def initialize(self) -> None:
        """Create tables if they don't exist."""
        ...

    @abstractmethod
    def log_session(self, record: SessionRecord) -> None:
        """Insert or update a session record."""
        ...

    @abstractmethod
    def update_session(self, emoji: str, number: int, **fields) -> None:
        """Update specific fields on a session."""
        ...

    @abstractmethod
    def delete_session(self, emoji: str, number: int) -> None:
        """Remove a session record."""
        ...

    @abstractmethod
    def clear_sessions(self) -> None:
        """Remove all session records."""
        ...

    @abstractmethod
    def log_usage(self, record: UsageRecord) -> None:
        """Log a usage record."""
        ...

    @abstractmethod
    def get_sessions(self, active_only: bool = False) -> list[SessionRecord]:
        """Get session records."""
        ...
