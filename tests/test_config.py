"""
tests/test_config.py
─────────────────────
Phase 1 E2E tests for agent/config.py

These tests verify that:
- Config loads with default values when no env vars are set
- Custom env vars are correctly read
- Invalid values raise ConfigError with a helpful message
- validate_api_key() raises clearly when key is missing
- validate_api_key() passes when key is present
"""

import os
import pytest

from agent.config import Config, ConfigError


# ── Helper ─────────────────────────────────────────────────────────────────

def _env(**overrides):
    """Return a dict that clears DevPilot env vars then applies overrides."""
    keys_to_clear = [
        "DEVPILOT_PROVIDER", "DEVPILOT_MODEL", "DEVPILOT_BASE_URL",
        "DEVPILOT_MAX_ITERATIONS", "DEVPILOT_NO_CONFIRM",
        "DEVPILOT_A2A_PORT", "DEVPILOT_A2A_TOKEN", "DEVPILOT_SESSIONS_DIR",
        "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    ]
    cleared = {k: None for k in keys_to_clear}   # monkeypatch removes None keys
    cleared.update(overrides)
    return cleared


# ── Tests ───────────────────────────────────────────────────────────────────

class TestConfigDefaults:
    def test_default_provider_is_anthropic(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.provider == "anthropic"

    def test_default_model_for_anthropic(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert "claude" in cfg.model

    def test_default_max_iterations(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.max_iterations == 50

    def test_default_no_confirm_is_false(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.no_confirm is False

    def test_default_a2a_port(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.a2a_port == 8000

    def test_base_url_is_none_by_default(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.base_url is None


class TestConfigCustomValues:
    def test_provider_openai(self, monkeypatch):
        for k, v in _env(DEVPILOT_PROVIDER="openai").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.provider == "openai"
        assert "gpt" in cfg.model

    def test_custom_model(self, monkeypatch):
        for k, v in _env(DEVPILOT_MODEL="claude-haiku-4-5").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.model == "claude-haiku-4-5"

    def test_no_confirm_true(self, monkeypatch):
        for k, v in _env(DEVPILOT_NO_CONFIRM="true").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.no_confirm is True

    def test_custom_max_iterations(self, monkeypatch):
        for k, v in _env(DEVPILOT_MAX_ITERATIONS="25").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.max_iterations == 25

    def test_custom_base_url(self, monkeypatch):
        for k, v in _env(DEVPILOT_BASE_URL="http://localhost:11434/v1").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.base_url == "http://localhost:11434/v1"


class TestConfigValidation:
    def test_invalid_provider_raises(self, monkeypatch):
        for k, v in _env(DEVPILOT_PROVIDER="gemini").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        with pytest.raises(ConfigError, match="DEVPILOT_PROVIDER"):
            Config.load()

    def test_invalid_max_iterations_raises(self, monkeypatch):
        for k, v in _env(DEVPILOT_MAX_ITERATIONS="zero").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        with pytest.raises(ConfigError, match="DEVPILOT_MAX_ITERATIONS"):
            Config.load()

    def test_zero_max_iterations_raises(self, monkeypatch):
        for k, v in _env(DEVPILOT_MAX_ITERATIONS="0").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        with pytest.raises(ConfigError):
            Config.load()


class TestApiKeyValidation:
    def test_missing_key_raises_config_error(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.active_api_key is None
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            cfg.validate_api_key()

    def test_present_key_passes_validation(self, monkeypatch):
        for k, v in _env(ANTHROPIC_API_KEY="sk-ant-test-key").items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        assert cfg.active_api_key == "sk-ant-test-key"
        cfg.validate_api_key()   # should NOT raise

    def test_str_repr_shows_key_status(self, monkeypatch):
        for k, v in _env().items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        cfg = Config.load()
        output = str(cfg)
        assert "MISSING" in output
        assert "provider" in output
