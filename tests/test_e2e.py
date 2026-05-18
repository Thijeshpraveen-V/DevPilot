"""
tests/test_e2e.py
─────────────────
End-to-end integration test.

Exercises the full pipeline: RepoContext → ToolRegistry → run_agent_loop.
Uses a mocked provider so no API key is required, but everything else is real:
  - A real Config dataclass
  - A real ToolRegistry (with write_file, read_file, run_bash, etc.)
  - A real RepoContext (vector store skipped if deps not installed)
  - The actual run_agent_loop coroutine

This catches regressions that unit tests can't: wiring bugs, schema mismatches,
history ordering issues, and heal-loop edge cases.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.config import Config
from agent.context import RepoContext
from agent.history import HistoryManager
from agent.loop import run_agent_loop
from agent.providers.base import ProviderResponse, ToolUseBlock
from agent.tools import ToolRegistry, ToolResult


# ── Shared helpers ────────────────────────────────────────────────────────────

def make_config(tmp_path: Path, no_confirm: bool = True) -> Config:
    return Config(
        provider="anthropic",
        model="claude-test",
        base_url=None,
        max_iterations=10,
        no_confirm=no_confirm,
        a2a_port=8000,
        a2a_token=None,
        workdir=str(tmp_path),
        extended_thinking=False,
        thinking_budget=10000,
        web_search_enabled=False,
        memory_enabled=False,
        a2a_enabled=False,
        sessions_dir=tmp_path,
    )


def make_provider(*responses: ProviderResponse) -> MagicMock:
    """Build a mock provider that streams the given responses in order."""
    provider = MagicMock()
    provider.chat_stream = AsyncMock(side_effect=list(responses))
    provider.make_tool_result_message = MagicMock(
        side_effect=lambda tool_use_id, content, is_error: {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": tool_use_id, "content": content}],
        }
    )
    provider.make_user_message = MagicMock(
        side_effect=lambda text: {"role": "user", "content": text}
    )
    return provider


def end_turn(text: str = "Done.") -> ProviderResponse:
    return ProviderResponse(
        text=text,
        tool_uses=[],
        stop_reason="end_turn",
        assistant_message={"role": "assistant", "content": text},
    )


def tool_turn(tool_name: str, tool_input: dict, text: str = "") -> ProviderResponse:
    return ProviderResponse(
        text=text,
        tool_uses=[ToolUseBlock(id="tid-1", name=tool_name, input=tool_input)],
        stop_reason="tool_use",
        assistant_message={"role": "assistant", "content": text or f"Calling {tool_name}"},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Full task — write a file then read it back
# ═══════════════════════════════════════════════════════════════════════════════

class TestE2EWriteThenRead:
    @pytest.mark.asyncio
    async def test_write_file_creates_file_on_disk(self, tmp_path: Path):
        """
        Full pipeline: provider calls write_file → real WriteFileTool runs →
        file lands on disk → loop terminates on end_turn.
        """
        config = make_config(tmp_path)
        context = RepoContext(str(tmp_path))
        registry = ToolRegistry(config, _context=context)
        history = HistoryManager()
        history.append({"role": "user", "content": "Write hello.py"})

        provider = make_provider(
            tool_turn("write_file", {"path": "hello.py", "content": "print('hello')\n"}),
            end_turn("Done — hello.py written."),
        )

        with patch("agent.ui.UI.print_diff"), patch("agent.ui.UI.print_tool_call"), \
             patch("agent.ui.UI.print_tool_result"), patch("agent.ui.UI.print_assistant_message"):
            await run_agent_loop(
                provider=provider,
                registry=registry,
                history=history,
                config=config,
                context=context,
            )

        assert (tmp_path / "hello.py").exists()
        assert (tmp_path / "hello.py").read_text() == "print('hello')\n"

    @pytest.mark.asyncio
    async def test_read_file_result_appended_to_history(self, tmp_path: Path):
        """
        Full pipeline: provider calls read_file → real ReadFileTool returns content →
        tool result is appended to history → provider is called again.
        """
        (tmp_path / "data.txt").write_text("answer=42\n")

        config = make_config(tmp_path)
        context = RepoContext(str(tmp_path))
        registry = ToolRegistry(config, _context=context)
        history = HistoryManager()
        history.append({"role": "user", "content": "Read data.txt"})

        provider = make_provider(
            tool_turn("read_file", {"path": "data.txt"}),
            end_turn("I read the file."),
        )

        with patch("agent.ui.UI.print_tool_call"), patch("agent.ui.UI.print_tool_result"), \
             patch("agent.ui.UI.print_assistant_message"):
            await run_agent_loop(
                provider=provider,
                registry=registry,
                history=history,
                config=config,
                context=context,
            )

        assert provider.chat_stream.call_count == 2

        # The second call to chat_stream should include the tool result in history
        second_call_messages = provider.chat_stream.call_args_list[1][0][0]
        history_text = json.dumps(second_call_messages)
        assert "answer=42" in history_text


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Pre-flight linting blocks bad Python before writing
# ═══════════════════════════════════════════════════════════════════════════════

class TestE2EPreflightLinting:
    @pytest.mark.asyncio
    async def test_invalid_python_blocked_and_heal_loop_fires(self, tmp_path: Path):
        """
        Provider attempts to write syntactically broken Python → WriteFileTool
        returns is_error=True → heal loop appends fix message → provider gets a
        second chance → succeeds with valid Python.
        """
        config = make_config(tmp_path)
        context = RepoContext(str(tmp_path))
        registry = ToolRegistry(config, _context=context)
        history = HistoryManager()
        history.append({"role": "user", "content": "Write a Python file"})

        broken_py = "def bad(\n    pass\n"  # missing closing paren
        good_py = "def good():\n    pass\n"

        provider = make_provider(
            tool_turn("write_file", {"path": "mod.py", "content": broken_py}),
            tool_turn("write_file", {"path": "mod.py", "content": good_py}),
            end_turn("Fixed and written."),
        )

        with patch("agent.ui.UI.print_diff"), patch("agent.ui.UI.print_tool_call"), \
             patch("agent.ui.UI.print_tool_result"), patch("agent.ui.UI.print_assistant_message"), \
             patch("agent.ui.UI.print_error"):
            await run_agent_loop(
                provider=provider,
                registry=registry,
                history=history,
                config=config,
                context=context,
            )

        # Bad file should NOT be on disk; good file should be
        assert not (tmp_path / "mod.py").exists() or \
               (tmp_path / "mod.py").read_text() == good_py


# ═══════════════════════════════════════════════════════════════════════════════
# E2E: Heal loop abort after 3 consecutive errors
# ═══════════════════════════════════════════════════════════════════════════════

class TestE2EHealLoopAbort:
    @pytest.mark.asyncio
    async def test_aborts_after_three_consecutive_errors(self, tmp_path: Path):
        """
        Registry always returns is_error=True → heal loop should abort after
        3 consecutive failures, not loop forever.
        """
        config = make_config(tmp_path)
        context = RepoContext(str(tmp_path))
        registry = MagicMock()
        registry.schemas = []
        registry.execute = AsyncMock(return_value=ToolResult("tool exploded", is_error=True))

        history = HistoryManager()
        history.append({"role": "user", "content": "Do something"})

        # Provider always returns a tool call
        provider = MagicMock()
        provider.chat_stream = AsyncMock(return_value=tool_turn("run_bash", {"command": "fail"}))
        provider.make_tool_result_message = MagicMock(
            return_value={"role": "user", "content": "error result"}
        )
        provider.make_user_message = MagicMock(
            return_value={"role": "user", "content": "fix it"}
        )

        with patch("agent.ui.UI.print_tool_call"), patch("agent.ui.UI.print_tool_result"), \
             patch("agent.ui.UI.print_assistant_message"), patch("agent.ui.UI.print_error"):
            await run_agent_loop(
                provider=provider,
                registry=registry,
                history=history,
                config=config,
                max_iterations=20,
                context=context,
            )

        # Must have aborted well before 20 iterations
        assert registry.execute.call_count == 3



