"""Tests for triage classification."""

from unittest.mock import MagicMock

from pigeon.llm.base import LLMResponse
from pigeon.triage import TriageResult, generate_topic_label, triage_message


def test_triage_instant_answer():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="The capital of France is Paris.")
    category, text = triage_message("What's the capital of France?", backend)
    assert category == TriageResult.INSTANT
    assert "Paris" in text


def test_triage_checking():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="CHECKING")
    category, text = triage_message("What's on my calendar today?", backend)
    assert category == TriageResult.CHECKING
    assert text == ""


def test_triage_task():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="TASK")
    category, text = triage_message("Build me a website", backend)
    assert category == TriageResult.TASK
    assert text == ""


def test_triage_error_treated_as_checking():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="[error: timeout]")
    category, text = triage_message("anything", backend)
    assert category == TriageResult.CHECKING


def test_generate_topic_label():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="Weather Check")
    label = generate_topic_label("What's the weather today?", backend)
    assert label == "Weather Check"


def test_generate_topic_label_strips_quotes():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text='"Build Website"')
    label = generate_topic_label("Build me a website", backend)
    assert label == "Build Website"


def test_generate_topic_label_error():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="[error: failed]")
    label = generate_topic_label("anything", backend)
    assert label == ""


def test_generate_topic_label_truncates():
    backend = MagicMock()
    backend.chat.return_value = LLMResponse(text="A" * 50)
    label = generate_topic_label("test", backend)
    assert len(label) <= 25
