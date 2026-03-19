"""Cheap-model triage for first-pass message classification."""

import logging

from pigeon.llm.base import LLMBackend

log = logging.getLogger("pigeon")

TRIAGE_PROMPT = (  # noqa: E501
    "You are a fast triage assistant. Classify this message:\n\n"
    "1. If you can answer from your own knowledge in 1-3 sentences, do so directly.\n"
    "2. If it requires checking calendars, files, tasks, databases, tools, "
    "or anything external: respond ONLY with CHECKING\n"
    "3. If it's a long-running task (build something, write docs, research, "
    "modify files): respond ONLY with TASK\n\n"
    "Question: "
)

TOPIC_PROMPT = (
    "Generate a 2-3 word topic label for this message. "
    "Reply with ONLY the label, nothing else.\n"
    'Examples: "Weather Check", "Build Website", "Calendar Query", "Python Help"\n'
    "Message: "
)


class TriageResult:
    INSTANT = "instant"  # Triage model answered directly
    CHECKING = "checking"  # Needs external tools
    TASK = "task"  # Long-running task


def triage_message(prompt: str, backend: LLMBackend,
                   model: str | None = None) -> tuple[str, str]:
    """Classify a message using the triage model.

    Returns (category, response_text).
    - If INSTANT: response_text is the direct answer
    - If CHECKING/TASK: response_text is empty
    """
    response = backend.chat(TRIAGE_PROMPT + prompt, model=model)
    text = response.text.strip()
    upper = text.upper()

    if upper in ("TASK", "CHECKING") or text.startswith("[error:"):
        category = TriageResult.TASK if upper == "TASK" else TriageResult.CHECKING
        return category, ""

    return TriageResult.INSTANT, text


def generate_topic_label(prompt: str, backend: LLMBackend,
                         model: str | None = None) -> str:
    """Generate a short topic label for a message."""
    try:
        response = backend.chat(TOPIC_PROMPT + prompt[:200], model=model)
        label = response.text.strip().strip('"').strip("'")[:25]
        if label and not label.startswith("[error:"):
            return label
    except Exception:
        pass
    return ""
