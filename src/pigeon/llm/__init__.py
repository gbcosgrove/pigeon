"""LLM backend registry."""

from pigeon.llm.base import LLMBackend, LLMResponse

_BACKENDS: dict[str, type[LLMBackend]] = {}


def register_backend(name: str, cls: type[LLMBackend]) -> None:
    _BACKENDS[name] = cls


def get_backend(name: str, **kwargs) -> LLMBackend:
    if name not in _BACKENDS:
        raise ValueError(
            f"Unknown LLM backend: {name}. "
            f"Available: {', '.join(_BACKENDS.keys())}"
        )
    return _BACKENDS[name](**kwargs)


# Register built-in backends on import
from pigeon.llm.anthropic_api import AnthropicBackend  # noqa: E402
from pigeon.llm.claude_cli import ClaudeCLIBackend  # noqa: E402
from pigeon.llm.ollama import OllamaBackend  # noqa: E402
from pigeon.llm.openai_api import OpenAIBackend  # noqa: E402

register_backend("claude-cli", ClaudeCLIBackend)
register_backend("anthropic", AnthropicBackend)
register_backend("openai", OpenAIBackend)
register_backend("ollama", OllamaBackend)

__all__ = ["LLMBackend", "LLMResponse", "get_backend", "register_backend"]
