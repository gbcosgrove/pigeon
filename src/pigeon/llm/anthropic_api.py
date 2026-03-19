"""Anthropic API backend — direct API calls via the anthropic SDK."""

import logging
import os

from pigeon.llm.base import LLMBackend, LLMResponse

log = logging.getLogger("pigeon")

DEFAULT_MODEL = "claude-sonnet-4-20250514"


class AnthropicBackend(LLMBackend):
    """Uses the Anthropic Python SDK for inference.

    Requires: pip install pigeon-imessage[anthropic]
    Set ANTHROPIC_API_KEY environment variable.
    """

    def __init__(self, **kwargs):
        self._client = None

    @property
    def name(self) -> str:
        return "anthropic"

    @property
    def available(self) -> bool:
        try:
            import anthropic  # noqa: F401
            return bool(os.environ.get("ANTHROPIC_API_KEY"))
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except ImportError:
                raise RuntimeError(
                    "anthropic package not installed. "
                    "Run: pip install pigeon-imessage[anthropic]"
                )
        return self._client

    def chat(self, prompt: str, model: str | None = None,
             resume_session: str | None = None) -> LLMResponse:
        client = self._get_client()
        model = model or DEFAULT_MODEL

        log.info("Anthropic API (%s): %s", model, prompt[:100])

        try:
            response = client.messages.create(
                model=model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

            return LLMResponse(
                text=text.strip() or "[no response]",
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
        except Exception as e:
            log.error("Anthropic API error: %s", e)
            return LLMResponse(text="[LLM error — check logs]")
