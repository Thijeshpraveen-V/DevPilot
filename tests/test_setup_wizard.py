"""
tests/test_setup_wizard.py
──────────────────────────
Unit tests for the first-run setup wizard.

Tests:
  1. _is_interactive() returns False in non-TTY context
  2. run_setup_wizard() returns False and skips in non-TTY context
  3. _write_env_file() writes all required keys correctly
  4. _write_env_file() preserves pre-existing keys
  5. _write_env_file() overwrites an existing key
  6. run_setup_wizard() returns False and writes nothing in CI
  7. DEVPILOT_BASE_URL is written for compatible providers (Groq path)
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from agent.setup_wizard import _write_env_file, run_setup_wizard


# ═══════════════════════════════════════════════════════════════════════════════
# _write_env_file
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteEnvFile:
    def test_creates_env_file_with_correct_keys(self, tmp_path: Path):
        env = tmp_path / ".env"
        _write_env_file(env, {
            "ANTHROPIC_API_KEY": "sk-ant-test",
            "DEVPILOT_PROVIDER": "anthropic",
            "DEVPILOT_MODEL": "claude-opus-4-5-20251101",
        })
        content = env.read_text()
        assert "ANTHROPIC_API_KEY=sk-ant-test" in content
        assert "DEVPILOT_PROVIDER=anthropic" in content
        assert "DEVPILOT_MODEL=claude-opus-4-5-20251101" in content

    def test_preserves_existing_keys(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("EXISTING_KEY=keep_me\nDEVPILOT_MAX_ITERATIONS=30\n")
        _write_env_file(env, {
            "ANTHROPIC_API_KEY": "sk-ant-new",
            "DEVPILOT_PROVIDER": "anthropic",
            "DEVPILOT_MODEL": "claude-haiku-4-5-20251101",
        })
        content = env.read_text()
        assert "EXISTING_KEY=keep_me" in content
        assert "DEVPILOT_MAX_ITERATIONS=30" in content
        assert "ANTHROPIC_API_KEY=sk-ant-new" in content

    def test_overwrites_existing_api_key(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("ANTHROPIC_API_KEY=sk-ant-old\n")
        _write_env_file(env, {"ANTHROPIC_API_KEY": "sk-ant-new"})
        content = env.read_text()
        assert "sk-ant-new" in content
        assert "sk-ant-old" not in content

    def test_creates_file_if_missing(self, tmp_path: Path):
        env = tmp_path / "new.env"
        assert not env.exists()
        _write_env_file(env, {"OPENAI_API_KEY": "sk-test", "DEVPILOT_PROVIDER": "openai", "DEVPILOT_MODEL": "gpt-4o"})
        assert env.exists()
        assert "OPENAI_API_KEY=sk-test" in env.read_text()

    def test_writes_base_url_for_compatible_providers(self, tmp_path: Path):
        """Groq, Together, Mistral etc. all need DEVPILOT_BASE_URL written."""
        env = tmp_path / ".env"
        _write_env_file(env, {
            "GROQ_API_KEY": "gsk_test",
            "OPENAI_API_KEY": "gsk_test",
            "DEVPILOT_PROVIDER": "openai",
            "DEVPILOT_MODEL": "llama-3.3-70b-versatile",
            "DEVPILOT_BASE_URL": "https://api.groq.com/openai/v1",
        })
        content = env.read_text()
        assert "DEVPILOT_BASE_URL=https://api.groq.com/openai/v1" in content
        assert "DEVPILOT_PROVIDER=openai" in content

    def test_writes_ollama_config(self, tmp_path: Path):
        """Ollama uses a placeholder key and localhost base URL."""
        env = tmp_path / ".env"
        _write_env_file(env, {
            "OPENAI_API_KEY": "ollama",
            "DEVPILOT_PROVIDER": "openai",
            "DEVPILOT_MODEL": "qwen2.5-coder:7b",
            "DEVPILOT_BASE_URL": "http://localhost:11434/v1",
        })
        content = env.read_text()
        assert "DEVPILOT_BASE_URL=http://localhost:11434/v1" in content
        assert "OPENAI_API_KEY=ollama" in content


# ═══════════════════════════════════════════════════════════════════════════════
# run_setup_wizard — non-TTY / CI
# ═══════════════════════════════════════════════════════════════════════════════

class TestSetupWizardNonInteractive:
    def test_returns_false_in_non_tty(self, tmp_path: Path):
        with patch("agent.setup_wizard._is_interactive", return_value=False):
            result = run_setup_wizard(env_path=tmp_path / ".env")
        assert result is False

    def test_no_env_file_written_when_skipped(self, tmp_path: Path):
        env = tmp_path / ".env"
        with patch("agent.setup_wizard._is_interactive", return_value=False):
            run_setup_wizard(env_path=env)
        assert not env.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# run_setup_wizard — per-provider flow tests
# ═══════════════════════════════════════════════════════════════════════════════

def _run_wizard(env_path: Path, prompt_answers: list[str]) -> bool:
    """
    Run the wizard with mocked prompts. Prompt.ask is called in sequence:
      1. Provider choice (Step 1)
      2. API key (Step 2, password=True)
      3. Model choice (Step 3)
    Returns the wizard result.
    """
    with patch("agent.setup_wizard._is_interactive", return_value=True), \
         patch("agent.setup_wizard.console"), \
         patch("agent.setup_wizard.Prompt.ask", side_effect=prompt_answers):
        return run_setup_wizard(env_path=env_path)


class TestSetupWizardAnthropicFlow:
    def test_anthropic_returns_true(self, tmp_path: Path):
        result = _run_wizard(tmp_path / ".env", ["1", "sk-ant-testkey123", "1"])
        assert result is True

    def test_anthropic_writes_correct_env(self, tmp_path: Path):
        env = tmp_path / ".env"
        _run_wizard(env, ["1", "sk-ant-testkey123", "2"])  # model 2 = sonnet
        content = env.read_text()
        assert "ANTHROPIC_API_KEY=sk-ant-testkey123" in content
        assert "DEVPILOT_PROVIDER=anthropic" in content
        assert "claude-sonnet-4-5-20251101" in content

    def test_anthropic_injects_os_environ(self, tmp_path: Path):
        os.environ.pop("ANTHROPIC_API_KEY", None)
        _run_wizard(tmp_path / ".env", ["1", "sk-ant-envcheck", "1"])
        assert os.environ.get("ANTHROPIC_API_KEY") == "sk-ant-envcheck"
        assert os.environ.get("DEVPILOT_PROVIDER") == "anthropic"

    def test_anthropic_bad_key_prefix_still_saves(self, tmp_path: Path):
        """Key without sk-ant- prefix should save with a warning, not abort."""
        env = tmp_path / ".env"
        result = _run_wizard(env, ["1", "bad-prefix-key", "1"])
        assert result is True
        assert "bad-prefix-key" in env.read_text()

    def test_anthropic_empty_key_returns_false(self, tmp_path: Path):
        """Empty key should abort the wizard gracefully."""
        result = _run_wizard(tmp_path / ".env", ["1", "", "1"])
        assert result is False


class TestSetupWizardOpenAIFlow:
    def test_openai_returns_true(self, tmp_path: Path):
        result = _run_wizard(tmp_path / ".env", ["2", "sk-oai-testkey", "1"])
        assert result is True

    def test_openai_writes_correct_env(self, tmp_path: Path):
        env = tmp_path / ".env"
        _run_wizard(env, ["2", "sk-oai-testkey", "2"])  # model 2 = gpt-4o-mini
        content = env.read_text()
        assert "OPENAI_API_KEY=sk-oai-testkey" in content
        assert "DEVPILOT_PROVIDER=openai" in content
        assert "gpt-4o-mini" in content
        # OpenAI native has no base URL
        assert "DEVPILOT_BASE_URL" not in content

    def test_openai_custom_model_option(self, tmp_path: Path):
        """Selecting 'Other' (last option) should prompt for a custom model name."""
        env = tmp_path / ".env"
        # choices=[1,2,3,4,5] — option 5 is "Other", then custom name
        _run_wizard(env, ["2", "sk-oai-testkey", "5", "my-custom-model"])
        assert "my-custom-model" in env.read_text()


class TestSetupWizardGroqFlow:
    def test_groq_returns_true(self, tmp_path: Path):
        result = _run_wizard(tmp_path / ".env", ["3", "gsk_testkey", "1"])
        assert result is True

    def test_groq_writes_base_url(self, tmp_path: Path):
        env = tmp_path / ".env"
        _run_wizard(env, ["3", "gsk_testkey", "1"])
        content = env.read_text()
        assert "DEVPILOT_BASE_URL=https://api.groq.com/openai/v1" in content
        assert "DEVPILOT_PROVIDER=openai" in content
        assert "llama-3.3-70b-versatile" in content

    def test_groq_key_aliased_to_openai_key(self, tmp_path: Path):
        """OPENAI_API_KEY must be written so OpenAIProvider can find it."""
        env = tmp_path / ".env"
        _run_wizard(env, ["3", "gsk_mykey", "1"])
        content = env.read_text()
        assert "OPENAI_API_KEY=gsk_mykey" in content
        assert "GROQ_API_KEY=gsk_mykey" in content


class TestSetupWizardOllamaFlow:
    def test_ollama_returns_true(self, tmp_path: Path):
        # Ollama is choice 6 — no key prompt, just model choice
        result = _run_wizard(tmp_path / ".env", ["6", "1"])
        assert result is True

    def test_ollama_uses_localhost_base_url(self, tmp_path: Path):
        env = tmp_path / ".env"
        _run_wizard(env, ["6", "1"])
        content = env.read_text()
        assert "DEVPILOT_BASE_URL=http://localhost:11434/v1" in content
        assert "DEVPILOT_PROVIDER=openai" in content

    def test_ollama_uses_placeholder_api_key(self, tmp_path: Path):
        """Ollama doesn't need a real API key — wizard writes 'ollama' as placeholder."""
        env = tmp_path / ".env"
        _run_wizard(env, ["6", "1"])
        assert "OPENAI_API_KEY=ollama" in env.read_text()


class TestSetupWizardCustomFlow:
    def test_custom_endpoint_returns_true(self, tmp_path: Path):
        # Choice 7 → base_url, api_key, model_name prompts
        result = _run_wizard(
            tmp_path / ".env",
            ["7", "https://my.llm.com/v1", "my-secret", "my-model"]
        )
        assert result is True

    def test_custom_endpoint_writes_all_fields(self, tmp_path: Path):
        env = tmp_path / ".env"
        _run_wizard(env, ["7", "https://my.llm.com/v1", "my-secret", "my-model"])
        content = env.read_text()
        assert "DEVPILOT_BASE_URL=https://my.llm.com/v1" in content
        assert "OPENAI_API_KEY=my-secret" in content
        assert "DEVPILOT_MODEL=my-model" in content
        assert "DEVPILOT_PROVIDER=openai" in content

    def test_custom_endpoint_missing_base_url_returns_false(self, tmp_path: Path):
        """Missing base_url should abort the wizard."""
        result = _run_wizard(tmp_path / ".env", ["7", "", "my-secret", "my-model"])
        assert result is False

