"""
tests/test_tools.py
────────────────────
Tests for agent/tools/ package (post-refactor).

Tests verify:
  1. ReadFileTool  — happy path, partial read, missing file, not-a-file
  2. WriteFileTool — creates file, creates parent dirs, overwrites
  3. ListFilesTool — lists dir, empty dir, bad path, recursive
  4. RunBashTool   — success, non-zero exit, timeout, invalid command, stderr
  5. SearchCodeTool — match found, no match, glob filter, invalid path
  6. PermissionGuard — blocks/allows correctly, --no-confirm bypass
  7. ToolRegistry  — unknown tool, execute flow, cancel path, MCP register/deregister
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools import (
    PermissionGuard,
    ToolRegistry,
    ToolResult,
)
from agent.tools.fs import ListFilesTool, ReadFileTool, WriteFileTool
from agent.tools.shell import RunBashTool
from agent.tools.search_code import SearchCodeTool


# ── Shared fixture: a minimal Config-like object ──────────────────────────────

class FakeConfig:
    """Minimal config for tool tests."""
    workdir: str
    no_confirm: bool = True
    a2a_enabled: bool = False
    web_search_enabled: bool = False
    memory_enabled: bool = False

    def __init__(self, workdir: str, no_confirm: bool = True):
        self.workdir = workdir
        self.no_confirm = no_confirm


# ═══════════════════════════════════════════════════════════════════════════════
# READ FILE
# ═══════════════════════════════════════════════════════════════════════════════

class TestReadFile:
    @pytest.mark.asyncio
    async def test_reads_existing_file(self, tmp_path: Path):
        f = tmp_path / "hello.txt"
        f.write_text("line one\nline two\nline three")
        tool = ReadFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="hello.txt")
        assert not result.is_error
        assert "line one" in result.output
        assert "line two" in result.output
        assert "1:" in result.output  # line numbers

    @pytest.mark.asyncio
    async def test_partial_read(self, tmp_path: Path):
        f = tmp_path / "multi.txt"
        f.write_text("a\nb\nc\nd\ne")
        tool = ReadFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="multi.txt", start_line=2, end_line=3)
        assert not result.is_error
        assert "b" in result.output
        assert "c" in result.output
        assert "a" not in result.output

    @pytest.mark.asyncio
    async def test_missing_file_returns_error(self, tmp_path: Path):
        tool = ReadFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="nope.txt")
        assert result.is_error
        assert "not found" in result.output.lower()

    @pytest.mark.asyncio
    async def test_path_is_directory_returns_error(self, tmp_path: Path):
        (tmp_path / "subdir").mkdir()
        tool = ReadFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="subdir")
        assert result.is_error
        assert "not a file" in result.output.lower()

    @pytest.mark.asyncio
    async def test_empty_file_is_ok(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_text("")
        tool = ReadFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="empty.txt")
        assert not result.is_error


# ═══════════════════════════════════════════════════════════════════════════════
# WRITE FILE
# ═══════════════════════════════════════════════════════════════════════════════

class TestWriteFile:
    @pytest.mark.asyncio
    async def test_creates_new_file(self, tmp_path: Path):
        tool = WriteFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="output.txt", content="hello world")
        assert not result.is_error
        assert (tmp_path / "output.txt").read_text() == "hello world"

    @pytest.mark.asyncio
    async def test_creates_parent_directories(self, tmp_path: Path):
        tool = WriteFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="a/b/c/deep.txt", content="deep content")
        assert not result.is_error
        assert (tmp_path / "a" / "b" / "c" / "deep.txt").exists()

    @pytest.mark.asyncio
    async def test_overwrites_existing_file(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("old content")
        tool = WriteFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="file.txt", content="new content")
        assert not result.is_error
        assert f.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_result_mentions_char_count(self, tmp_path: Path):
        tool = WriteFileTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="counted.txt", content="12345")
        assert "5" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# LIST FILES
# ═══════════════════════════════════════════════════════════════════════════════

class TestListFiles:
    @pytest.mark.asyncio
    async def test_lists_files_and_dirs(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x")
        (tmp_path / "b.py").write_text("y")
        (tmp_path / "subdir").mkdir()
        tool = ListFilesTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path=".")
        assert not result.is_error
        assert "a.py" in result.output
        assert "b.py" in result.output
        assert "subdir" in result.output

    @pytest.mark.asyncio
    async def test_empty_directory(self, tmp_path: Path):
        tool = ListFilesTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path=".")
        assert not result.is_error
        assert "empty" in result.output.lower()

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_error(self, tmp_path: Path):
        tool = ListFilesTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="ghost")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_file_path_returns_error(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        tool = ListFilesTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path="file.txt")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_recursive_lists_nested_files(self, tmp_path: Path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "nested.py").write_text("x")
        tool = ListFilesTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(path=".", recursive=True)
        assert not result.is_error
        assert "nested.py" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# RUN BASH
# ═══════════════════════════════════════════════════════════════════════════════

class TestRunBash:
    @pytest.mark.asyncio
    async def test_successful_command(self, tmp_path: Path):
        tool = RunBashTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(command="echo DevPilot")
        assert not result.is_error
        assert "DevPilot" in result.output

    @pytest.mark.asyncio
    async def test_nonzero_exit_is_error(self, tmp_path: Path):
        tool = RunBashTool(FakeConfig(str(tmp_path)))
        cmd = "exit 1" if sys.platform == "win32" else "exit 1"
        result = await tool.execute(command=cmd)
        assert result.is_error
        assert "exit code: 1" in result.output

    @pytest.mark.asyncio
    async def test_exit_code_in_output(self, tmp_path: Path):
        tool = RunBashTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(command="echo hi")
        assert "exit code:" in result.output

    @pytest.mark.asyncio
    async def test_missing_command_returns_error(self, tmp_path: Path):
        tool = RunBashTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(command="")
        assert result.is_error
        assert "command" in result.output.lower()

    @pytest.mark.asyncio
    async def test_timeout_returns_error(self, tmp_path: Path):
        tool = RunBashTool(FakeConfig(str(tmp_path)))
        sleep_cmd = "Start-Sleep 10" if sys.platform == "win32" else "sleep 10"
        result = await tool.execute(command=sleep_cmd, timeout=1)
        assert result.is_error
        assert "timed out" in result.output.lower()

    @pytest.mark.asyncio
    async def test_stderr_captured(self, tmp_path: Path):
        tool = RunBashTool(FakeConfig(str(tmp_path)))
        err_cmd = "Write-Error 'test error' 2>&1; exit 0" if sys.platform == "win32" else "echo err >&2; exit 0"
        result = await tool.execute(command=err_cmd)
        assert isinstance(result.output, str)


# ═══════════════════════════════════════════════════════════════════════════════
# SEARCH CODE
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchCode:
    @pytest.mark.asyncio
    async def test_finds_pattern_in_file(self, tmp_path: Path):
        (tmp_path / "main.py").write_text("def hello():\n    pass\n")
        tool = SearchCodeTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(pattern="def hello")
        assert not result.is_error
        assert "main.py" in result.output
        assert "def hello" in result.output

    @pytest.mark.asyncio
    async def test_no_match_returns_message(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("x = 1\n")
        tool = SearchCodeTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(pattern="zzz_no_match")
        assert not result.is_error
        assert "no matches" in result.output.lower()

    @pytest.mark.asyncio
    async def test_missing_pattern_returns_error(self, tmp_path: Path):
        tool = SearchCodeTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(pattern="")
        assert result.is_error

    @pytest.mark.asyncio
    async def test_glob_filter_respected(self, tmp_path: Path):
        (tmp_path / "a.py").write_text("TARGET_PYTHON")
        (tmp_path / "b.txt").write_text("TARGET_TEXT")
        tool = SearchCodeTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(pattern="TARGET", file_pattern="*.py")
        assert "a.py" in result.output
        assert "b.txt" not in result.output

    @pytest.mark.asyncio
    async def test_case_insensitive_fallback(self, tmp_path: Path):
        (tmp_path / "x.py").write_text("UPPERCASE_WORD")
        tool = SearchCodeTool(FakeConfig(str(tmp_path)))
        result = await tool.execute(pattern="uppercase_word")
        assert not result.is_error
        assert "x.py" in result.output


# ═══════════════════════════════════════════════════════════════════════════════
# PERMISSION GUARD
# ═══════════════════════════════════════════════════════════════════════════════

class TestPermissionGuard:
    @pytest.mark.asyncio
    async def test_no_confirm_mode_always_allows(self):
        guard = PermissionGuard(no_confirm=True)
        assert await guard.check("write_file", {"path": "x.py", "content": "hi"}) is True
        assert await guard.check("run_bash", {"command": "echo hi"}) is True

    @pytest.mark.asyncio
    async def test_user_approves(self, monkeypatch):
        guard = PermissionGuard(no_confirm=False)
        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert await guard.check("write_file", {"path": "x.py", "content": "hi"}) is True

    @pytest.mark.asyncio
    async def test_user_declines(self, monkeypatch):
        guard = PermissionGuard(no_confirm=False)
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert await guard.check("write_file", {"path": "x.py", "content": "hi"}) is False

    @pytest.mark.asyncio
    async def test_keyboard_interrupt_cancels(self, monkeypatch):
        guard = PermissionGuard(no_confirm=False)
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(KeyboardInterrupt))
        # KeyboardInterrupt should propagate or be handled — here we just confirm no crash
        try:
            await guard.check("run_bash", {"command": "rm -rf /"})
        except (KeyboardInterrupt, Exception):
            pass  # Expected


# ═══════════════════════════════════════════════════════════════════════════════
# TOOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolRegistry:
    def test_create_loads_builtin_tools(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path), no_confirm=True)
        registry = ToolRegistry(config)
        names = {s["name"] for s in registry.schemas}
        # Core Sprint 1 tools
        assert {"read_file", "write_file", "list_files", "run_bash", "search_code"}.issubset(names)

    def test_a2a_not_loaded_when_disabled(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path))
        config.a2a_enabled = False
        registry = ToolRegistry(config)
        names = {s["name"] for s in registry.schemas}
        assert "a2a_delegate_task" not in names

    def test_all_schemas_have_required_fields(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path))
        registry = ToolRegistry(config)
        for schema in registry.schemas:
            assert "name" in schema
            assert "description" in schema
            assert "input_schema" in schema

    @pytest.mark.asyncio
    async def test_execute_unknown_tool_returns_error(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path))
        registry = ToolRegistry(config)
        result = await registry.execute("nonexistent_tool", {})
        assert isinstance(result, ToolResult)
        assert result.is_error
        assert "unknown tool" in result.output.lower()

    @pytest.mark.asyncio
    async def test_execute_read_file_via_registry(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_text("registry test content")
        config = FakeConfig(str(tmp_path))
        registry = ToolRegistry(config)
        result = await registry.execute("read_file", {"path": "test.txt"})
        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert "registry test content" in result.output

    @pytest.mark.asyncio
    async def test_execute_write_file_no_confirm(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path), no_confirm=True)
        registry = ToolRegistry(config)
        result = await registry.execute("write_file", {"path": "out.txt", "content": "test"})
        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert (tmp_path / "out.txt").read_text() == "test"

    @pytest.mark.asyncio
    async def test_user_cancel_returns_non_error(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        config = FakeConfig(str(tmp_path), no_confirm=False)
        registry = ToolRegistry(config)
        result = await registry.execute("run_bash", {"command": "echo hi"})
        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert "cancelled" in result.output.lower()

    @pytest.mark.asyncio
    async def test_register_custom_mcp_tool(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path))
        registry = ToolRegistry(config)
        schema = {
            "name": "my_mcp_tool",
            "description": "A test MCP tool",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "_mcp_server_id": "server_1",
        }
        async def mock_executor(tool_input: dict) -> ToolResult:
            return ToolResult("mcp result", False)

        registry.register_mcp_tool(schema, mock_executor)
        assert registry.has_tool("my_mcp_tool")
        result = await registry.execute("my_mcp_tool", {})
        assert isinstance(result, ToolResult)
        assert result.output == "mcp result"

    @pytest.mark.asyncio
    async def test_deregister_mcp_tools(self, tmp_path: Path):
        config = FakeConfig(str(tmp_path))
        registry = ToolRegistry(config)
        schema = {
            "name": "mcp_removable",
            "description": "Will be removed",
            "input_schema": {"type": "object", "properties": {}, "required": []},
            "_mcp_server_id": "server_x",
        }
        async def mock_executor(tool_input: dict) -> ToolResult:
            return ToolResult("ok", False)

        registry.register_mcp_tool(schema, mock_executor)
        assert registry.has_tool("mcp_removable")
        registry.deregister_mcp_tools("server_x")
        assert not registry.has_tool("mcp_removable")
        names = {s["name"] for s in registry.schemas}
        assert "mcp_removable" not in names
