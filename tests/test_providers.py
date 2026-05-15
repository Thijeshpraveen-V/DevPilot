"""
tests/test_providers.py
────────────────────────
Phase 2 E2E tests for the provider layer.

All tests are fully mocked — no real API key or network call needed.
We verify:
  1. AnthropicProvider parses text responses correctly
  2. AnthropicProvider parses tool_use responses correctly
  3. AnthropicProvider builds correct tool_result/user messages
  4. OpenAIProvider parses text responses correctly
  5. OpenAIProvider parses tool_use responses correctly
  6. OpenAIProvider converts canonical messages → OpenAI format correctly
  7. OpenAIProvider converts canonical tool schemas → OpenAI format correctly
  8. Factory creates the right provider type
  9. ConfigError is raised when API key is missing
"""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import Config, ConfigError
from agent.providers.base import ProviderResponse, ToolUseBlock
from agent.providers.factory import create_provider
from agent.providers.openai_provider import OpenAIProvider


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(provider: str = "anthropic", api_key: str = "sk-test") -> Config:
    """Return a minimal Config with the given provider and a fake API key."""
    env_key = "ANTHROPIC_API_KEY" if provider == "anthropic" else "OPENAI_API_KEY"
    os.environ[env_key] = api_key
    os.environ["DEVPILOT_PROVIDER"] = provider
    return Config.load()


def _remove_test_keys():
    for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEVPILOT_PROVIDER"):
        os.environ.pop(k, None)


# ── Mock Anthropic response builders ─────────────────────────────────────────

def _anthropic_text_response(text: str) -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "end_turn"
    return resp


def _anthropic_tool_response(tool_id: str, tool_name: str, tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.id = tool_id
    block.name = tool_name
    block.input = tool_input
    resp = MagicMock()
    resp.content = [block]
    resp.stop_reason = "tool_use"
    return resp


def _anthropic_mixed_response(text: str, tool_id: str, tool_name: str, tool_input: dict) -> MagicMock:
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text
    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.id = tool_id
    tool_block.name = tool_name
    tool_block.input = tool_input
    resp = MagicMock()
    resp.content = [text_block, tool_block]
    resp.stop_reason = "tool_use"
    return resp


# ── Mock OpenAI response builders ─────────────────────────────────────────────

def _openai_text_response(text: str) -> MagicMock:
    msg = MagicMock()
    msg.content = text
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _openai_tool_response(tool_id: str, tool_name: str, tool_input: dict) -> MagicMock:
    func = MagicMock()
    func.name = tool_name
    func.arguments = json.dumps(tool_input)
    tc = MagicMock()
    tc.id = tool_id
    tc.function = func
    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = "tool_calls"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# ═══════════════════════════════════════════════════════════════════════════════
# ANTHROPIC PROVIDER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestAnthropicProviderTextResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        _remove_test_keys()
        self.cfg = _make_config("anthropic")
        yield
        _remove_test_keys()

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    async def test_text_response_sets_text(self, mock_cls):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_anthropic_text_response("Hello from Claude!")
        )
        mock_cls.return_value = mock_client

        from agent.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(self.cfg)
        result = await provider.chat([{"role": "user", "content": "Hi"}], [])

        assert isinstance(result, ProviderResponse)
        assert result.text == "Hello from Claude!"
        assert result.tool_uses == []
        assert result.stop_reason == "end_turn"
        assert not result.has_tool_uses

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    async def test_text_response_assistant_message_shape(self, mock_cls):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_anthropic_text_response("Got it.")
        )
        mock_cls.return_value = mock_client

        from agent.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(self.cfg)
        result = await provider.chat([{"role": "user", "content": "Hi"}], [])

        assert result.assistant_message["role"] == "assistant"
        content = result.assistant_message["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Got it."


class TestAnthropicProviderToolResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        _remove_test_keys()
        self.cfg = _make_config("anthropic")
        yield
        _remove_test_keys()

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    async def test_tool_use_parsed_correctly(self, mock_cls):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_anthropic_tool_response(
                "toolu_01", "read_file", {"path": "main.py"}
            )
        )
        mock_cls.return_value = mock_client

        from agent.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(self.cfg)
        result = await provider.chat([{"role": "user", "content": "Read main.py"}], [])

        assert result.has_tool_uses
        assert len(result.tool_uses) == 1
        tu = result.tool_uses[0]
        assert isinstance(tu, ToolUseBlock)
        assert tu.id == "toolu_01"
        assert tu.name == "read_file"
        assert tu.input == {"path": "main.py"}
        assert result.stop_reason == "tool_use"

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    async def test_mixed_text_and_tool(self, mock_cls):
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(
            return_value=_anthropic_mixed_response(
                "Let me read that file.", "toolu_02", "read_file", {"path": "agent/config.py"}
            )
        )
        mock_cls.return_value = mock_client

        from agent.providers.anthropic_provider import AnthropicProvider
        provider = AnthropicProvider(self.cfg)
        result = await provider.chat([{"role": "user", "content": "Read config.py"}], [])

        assert result.text == "Let me read that file."
        assert result.has_tool_uses
        assert result.tool_uses[0].name == "read_file"


