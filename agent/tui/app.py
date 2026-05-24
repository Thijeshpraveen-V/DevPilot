"""
agent/tui/app.py
────────────────
Textual TUI for DevPilot.
Provides a premium, full-screen terminal IDE experience.
"""

from __future__ import annotations

from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, ScrollableContainer, VerticalScroll
from textual.widgets import Header, Footer, Input, RichLog, Button, Label, Tree, Static, LoadingIndicator
from textual.widgets.tree import TreeNode
from textual.screen import ModalScreen
from textual.events import MouseDown, MouseUp, MouseMove
from textual.reactive import reactive
from textual import work, on

from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.panel import Panel

from agent.ui import (
    UI, UIEvent, AssistantMessageEvent, StreamTokenEvent, ToolCallEvent,
    ToolResultEvent, ErrorEvent, InfoEvent, SuccessEvent, DiffEvent, ThinkingEvent,
)
from agent.loop import run_agent_loop

CSS = """
Screen {
    background: #1e1e1e;
}

#main-container {
    height: 100%;
}

#project-map {
    width: 25%;
    background: #181818;
    padding: 0 1;
}

#map-title {
    text-style: bold;
    color: #4fc1ff;
    padding: 1 0;
    background: #181818;
}

#project-tree {
    background: #181818;
    color: #cccccc;
    padding: 0;
}

#chat-area {
    width: 50%;
    height: 100%;
    padding: 0 1;
}

#chat-log {
    height: 1fr;
    border: none;
    background: #1e1e1e;
}

#live-stream {
    background: #1e1e1e;
    border: solid #007acc;
    padding: 0 1;
    display: none;
    height: auto;
    max-height: 10;
}

#agent-spinner {
    height: 1;
    color: #4fc1ff;
    background: #1e1e1e;
    display: none;
}

#chat-input {
    dock: bottom;
    margin: 1;
    background: #252526;
    border: round #007acc;
}

VerticalResizer {
    width: 1;
    height: 100%;
    background: #2d2d2d;
    content-align: center middle;
    color: #4fc1ff;
    text-style: bold;
}

VerticalResizer:hover {
    background: #007acc;
}

VerticalResizer.-dragging {
    background: #007acc;
}

#drawer-title {
    text-style: bold;
    color: #4fc1ff;
    padding: 1 0;
    background: #181818;
}

#drawer-log {
    background: #181818;
}

/* Modal */
PermissionModal {
    align: center middle;
    background: rgba(0,0,0,0.75);
}
#modal-dialog {
    width: 64;
    height: auto;
    max-height: 80%;
    padding: 1 2;
    background: #252526;
    border: thick #d7ba7d;
}
#modal-title {
    text-style: bold;
    color: #d7ba7d;
    padding-bottom: 1;
}
#modal-preview {
    height: 1fr;
    max-height: 20;
    background: #1e1e1e;
    border: solid #333;
    padding: 1;
    overflow-y: auto;
}
#modal-buttons {
    layout: horizontal;
    align: center middle;
    height: auto;
    margin-top: 1;
}
Button { margin: 0 1; }

.copy-btn { 
    display: none;
    margin-top: 1;
    background: #007acc;
    color: white;
    border: none;
    height: 1;
    min-width: 10;
}
ChatMessage:hover .copy-btn { 
    display: block; 
}
ChatMessage {
    height: auto;
    margin-bottom: 1;
}
"""


