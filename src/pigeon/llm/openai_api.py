"""OpenAI API backend — works with OpenAI, Azure, or any compatible endpoint."""

import logging
import os

from pigeon.llm.base import LLMBackend, LLMResponse

log = logging.getLogger("pigeon")

DEFAULT_MODEL = "gpt-4o"


class OpenAIBackend(LLMBackend):
    """Uses the OpenAI Python SDK for inference.

    Requires: pip install pigeon-imessage[openai]
    Set OPENAI_API_KEY environment variable.
    Optionally set OPENAI_BASE_URL for compatible endpoints (Azure, local, etc).
    """

    def __init__(self, **kwargs):
        self._client = None

    @property
    def name(self) -> str:
        return "openai"

    @property
    def available(self) -> bool:
        try:
            import openai  # noqa: F401
            return bool(os.environ.get("OPENAI_API_KEY"))
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            try:
                import openai
                kwargs = {}
                base_url = os.environ.get("OPENAI_BASE_URL")
                if base_url:
                    kwargs["base_url"] = base_url
                self._client = openai.OpenAI(**kwargs)
            except ImportError:
                raise RuntimeError(
                    "openai package not installed. "
                    "Run: pip install pigeon-imessage[openai]"
                )
        return self._client

    def chat(self, prompt: str, model: str | None = None,
             resume_session: str | None = None) -> LLMResponse:
        client = self._get_client()
        model = model or DEFAULT_MODEL

        log.info("OpenAI API (%s): %s", model, prompt[:100])

        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
            )

            text = response.choices[0].message.content or ""
            usage = response.usage

            return LLMResponse(
                text=text.strip() or "[no response]",
                model=response.model,
                input_tokens=usage.prompt_tokens if usage else None,
                output_tokens=usage.completion_tokens if usage else None,
            )
        except Exception as e:
            log.error("OpenAI API error: %s", e)
            return LLMResponse(text="[LLM error — check logs]")
