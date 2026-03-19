"""Ollama backend — local models via HTTP API."""

import json
import logging
import os
import urllib.request

from pigeon.llm.base import LLMBackend, LLMResponse

log = logging.getLogger("pigeon")

DEFAULT_MODEL = "llama3.2"
DEFAULT_HOST = "http://localhost:11434"


class OllamaBackend(LLMBackend):
    """Uses Ollama's local HTTP API for inference.

    Requires Ollama to be running locally. No API key needed.
    Set OLLAMA_HOST to override the default (http://localhost:11434).
    """

    def __init__(self, **kwargs):
        self._host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST).rstrip("/")

    @property
    def name(self) -> str:
        return "ollama"

    @property
    def available(self) -> bool:
        try:
            req = urllib.request.Request(f"{self._host}/api/tags", method="GET")
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            return False

    def chat(self, prompt: str, model: str | None = None,
             resume_session: str | None = None) -> LLMResponse:
        model = model or DEFAULT_MODEL

        log.info("Ollama (%s): %s", model, prompt[:100])

        try:
            url = f"{self._host}/api/chat"
            body = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }).encode()
            req = urllib.request.Request(
                url, data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=300)
            data = json.loads(resp.read())

            text = data.get("message", {}).get("content", "")
            eval_count = data.get("eval_count")
            prompt_eval_count = data.get("prompt_eval_count")

            return LLMResponse(
                text=text.strip() or "[no response]",
                model=model,
                input_tokens=prompt_eval_count,
                output_tokens=eval_count,
            )
        except Exception as e:
            log.error("Ollama error: %s", e)
            return LLMResponse(text="[LLM error — check logs]")
