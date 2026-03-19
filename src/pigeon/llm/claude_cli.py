"""Claude CLI backend — shells out to the `claude` command."""

import json
import logging
import os
import subprocess

from pigeon.llm.base import LLMBackend, LLMResponse

log = logging.getLogger("pigeon")


class ClaudeCLIBackend(LLMBackend):
    """Uses the Claude Code CLI (`claude -p`) for inference.

    Requires Claude Code to be installed. No API key needed.
    Supports session resume for multi-turn conversations.
    """

    def __init__(self, working_directory: str | None = None, **kwargs):
        self._working_dir = working_directory or str(os.path.expanduser("~"))

    @property
    def name(self) -> str:
        return "claude-cli"

    @property
    def available(self) -> bool:
        for d in os.environ.get("PATH", "").split(":"):
            if os.path.isfile(os.path.join(d, "claude")):
                return True
        return False

    def chat(self, prompt: str, model: str | None = None,
             resume_session: str | None = None) -> LLMResponse:
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if model:
            cmd.extend(["--model", model])
        if resume_session:
            cmd.extend(["--resume", resume_session])

        label = model or "default"
        log.info("Claude CLI (%s): %s", label, prompt[:100])

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                cwd=self._working_dir, timeout=300,
            )
            if result.returncode != 0:
                log.error("Claude CLI error (rc=%d): %s",
                          result.returncode, (result.stderr or "")[:500])
                return LLMResponse(text="[LLM error — check logs]")

            if not result.stdout or not result.stdout.strip():
                return LLMResponse(text="[no response]")

            try:
                resp = json.loads(result.stdout)
                text = (resp.get("result") or "").strip()
                session_id = resp.get("session_id")
                usage = resp.get("usage", {})

                # Extract model name from modelUsage
                model_usage = resp.get("modelUsage", {})
                model_name = list(model_usage.keys())[0] if model_usage else model or "unknown"
                if "[" in model_name:
                    model_name = model_name.split("[")[0]

                if not text:
                    return LLMResponse(text="[no response]", session_id=session_id)

                return LLMResponse(
                    text=text,
                    model=model_name,
                    input_tokens=usage.get("input_tokens"),
                    output_tokens=usage.get("output_tokens"),
                    session_id=session_id,
                    cost_usd=resp.get("total_cost_usd"),
                )
            except (json.JSONDecodeError, TypeError):
                return LLMResponse(text=result.stdout.strip())

        except FileNotFoundError:
            return LLMResponse(text="[error: claude CLI not found in PATH]")
        except subprocess.TimeoutExpired:
            return LLMResponse(text="[error: timed out]")
