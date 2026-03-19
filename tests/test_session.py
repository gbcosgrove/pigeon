"""Tests for session management logic."""

from pigeon.config import PigeonConfig


def test_session_emojis_default():
    config = PigeonConfig()
    assert len(config.session_emojis) == 20
    # First 5 should be the classic colors
    assert config.session_emojis[0] == "\U0001f534"  # 🔴


def test_max_sessions_validation():
    # 0 = unlimited, should be valid
    config = PigeonConfig(chat_ids=[1], max_sessions=0)
    errors = config.validate()
    assert not any("max_sessions" in e for e in errors)

    # Negative is invalid
    config = PigeonConfig(chat_ids=[1], max_sessions=-1)
    errors = config.validate()
    assert any("max_sessions" in e for e in errors)

    # Positive is valid (no upper cap)
    config = PigeonConfig(chat_ids=[1], max_sessions=50)
    errors = config.validate()
    assert not any("max_sessions" in e for e in errors)


def test_truncation_limit_validation():
    config = PigeonConfig(chat_ids=[1], truncation_limit=100)
    errors = config.validate()
    assert any("truncation_limit" in e for e in errors)

    config = PigeonConfig(chat_ids=[1], truncation_limit=500)
    errors = config.validate()
    assert not any("truncation_limit" in e for e in errors)


def test_stale_timeout_default():
    config = PigeonConfig()
    assert config.stale_timeout == 600


def test_warn_at_sessions_default():
    config = PigeonConfig()
    assert config.warn_at_sessions == 10
