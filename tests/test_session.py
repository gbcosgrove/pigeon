"""Tests for session management logic."""

from pigeon.config import PigeonConfig


def test_session_emojis_default():
    config = PigeonConfig()
    assert len(config.session_emojis) == 5
    # Each emoji should be unique
    assert len(set(config.session_emojis)) == 5


def test_max_sessions_validation():
    config = PigeonConfig(chat_ids=[1], max_sessions=0)
    errors = config.validate()
    assert any("max_sessions" in e for e in errors)

    config = PigeonConfig(chat_ids=[1], max_sessions=11)
    errors = config.validate()
    assert any("max_sessions" in e for e in errors)

    config = PigeonConfig(chat_ids=[1], max_sessions=5)
    errors = config.validate()
    assert not any("max_sessions" in e for e in errors)


def test_truncation_limit_validation():
    config = PigeonConfig(chat_ids=[1], truncation_limit=100)
    errors = config.validate()
    assert any("truncation_limit" in e for e in errors)

    config = PigeonConfig(chat_ids=[1], truncation_limit=500)
    errors = config.validate()
    assert not any("truncation_limit" in e for e in errors)
