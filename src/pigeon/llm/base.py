"""Abstract LLM backend interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    """Response from an LLM backend."""
    text: str
    model: str = ""
    input_tokens: int | None = None
    output_tokens: int | None = None
    session_id: str | None = None
    cost_usd: float | None = None


class LLMBackend(ABC):
    """Abstract base class for LLM backends."""

    @abstractmethod
    def chat(self, prompt: str, model: str | None = None,
             resume_session: str | None = None) -> LLMResponse:
        """Send a prompt and get a response."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Backend identifier."""
        ...

    @property
    def available(self) -> bool:
        """Check if this backend is available (dependencies installed, etc)."""
        return True