class PermissionModal(ModalScreen[str]):
    """Centered modal that pauses the worker until the user decides."""

    def __init__(self, tool_name: str, preview_lines: list[str]) -> None:
        self.tool_name = tool_name
        self.preview_text = "\n".join(preview_lines)
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label(f"⚠  Permission required: {self.tool_name}", id="modal-title")
            with ScrollableContainer(id="modal-preview"):
                yield Label(self.preview_text)
            with Horizontal(id="modal-buttons"):
                yield Button("Allow Once", id="btn-allow",     variant="primary")
                yield Button("Allow All",  id="btn-allow-all", variant="warning")
                yield Button("Deny",       id="btn-deny",      variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {"btn-allow": "y", "btn-allow-all": "a", "btn-deny": "n"}
        button_id = event.button.id or ""
        self.dismiss(mapping.get(button_id, "n"))


class VerticalResizer(Static):
    """A vertical drag handle to resize sidebars."""
    
    def on_mouse_down(self, event: MouseDown) -> None:
        self.add_class("-dragging")
        self.capture_mouse()
        
    def on_mouse_up(self, event: MouseUp) -> None:
        self.remove_class("-dragging")
        self.release_mouse()
        
    def on_mouse_move(self, event: MouseMove) -> None:
        if self.has_class("-dragging"):
            from typing import Any
            app: Any = self.app
            total_width = app.console.size.width
            if total_width > 0:
                if self.id == "left-resizer":
                    new_percent = int((event.screen_x / total_width) * 100)
                else:
                    new_percent = int(((total_width - event.screen_x) / total_width) * 100)
                
                # Constrain to reasonable minimum and maximum
                if 5 <= new_percent <= 40:
                    if self.id == "left-resizer":
                        app._left_width = new_percent
                    else:
                        app._right_width = new_percent
                    app._apply_sidebar_widths()


class ProjectMap(Vertical):
    """
    Left sidebar — uses a native Textual Tree widget so nodes are
    properly indented, truncated at the pane boundary, and collapsible.
    """

    def compose(self) -> ComposeResult:
        yield Label("📁  Project Context", id="map-title")
        self.file_tree: Tree[str] = Tree("", id="project-tree")
        self.file_tree.show_root = False
        self.file_tree.guide_depth = 2
        yield self.file_tree

    def populate(self, workdir_path: "Path", repo_context: Any) -> None:  # type: ignore[name-defined]
        """Rebuild the tree from the workdir, ignoring ignored dirs."""
        from pathlib import Path

        self.file_tree.clear()
        root = self.file_tree.root

        IGNORE = {
            ".git", "node_modules", ".venv", "__pycache__",
            "dist", "build", ".next", ".tox", "coverage_html_report",
            ".devpilot_sessions", ".pytest_cache",
        }

        def _add(node: TreeNode, directory: Path, depth: int = 0) -> None:
            if depth > 6:
                return
            try:
                items = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except OSError:
                return
            for item in items:
                if item.name.startswith(".") and item.name not in (".env", ".gitignore", ".github"):
                    continue
                if item.name in IGNORE or item.name.endswith(".egg-info"):
                    continue
                if item.is_dir():
                    child = node.add(f"📁 {item.name}", expand=depth < 1)
                    _add(child, item, depth + 1)
                else:
                    # Mark files the model has already read with a dot
                    rel = str(item.relative_to(workdir_path))
                    read = rel in getattr(repo_context, "_read_files", {})
                    icon = "●" if read else "📄"
                    node.add_leaf(f"{icon} {item.name}")

        _add(root, workdir_path)


class StreamingMessage(Vertical):
    """Live-updating widget during streaming. Replaced by ChatMessage on completion."""
    def __init__(self, role: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.role = role
        self._buffer = ""
        self._md_widget = Static(Markdown(" █"))

    def compose(self) -> ComposeResult:
        color = "green" if self.role == "You" else "cyan"
        yield Static(f"[bold {color}]{self.role}:[/bold {color}]", markup=True)
        yield self._md_widget

    def update_token(self, token: str) -> None:
        self._buffer += token
        self._md_widget.update(Markdown(self._buffer + " █"))


class ChatMessage(Vertical):
    """Final rendered message with Copy button."""
    def __init__(self, role: str, text: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.role = role
        self.text = text

    def compose(self) -> ComposeResult:
        color = "green" if self.role == "You" else "cyan"
        yield Static(f"[bold {color}]{self.role}:[/bold {color}]", markup=True)
        yield Static(Markdown(self.text))
        if self.role == "DevPilot":
            yield Button("📋 Copy", classes="copy-btn")

    @on(Button.Pressed, ".copy-btn")
    def copy_text(self, event: Button.Pressed) -> None:
        self.app.copy_to_clipboard(self.text)
        self.app.notify("Copied to clipboard!", title="Success")


class DevPilotApp(App):
    """The main DevPilot Textual application."""

    CSS = CSS
    TITLE = "DevPilot V2"
    BINDINGS = [
        ("ctrl+b", "toggle_map", "Toggle Map"),
        ("f1", "shrink_sidebar", "Shrink Sidebar"),
        ("f2", "grow_sidebar", "Grow Sidebar"),
        ("f3", "copy_last", "Copy Response"),
    ]

    def __init__(
        self,
        provider: Any,
        registry: Any,
        history: Any,
        config: Any,
        repo_context: Any,
    ) -> None:
        super().__init__()
        self.provider     = provider
        self.registry     = registry
        self.history      = history
        self.config       = config
        self.repo_context = repo_context
        self._active_stream: StreamingMessage | None = None
        self._last_assistant_message = ""
        self._left_width = 25
        UI.set_tui_app(self)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="main-container"):
            self.project_map = ProjectMap(id="project-map")
            yield self.project_map
            
            yield VerticalResizer("↔", id="left-resizer")
            
            with Vertical(id="chat-area"):
                self.chat_log = VerticalScroll(id="chat-log")
                yield self.chat_log
                self.spinner = LoadingIndicator(id="agent-spinner")
                yield self.spinner
                yield Input(
                    placeholder="Ask DevPilot… (type 'exit' to quit)",
                    id="chat-input",
                )
        yield Footer()

    async def on_mount(self) -> None:
        from pathlib import Path
        self._apply_sidebar_widths()
        # Use the config workdir — the actual DevPilot project root
        self._refresh_project_map()
        welcome_msg = "DevPilot is ready. Type your task below to begin."
        await self.chat_log.mount(ChatMessage("DevPilot", welcome_msg))
        self.chat_log.scroll_end(animate=False)
        self._last_assistant_message = welcome_msg
        self.sub_title = (
            f"Model: {self.config.model}  │  "
            f"Workdir: {self.config.workdir}  │  "
            f"Session: active"
        )

    def _refresh_project_map(self) -> None:
        from pathlib import Path
        workdir = Path(self.config.workdir).resolve()
        self.project_map.populate(workdir, self.repo_context)

    def action_toggle_map(self) -> None:
        self.project_map.display = not self.project_map.display
        self._apply_sidebar_widths()

    def action_shrink_sidebar(self) -> None:
        if self._left_width > 5: self._left_width -= 5
        self._apply_sidebar_widths()

    def action_grow_sidebar(self) -> None:
        if self._left_width < 50: self._left_width += 5
        self._apply_sidebar_widths()
        
    def action_copy_last(self) -> None:
        if self._last_assistant_message:
            self.copy_to_clipboard(self._last_assistant_message)
            self.notify("Copied last response to clipboard!", title="Success")
        else:
            self.notify("Nothing to copy yet.", severity="warning")

    def _apply_sidebar_widths(self) -> None:
        self.project_map.styles.width = f"{self._left_width}%"
        chat_width = 100 - (self._left_width if self.project_map.display else 0)
        self.query_one("#chat-area").styles.width = f"{chat_width}%"

    @work(exclusive=True)
    async def run_agent_task(self, user_input: str) -> None:
        self.history.append(self.provider.make_user_message(user_input))
        try:
            await run_agent_loop(
                provider=self.provider,
                registry=self.registry,
                history=self.history,
                config=self.config,
                max_iterations=self.config.max_iterations,
                context=self.repo_context,
            )
        except Exception as e:
            self.post_message(ErrorEvent(f"Agent loop crashed: {e}"))

    async def on_worker_state_changed(self, event: Any) -> None:
        """Re-enable input when the agent loop finishes."""
        if event.worker.name == "run_agent_task" and event.state.name in ("SUCCESS", "ERROR", "CANCELLED"):
            self.spinner.display = False

            try:
                inp = self.query_one("#chat-input", Input)
                inp.disabled = False
                inp.focus()
            except Exception:
                pass

            # Safety fallback: if AssistantMessageEvent never arrived (edge case),
            # finalize the stream now so the response is never lost.
            if self._active_stream:
                final_text = self._active_stream._buffer
                await self._active_stream.remove()
                self._active_stream = None
                if final_text:
                    await self.chat_log.mount(ChatMessage("DevPilot", final_text))
                    self.chat_log.scroll_end(animate=False)
                    self._last_assistant_message = final_text

            # Refresh tree to show newly read/written files
            self._refresh_project_map()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        user_input = event.value.strip()
        if not user_input:
            return
        if user_input.lower() in ("exit", "quit"):
            self.exit()
            return
            
        inp = self.query_one("#chat-input", Input)
        inp.disabled = True
        inp.value = ""
        
        await self.chat_log.mount(ChatMessage("You", user_input))
        self.chat_log.scroll_end(animate=False)
        
        self.spinner.display = True
        self.run_agent_task(user_input)

    # ── UI event routing ──────────────────────────────────────────────────────

    @on(AssistantMessageEvent)
    @on(StreamTokenEvent)
    @on(ToolCallEvent)
    @on(ToolResultEvent)
    @on(ErrorEvent)
    @on(InfoEvent)
    @on(SuccessEvent)
    @on(DiffEvent)
    @on(ThinkingEvent)
    async def handle_ui_events(self, event: UIEvent) -> None:
        if isinstance(event, AssistantMessageEvent):
            if self._active_stream:
                # Streaming was used — use the already-buffered text.
                # Ignore event.text to avoid duplication (it's the same content).
                final_text = self._active_stream._buffer
                await self._active_stream.remove()
                self._active_stream = None
            else:
                # Non-streaming path — event.text is the only source.
                final_text = event.text.strip()

            if final_text:
                await self.chat_log.mount(ChatMessage("DevPilot", final_text))
                self.chat_log.scroll_end(animate=False)
                self._last_assistant_message = final_text

        elif isinstance(event, StreamTokenEvent):
            if self.spinner.display:
                self.spinner.display = False
            if not self._active_stream:
                self._active_stream = StreamingMessage("DevPilot")
                await self.chat_log.mount(self._active_stream)
                self.chat_log.scroll_end(animate=False)
            self._active_stream.update_token(event.token)
            self.chat_log.scroll_end(animate=False)

        elif isinstance(event, ToolCallEvent):
            if self._active_stream:
                final_text = self._active_stream._buffer
                await self._active_stream.remove()
                self._active_stream = None
                await self.chat_log.mount(ChatMessage("DevPilot", final_text))
                self.chat_log.scroll_end(animate=False)
                self._last_assistant_message = final_text
            
            self.spinner.display = True
            
            if isinstance(event.tool_input, dict):
                args = ", ".join(f"{k}={v!r}" for k, v in event.tool_input.items())
                inp_str = f"({args})"
            else:
                import json
                try:
                    inp_str = json.dumps(event.tool_input)
                except Exception:
                    inp_str = str(event.tool_input)
                
            if len(inp_str) > 150:
                inp_str = inp_str[:147] + "..."
                
            await self.chat_log.mount(Static(f"[dim cyan]🔧 Used {event.tool_name}{inp_str}[/dim cyan]", markup=True))
            self.chat_log.scroll_end(animate=False)

        elif isinstance(event, ToolResultEvent):
            if event.is_error:
                err_line = event.content.splitlines()[0] if event.content else "Unknown error"
                await self.chat_log.mount(Static(f"[dim red]❌ {event.tool_name} failed: {err_line}[/dim red]", markup=True))
                self.chat_log.scroll_end(animate=False)

        elif isinstance(event, ErrorEvent):
            await self.chat_log.mount(Static(f"[bold red]❌ {event.msg}[/bold red]", markup=True))
            self.chat_log.scroll_end(animate=False)

        elif isinstance(event, InfoEvent):
            await self.chat_log.mount(Static(f"[dim cyan]ℹ {event.msg}[/dim cyan]", markup=True))
            self.chat_log.scroll_end(animate=False)

        elif isinstance(event, SuccessEvent):
            await self.chat_log.mount(Static(f"[bold green]✓ {event.msg}[/bold green]", markup=True))
            self.chat_log.scroll_end(animate=False)

        elif isinstance(event, DiffEvent):
            from textual.widgets import Label
            await self.chat_log.mount(Label(f"[yellow]📝 {'New' if event.is_new else 'Diff'}: {event.path}[/yellow]", markup=True))
            self.chat_log.scroll_end(animate=False)

        elif isinstance(event, ThinkingEvent):
            await self.chat_log.mount(Static(f"[dim]🧠 Extended Thinking...[/dim]", markup=True))
            self.chat_log.scroll_end(animate=False)