class TestAnthropicProviderMessages:
    @pytest.fixture(autouse=True)
    def setup(self):
        _remove_test_keys()
        self.cfg = _make_config("anthropic")
        yield
        _remove_test_keys()

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    def test_make_user_message(self, mock_cls):
        mock_cls.return_value = MagicMock()
        from agent.providers.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(self.cfg)
        msg = p.make_user_message("Hello")
        assert msg == {"role": "user", "content": "Hello"}

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    def test_make_tool_result_message(self, mock_cls):
        mock_cls.return_value = MagicMock()
        from agent.providers.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(self.cfg)
        msg = p.make_tool_result_message("toolu_01", "file contents here")
        assert msg["role"] == "user"
        block = msg["content"][0]
        assert block["type"] == "tool_result"
        assert block["tool_use_id"] == "toolu_01"
        assert block["content"] == "file contents here"
        assert block["is_error"] is False

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    def test_make_tool_result_message_error(self, mock_cls):
        mock_cls.return_value = MagicMock()
        from agent.providers.anthropic_provider import AnthropicProvider
        p = AnthropicProvider(self.cfg)
        msg = p.make_tool_result_message("toolu_99", "Permission denied", is_error=True)
        assert msg["content"][0]["is_error"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# OPENAI PROVIDER TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestOpenAIProviderTextResponse:
    @pytest.fixture(autouse=True)
    def setup(self):
        _remove_test_keys()
        self.cfg = _make_config("openai")
        yield
        _remove_test_keys()

    @patch("agent.providers.openai_provider.AsyncOpenAI")
    async def test_text_response_parsed(self, mock_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_openai_text_response("Hello from GPT!")
        )
        mock_cls.return_value = mock_client

        from agent.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider(self.cfg)
        result = await provider.chat([{"role": "user", "content": "Hi"}], [])

        assert result.text == "Hello from GPT!"
        assert result.tool_uses == []
        assert result.stop_reason == "end_turn"
        assert not result.has_tool_uses

    @patch("agent.providers.openai_provider.AsyncOpenAI")
    async def test_tool_use_parsed(self, mock_cls):
        mock_client = MagicMock()
        mock_client.chat.completions.create = AsyncMock(
            return_value=_openai_tool_response("call_01", "list_files", {"path": "."})
        )
        mock_cls.return_value = mock_client

        from agent.providers.openai_provider import OpenAIProvider
        provider = OpenAIProvider(self.cfg)
        result = await provider.chat([{"role": "user", "content": "List files"}], [])

        assert result.has_tool_uses
        tu = result.tool_uses[0]
        assert tu.id == "call_01"
        assert tu.name == "list_files"
        assert tu.input == {"path": "."}
        assert result.stop_reason == "tool_use"


class TestOpenAIMessageConversion:
    """Test the internal canonical → OpenAI format conversion."""

    def test_simple_user_message(self):
        msgs = [{"role": "user", "content": "Hello"}]
        result = OpenAIProvider._to_openai_messages(msgs)
        assert result == [{"role": "user", "content": "Hello"}]

    def test_assistant_text_message(self):
        msgs = [{"role": "assistant", "content": [{"type": "text", "text": "Hi there"}]}]
        result = OpenAIProvider._to_openai_messages(msgs)
        assert result[0]["role"] == "assistant"
        assert result[0]["content"] == "Hi there"
        assert "tool_calls" not in result[0]

    def test_assistant_tool_use_message(self):
        msgs = [
            {
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "c1", "name": "read_file", "input": {"path": "x.py"}},
                ],
            }
        ]
        result = OpenAIProvider._to_openai_messages(msgs)
        assert result[0]["tool_calls"][0]["id"] == "c1"
        assert result[0]["tool_calls"][0]["function"]["name"] == "read_file"
        assert json.loads(result[0]["tool_calls"][0]["function"]["arguments"]) == {"path": "x.py"}

    def test_tool_result_becomes_tool_role(self):
        msgs = [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "c1", "content": "file content", "is_error": False}
                ],
            }
        ]
        result = OpenAIProvider._to_openai_messages(msgs)
        assert result[0]["role"] == "tool"
        assert result[0]["tool_call_id"] == "c1"
        assert result[0]["content"] == "file content"

    def test_tool_schema_conversion(self):
        canonical = [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            }
        ]
        result = OpenAIProvider._to_openai_tools(canonical)
        assert result[0]["type"] == "function"
        fn = result[0]["function"]
        assert fn["name"] == "read_file"
        assert fn["description"] == "Read a file"
        assert fn["parameters"]["properties"]["path"]["type"] == "string"


# ═══════════════════════════════════════════════════════════════════════════════
# FACTORY TESTS
# ═══════════════════════════════════════════════════════════════════════════════

class TestProviderFactory:
    @pytest.fixture(autouse=True)
    def setup(self):
        _remove_test_keys()
        yield
        _remove_test_keys()

    @patch("agent.providers.anthropic_provider.anthropic.AsyncAnthropic")
    def test_factory_creates_anthropic(self, mock_cls):
        mock_cls.return_value = MagicMock()
        cfg = _make_config("anthropic")
        from agent.providers.anthropic_provider import AnthropicProvider
        provider = create_provider(cfg)
        assert isinstance(provider, AnthropicProvider)

    @patch("agent.providers.openai_provider.AsyncOpenAI")
    def test_factory_creates_openai(self, mock_cls):
        mock_cls.return_value = MagicMock()
        cfg = _make_config("openai")
        from agent.providers.openai_provider import OpenAIProvider
        provider = create_provider(cfg)
        assert isinstance(provider, OpenAIProvider)

    def test_missing_api_key_raises_config_error(self):
        _remove_test_keys()
        os.environ["DEVPILOT_PROVIDER"] = "anthropic"
        cfg = Config.load()
        with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
            create_provider(cfg)
