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

# Define custom themes for DevPilot
_custom_theme = Theme({
    "info": "dim cyan",
    "warning": "magenta",
    "danger": "bold red",
    "tool.name": "bold blue",
})

console = Console(theme=_custom_theme)


class UI:
    """Namespace for UI rendering functions."""

    @staticmethod
    def print_assistant_message(text: str) -> None:
        """Render normal markdown text from the assistant."""
        if not text.strip():
            return
        
        console.print()
        console.print(Markdown(text))
        console.print()

    @staticmethod
    def print_tool_call(tool_name: str, tool_input: dict) -> None:
        """Render a trace of a tool invocation."""
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
        console.print(f"[danger]❌ {msg}[/danger]")

    @staticmethod
    def print_info(msg: str) -> None:
        """Render a system info message."""
        console.print(f"[info]ℹ️ {msg}[/info]")

    @staticmethod
    def print_success(msg: str) -> None:
        """Render a success message."""
        console.print(f"[bold green]✓ {msg}[/bold green]")

    @staticmethod
    def print_thinking_block(thinking_text: str) -> None:
        """Render the model's extended thinking in a muted panel."""
        if not thinking_text or not thinking_text.strip():
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
        label = "New file" if is_new else "Changes"
        panel = Panel(
            Syntax(diff, "diff", theme="monokai", background_color="default"),
            title=f"[bold yellow]📝 {label}: {path}[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
        console.print(panel)

    @staticmethod
    def print_permission_prompt(tool_name: str, preview_lines: list[str]) -> None:
        """Render a permission request for a destructive tool."""
        body = "\n".join(preview_lines)
        panel = Panel(
            f"[bold]{body}[/bold]",
            title=f"[bold yellow]⚠ Permission required: {tool_name}[/bold yellow]",
            border_style="yellow",
            expand=False,
        )
        console.print(panel)
