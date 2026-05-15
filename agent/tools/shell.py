"""
agent/tools/shell.py
────────────────────
Shell tool — run_bash.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import TYPE_CHECKING, Any

from agent.tools.base import BaseTool, ToolResult, ToolSchema

if TYPE_CHECKING:
    from agent.config import Config


_IS_WINDOWS = sys.platform == "win32"
_DEFAULT_SHELL = os.getenv(
    "DEVPILOT_SHELL",
    "powershell.exe" if _IS_WINDOWS else "/bin/bash",
)
_SHELL_FLAG = "-Command" if _IS_WINDOWS else "-c"

# Commands that are always blocked regardless of --no-confirm
_BLOCKED_COMMANDS = frozenset([
    "rm -rf /",
    "dd if=/dev/zero",
    ":(){:|:&};:",   # Fork bomb
])


class RunBashTool(BaseTool):
    """Execute a bash command in the working directory."""

    def __init__(self, config: "Config") -> None:
        self._config = config

    @property
    def schema(self) -> ToolSchema:
        return ToolSchema(
            name="run_bash",
            description=(
                "Execute a bash command in the project's working directory. "
                "Use for running tests, builds, package installs, linters, etc. "
                "Always shown to the user before execution."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Bash command to execute.",
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Timeout in seconds (default: 60).",
                        "default": 60,
                    },
                },
                "required": ["command"],
            },
            required=["command"],
            is_destructive=True,
            sprint="Sprint 1",
        )

    async def execute(self, command: str, timeout: int = 60) -> ToolResult:  # type: ignore[override]
        if not command:
            return ToolResult("Error: 'command' parameter is required.", is_error=True)

        if any(b in command for b in _BLOCKED_COMMANDS):
            return ToolResult(f"Error: Command contains blocked patterns.", is_error=True)

        try:
            # Use asyncio subprocess to avoid blocking the event loop
            process = await asyncio.create_subprocess_exec(
                _DEFAULT_SHELL,
                _SHELL_FLAG,
                command,
                cwd=self._config.workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    process.kill()
                    await process.communicate()
                except ProcessLookupError:
                    pass
                return ToolResult(
                    f"Error: Command timed out after {timeout}s: {command}", is_error=True
                )

            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            output_parts: list[str] = []
            if stdout.strip():
                output_parts.append(f"stdout:\n{stdout.rstrip()}")
            if stderr.strip():
                output_parts.append(f"stderr:\n{stderr.rstrip()}")

            output_parts.append(f"exit code: {process.returncode}")
            output = "\n\n".join(output_parts) if output_parts else "(no output)"
            is_error = process.returncode != 0
            
            return ToolResult(output, is_error=is_error)

        except Exception as e:
            return ToolResult(f"Error executing command: {e}", is_error=True)
