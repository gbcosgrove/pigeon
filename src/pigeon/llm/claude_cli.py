"""Claude CLI backend — shells out to the `claude` command."""

import json
import logging
import os
import subprocess
import threading
import time

from pigeon.llm.base import LLMBackend, LLMResponse

log = logging.getLogger("pigeon")

# Default: kill process if no output for 10 minutes
DEFAULT_STALE_TIMEOUT = 600


class ClaudeCLIBackend(LLMBackend):
    """Uses the Claude Code CLI (`claude -p`) for inference.

    Requires Claude Code to be installed. No API key needed.
    Supports session resume for multi-turn conversations.

    Uses Popen instead of subprocess.run so that long-running Claude
    sessions complete naturally. A stale-output watchdog kills processes
    that produce no output for `stale_timeout` seconds (default 10 min).
    """

    def __init__(
        self, working_directory: str | None = None, stale_timeout: int | None = None, **kwargs
    ):
        self._working_dir = working_directory or str(os.path.expanduser("~"))
        self._stale_timeout = stale_timeout or DEFAULT_STALE_TIMEOUT

    @property
    def name(self) -> str:
        return "claude-cli"

    @property
    def available(self) -> bool:
        for d in os.environ.get("PATH", "").split(":"):
            if os.path.isfile(os.path.join(d, "claude")):
                return True
        return False

    def chat(
        self, prompt: str, model: str | None = None, resume_session: str | None = None
    ) -> LLMResponse:
        cmd = ["claude", "-p", prompt, "--output-format", "json"]
        if model:
            cmd.extend(["--model", model])
        if resume_session:
            cmd.extend(["--resume", resume_session])

        label = model or "default"
        if resume_session:
            label += f" resume={resume_session[:8]}"
        log.info("Claude CLI (%s): %s", label, prompt[:100])

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self._working_dir,
            )
        except FileNotFoundError:
            return LLMResponse(text="[error: claude CLI not found in PATH]")

        # Collect stdout/stderr in threads so pipe buffers don't deadlock
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        last_activity = time.monotonic()
        activity_lock = threading.Lock()

        def _read_stream(stream, chunks):
            nonlocal last_activity
            for line in stream:
                chunks.append(line)
                with activity_lock:
                    last_activity = time.monotonic()

        stdout_thread = threading.Thread(
            target=_read_stream, args=(proc.stdout, stdout_chunks), daemon=True
        )
        stderr_thread = threading.Thread(
            target=_read_stream, args=(proc.stderr, stderr_chunks), daemon=True
        )
        stdout_thread.start()
        stderr_thread.start()

        # Wait for process, checking for staleness periodically
        while proc.poll() is None:
            time.sleep(2)
            with activity_lock:
                idle = time.monotonic() - last_activity
            if idle > self._stale_timeout:
                log.warning(
                    "Claude CLI stale (no output for %ds), killing: %s", int(idle), prompt[:60]
                )
                proc.kill()
                proc.wait()
                return LLMResponse(text=f"[error: no output for {int(idle)}s — process killed]")

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

        stdout = "".join(stdout_chunks)
        stderr = "".join(stderr_chunks)

        if proc.returncode != 0:
            log.error("Claude CLI error (rc=%d): %s", proc.returncode, (stderr or "")[:500])
            return LLMResponse(text="[LLM error — check logs]")

        if not stdout or not stdout.strip():
            return LLMResponse(text="[no response]")

        try:
            resp = json.loads(stdout)
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
            return LLMResponse(text=stdout.strip())
