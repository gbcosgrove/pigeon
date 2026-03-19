"""Tests for configuration loading and validation."""

from pigeon.config import DEFAULT_CONFIG, PigeonConfig, _deep_merge, _env_substitute


def test_default_config():
    config = PigeonConfig.from_dict(DEFAULT_CONFIG)
    assert config.trigger_keyword == "pigeon"
    assert config.max_sessions == 0  # 0 = unlimited
    assert config.warn_at_sessions == 10
    assert config.stale_timeout == 600
    assert config.truncation_limit == 2000
    assert config.db_backend == "none"
    assert config.llm_main_backend == "claude-cli"


def test_config_validation_no_chat_ids():
    config = PigeonConfig()
    errors = config.validate()
    assert any("chat IDs" in e for e in errors)


def test_config_validation_bad_backend():
    config = PigeonConfig(chat_ids=[1], llm_main_backend="nonexistent")
    errors = config.validate()
    assert any("Unknown main LLM backend" in e for e in errors)


def test_config_validation_valid():
    config = PigeonConfig(
        chat_ids=[123], llm_main_backend="claude-cli", llm_triage_backend="claude-cli"
    )
    errors = config.validate()
    assert len(errors) == 0


def test_deep_merge():
    base = {"a": 1, "b": {"c": 2, "d": 3}}
    override = {"b": {"c": 99}, "e": 5}
    result = _deep_merge(base, override)
    assert result == {"a": 1, "b": {"c": 99, "d": 3}, "e": 5}


def test_env_substitute(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret123")
    assert _env_substitute("prefix_${TEST_KEY}_suffix") == "prefix_secret123_suffix"
    assert _env_substitute("no_vars_here") == "no_vars_here"
    assert _env_substitute("${MISSING_VAR}") == ""


def test_config_from_dict_custom_values():
    data = {
        "chat": {"ids": [42, 99], "identifier": "test@example.com"},
        "trigger": {
            "keyword": "ai",
            "expand_keyword": "ai:cc",
            "status_keyword": "ai:status",
            "off_keyword": "ai:off",
        },
        "llm": {
            "main": {"backend": "ollama", "model": "llama3"},
            "triage": {"backend": "anthropic", "model": "haiku"},
        },
        "sessions": {"max": 3},
        "response": {"truncation_limit": 1500},
        "database": {"backend": "sqlite"},
        "daemon": {"poll_interval": 10, "icon": "🤖"},
    }
    config = PigeonConfig.from_dict(data)
    assert config.chat_ids == [42, 99]
    assert config.trigger_keyword == "ai"
    assert config.llm_main_backend == "ollama"
    assert config.llm_main_model == "llama3"
    assert config.llm_triage_backend == "anthropic"
    assert config.max_sessions == 3
    assert config.truncation_limit == 1500
    assert config.icon == "🤖"
