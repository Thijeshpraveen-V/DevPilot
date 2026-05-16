"""
agent/ui.py
───────────
Rich-based user interface for DevPilot terminal output.
Handles rendering markdown, tool traces, diffs, and errors.
"""

from __future__ import annotations

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.theme import Theme
import typing
from typing import Any

if typing.TYPE_CHECKING:
    from textual.message import Message as _TextualMessage
else:
    try:
        from textual.message import Message as _TextualMessage
    except ImportError:
        _TextualMessage = object

class UIEvent(_TextualMessage):
    pass

class AssistantMessageEvent(UIEvent):
    def __init__(self, text: str) -> None:
        self.text = text
        super().__init__()

class StreamTokenEvent(UIEvent):
    def __init__(self, token: str) -> None:
        self.token = token
        super().__init__()

class ToolCallEvent(UIEvent):
    def __init__(self, tool_name: str, tool_input: dict) -> None:
        self.tool_name = tool_name
        self.tool_input = tool_input
        super().__init__()

class ToolResultEvent(UIEvent):
    def __init__(self, tool_name: str, content: str, is_error: bool) -> None:
        self.tool_name = tool_name
        self.content = content
        self.is_error = is_error
        super().__init__()

class ErrorEvent(UIEvent):
    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__()

class InfoEvent(UIEvent):
    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__()

class SuccessEvent(UIEvent):
    def __init__(self, msg: str) -> None:
        self.msg = msg
        super().__init__()

class DiffEvent(UIEvent):
    def __init__(self, path: str, diff: str, is_new: bool) -> None:
        self.path = path
        self.diff = diff
        self.is_new = is_new
        super().__init__()

class ThinkingEvent(UIEvent):
    def __init__(self, thinking_text: str) -> None:
        self.thinking_text = thinking_text
        super().__init__()


# ── Rich Terminal Theme (Fallback / CI mode) ──────────────────────────────────

_custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "tool.name": "bold blue",
})

console = Console(theme=_custom_theme)


class UI:
    """Namespace for UI rendering functions."""
    
    _tui_app: Any = None

    @classmethod
    def set_tui_app(cls, app: Any) -> None:
        cls._tui_app = app

    @staticmethod
    def print_stream_token(token: str) -> None:
        """Render a single stream token."""
        if UI._tui_app:
            UI._tui_app.post_message(StreamTokenEvent(token))
            return
        console.print(token, end="", highlight=False)

    @staticmethod
    def print_assistant_message(text: str) -> None:
        """Render normal markdown text from the assistant."""
        if not text.strip():
            return
            
        if UI._tui_app:
            UI._tui_app.post_message(AssistantMessageEvent(text))
            return
        
        console.print()
        console.print(Markdown(text))
        console.print()

    @staticmethod
    def print_tool_call(tool_name: str, tool_input: dict) -> None:
        """Render a trace of a tool invocation."""
        if UI._tui_app:
            UI._tui_app.post_message(ToolCallEvent(tool_name, tool_input))
            return

        # We can format the tool input nicely
        import json
        try:
            input_str = json.dumps(tool_input, indent=2)
        except Exception:
            input_str = str(tool_input)
            
        panel = Panel(
            Syntax(input_str, "json", theme="monokai", background_color="default"),
            title=f"[tool.name]🔧 Tool Call: {tool_name}[/tool.name]",
            border_style="blue",
            expand=False,
        )
        console.print(panel)

    @staticmethod
    def print_tool_result(tool_name: str, content: str, is_error: bool = False) -> None:
        """Render the result of a tool execution."""
        if UI._tui_app:
            UI._tui_app.post_message(ToolResultEvent(tool_name, content, is_error))
            return

        # Truncate output if it's too long
        lines = content.splitlines()
        if len(lines) > 20:
            content = "\n".join(lines[:20]) + f"\n... (truncated {len(lines) - 20} lines)"
            
        border_color = "red" if is_error else "green"
        title = f"[bold {border_color}]Result: {tool_name}[/bold {border_color}]"
        
        panel = Panel(
            content,
            title=title,
            border_style=border_color,
            expand=False,
        )
        console.print(panel)

    @staticmethod
    def print_error(msg: str) -> None:
        """Render a system or application error."""
        if UI._tui_app:
            UI._tui_app.post_message(ErrorEvent(msg))
            return
        console.print(f"[danger]❌ {msg}[/danger]")

    @staticmethod
    def print_info(msg: str) -> None:
        """Render a system info message."""
        if UI._tui_app:
            UI._tui_app.post_message(InfoEvent(msg))
            return
        console.print(f"[info]ℹ️ {msg}[/info]")

    @staticmethod
    def print_success(msg: str) -> None:
        """Render a success message."""
        if UI._tui_app:
            UI._tui_app.post_message(SuccessEvent(msg))
            return
        console.print(f"[bold green]✓ {msg}[/bold green]")

    @staticmethod
    def print_thinking_block(thinking_text: str) -> None:
        """Render the model's extended thinking in a muted panel."""
        if not thinking_text or not thinking_text.strip():
            return
            
        if UI._tui_app:
            UI._tui_app.post_message(ThinkingEvent(thinking_text))
            return

        lines = thinking_text.splitlines()
        if len(lines) > 30:
            display = "\n".join(lines[:30]) + f"\n... [{len(lines) - 30} more lines hidden]"
        else:
            display = thinking_text
        panel = Panel(
            f"[dim]{display}[/dim]",
            title="[dim]🧠 Extended Thinking[/dim]",
            border_style="dim",
            expand=False,
        )
        console.print(panel)

    @staticmethod
    def print_diff(path: str, diff: str, is_new: bool = False) -> None:
        """Render a syntax-highlighted unified diff before a file write."""
        if UI._tui_app:
            UI._tui_app.post_message(DiffEvent(path, diff, is_new))
            return

        label = "New file" if is_new else "Changes"
        panel = Panel(
            Syntax(diff, "diff", theme="monokai", background_color="default"),
            title=f"[bold yellow]📝 {label}: {path}[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
        console.print(panel)

    @staticmethod
    async def ask_permission(tool_name: str, preview_lines: list[str]) -> str:
        """
        Request permission. If in TUI mode, pushes an async modal.
        Otherwise, blocks on input() in an executor so the async loop doesn't stall.
        """
        if UI._tui_app:
            from agent.tui.app import PermissionModal
            # app.push_screen_wait is async and pauses the worker safely!
            choice = await UI._tui_app.push_screen_wait(PermissionModal(tool_name, preview_lines))
            return str(choice)

        body = "\n".join(preview_lines)
        panel = Panel(
            f"[bold]{body}[/bold]",
            title=f"[bold yellow]⚠ Permission required: {tool_name}[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
        console.print(panel)

        import asyncio
        loop = asyncio.get_event_loop()
        def _get_input():
            try:
                return input("  [y] allow once  [a] allow all  [n] deny: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                return "n"
        
        while True:
            choice = await loop.run_in_executor(None, _get_input)
            if choice in ("y", "yes", "", "a", "all", "n", "no"):
                return choice
