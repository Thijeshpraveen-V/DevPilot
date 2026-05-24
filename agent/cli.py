"""
agent/cli.py
─────────────
CLI entry point for DevPilot.
Parses arguments, runs first-run setup wizard if needed,
initializes components, and starts the interactive TUI or CI loop.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from datetime import datetime
from pathlib import Path


def _fix_windows_console() -> None:
    """
    Enable ANSI/VT100 support and UTF-8 encoding in Windows terminals.

    Root cause of the blank black CMD screen:
      - CMD.exe does NOT enable Virtual Terminal Processing by default.
      - Textual sends ANSI escape sequences to probe terminal capabilities.
      - Without VT support, CMD either hangs or renders nothing.
      - PowerShell has VT enabled by default → works immediately.

    Fixes applied:
      1. Enable ENABLE_VIRTUAL_TERMINAL_PROCESSING via Windows API (ctypes).
      2. Switch stdout/stderr to UTF-8 so → ✓ etc don't crash in cp1252.
      3. Set TERM / COLORTERM so Textual skips slow capability negotiation.
    """
    if sys.platform != "win32":
        return

    # ── 1. Enable Virtual Terminal Processing ─────────────────────────────────
    try:
        import ctypes
        import ctypes.wintypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]

        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        ENABLE_PROCESSED_OUTPUT            = 0x0001

        for handle_id in (-10, -11):   # STD_INPUT=-10, STD_OUTPUT=-11
            handle = kernel32.GetStdHandle(handle_id)
            if handle and handle != -1:
                mode = ctypes.wintypes.DWORD(0)
                if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                    new_mode = (mode.value
                                | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                                | ENABLE_PROCESSED_OUTPUT)
                    kernel32.SetConsoleMode(handle, new_mode)
    except Exception:
        pass   # non-fatal — worst case CMD is slow, not broken

    # ── 2. Switch stdout/stderr to UTF-8 ──────────────────────────────────────
    # Prevents UnicodeEncodeError on → ✓ ✗ characters in cp1252 CMD sessions
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        # Also tell Windows console host to use UTF-8 codepage
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)  # type: ignore[attr-defined]
    except Exception:
        pass

    # ── 3. Hint terminal type so Textual doesn't hang on capability detection ─
    # Textual checks these env vars first; without them it sends probe sequences
    # that CMD ignores, causing a multi-second hang.
    os.environ.setdefault("TERM", "xterm-256color")
    os.environ.setdefault("COLORTERM", "truecolor")


# Run immediately — must happen before any rich/textual import
_fix_windows_console()

# Python version guard — must run before any other import
if sys.version_info < (3, 11):
    print(
        f"\n[DevPilot] Python 3.11 or newer is required.\n"
        f"  You are running Python {sys.version_info.major}.{sys.version_info.minor}.\n"
        f"  Download the latest Python from: https://python.org/downloads/\n"
    )
    sys.exit(1)

# Module-level imports: only lightweight config/ui — everything else is lazy inside main_async()
from agent.config import Config, ConfigError
from agent.providers.factory import create_provider
from agent.ui import UI

_T0 = time.perf_counter()

def _log_startup(msg: str) -> None:
    """Print a startup progress line. Helps users see DevPilot is loading."""
    elapsed = time.perf_counter() - _T0
    # Use plain ASCII fallback so CMD doesn't choke on escape codes if VT failed
    print(f"\r[{elapsed:.1f}s] {msg}...", end="", flush=True)

def _clear_startup() -> None:
    """Clear the startup progress line once TUI takes over."""
    print("\r" + " " * 60 + "\r", end="", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="devpilot",
        description="DevPilot — Autonomous AI coding agent for your terminal",
    )
    parser.add_argument("--provider", choices=["anthropic", "openai"], help="Model provider")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--base-url", help="OpenAI-compatible base URL (e.g. Ollama)")
    parser.add_argument("--no-confirm", action="store_true", help="Skip confirmation prompts")
    parser.add_argument("--thinking", action="store_true", help="Enable extended thinking (Claude only)")
    parser.add_argument("--thinking-budget", type=int, help="Extended thinking token budget (default: 10000)")
    parser.add_argument("--no-web-search", action="store_true", help="Disable web search tool")
    parser.add_argument("--no-memory", action="store_true", help="Disable long-term memory")
    parser.add_argument("--workdir", help="Working directory for file operations (default: cwd)")
    parser.add_argument("--task", help="Run a single task and exit (CI mode)")
    parser.add_argument("--resume", help="Resume a previous session by ID")
    parser.add_argument("--a2a-port", type=int, help="A2A server port (default: 8000)")
    parser.add_argument("--no-a2a", action="store_true", help="Disable A2A server")
    parser.add_argument("--setup", action="store_true", help="Re-run the setup wizard")
    return parser.parse_args()


def _apply_cli_overrides(args: argparse.Namespace) -> None:
    """Push CLI flag values into env vars so Config.load() picks them up."""
    if args.provider:
        os.environ["DEVPILOT_PROVIDER"] = args.provider
    if args.model:
        os.environ["DEVPILOT_MODEL"] = args.model
    if args.base_url:
        os.environ["DEVPILOT_BASE_URL"] = args.base_url
    if args.no_confirm:
        os.environ["DEVPILOT_NO_CONFIRM"] = "true"
    if args.thinking:
        os.environ["DEVPILOT_THINKING"] = "true"
    if args.thinking_budget:
        os.environ["DEVPILOT_THINKING_BUDGET"] = str(args.thinking_budget)
    if args.no_web_search:
        os.environ["DEVPILOT_NO_WEB_SEARCH"] = "true"
    if args.no_memory:
        os.environ["DEVPILOT_NO_MEMORY"] = "true"
    if args.workdir:
        os.environ["DEVPILOT_WORKDIR"] = args.workdir
    if args.a2a_port:
        os.environ["DEVPILOT_A2A_PORT"] = str(args.a2a_port)
    if args.no_a2a:
        os.environ["DEVPILOT_NO_A2A"] = "true"


def _ensure_api_key(config: Config, args: argparse.Namespace) -> Config:
    """
    Check for a valid API key. If missing, run the setup wizard.
    Re-loads config after wizard so the new key is picked up.
    Returns the (possibly reloaded) config.
    """
    from agent.config import REQUIRED_ENV_KEYS
    key_name = REQUIRED_ENV_KEYS[config.provider]

    if config.active_api_key:
        return config  # Key present — nothing to do

    # Force re-run wizard if --setup flag passed
    if args.setup or not config.active_api_key:
        from agent.setup_wizard import run_setup_wizard
        _user_env = Path.home() / ".devpilot" / ".env"
        success = run_setup_wizard(env_path=_user_env)
        if not success:
            # Wizard skipped (CI/no TTY) or failed — print helpful error
            UI.print_error(
                f"Missing API key for provider '{config.provider}'.\n"
                f"  Set {key_name} in your environment or .env file.\n"
                f"  Run 'devpilot --setup' to configure interactively."
            )
            sys.exit(1)

        # Reload config so the new env vars are picked up
        try:
            config = Config.load()
            _apply_cli_overrides(args)
            config = Config.load()
        except ConfigError as e:
            UI.print_error(str(e))
            sys.exit(1)

    return config


async def main_async() -> None:
    args = parse_args()
    _apply_cli_overrides(args)

    # Load config
    _log_startup("Loading configuration")
    try:
        config = Config.load()
    except ConfigError as e:
        UI.print_error(str(e))
        sys.exit(1)

    # Handle --setup flag (force wizard even if key exists)
    if args.setup:
        _clear_startup()
        from agent.setup_wizard import run_setup_wizard
        _user_env = Path.home() / ".devpilot" / ".env"
        run_setup_wizard(env_path=_user_env)

        try:
            config = Config.load()
        except ConfigError as e:
            UI.print_error(str(e))
            sys.exit(1)
    else:
        # Ensure API key — runs wizard if missing
        config = _ensure_api_key(config, args)

    # Final key validation (catches invalid key format etc.)
    try:
        config.validate_api_key()
    except ConfigError as e:
        UI.print_error(str(e))
        sys.exit(1)

    # Wire up provider, context, registry — lazy imports keep startup lean
    _log_startup("Initializing AI provider")
    provider = create_provider(config)

    _log_startup("Scanning project context")
    from agent.context import RepoContext
    from agent.history import HistoryManager
    from agent.tools import ToolRegistry
    repo_context = RepoContext(config.workdir)
    registry = ToolRegistry(config, _context=repo_context)

    # MCP — lazy import to avoid loading the mcp library at startup
    _log_startup("Connecting MCP servers")
    from agent.mcp_client import MCPManager
    mcp_config_path = Path("mcp_servers.json")
    if not mcp_config_path.exists():
        mcp_config_path = Path(__file__).parent.parent / "mcp_servers.json"
    mcp_manager = MCPManager(mcp_config_path)
    await mcp_manager.connect_all(registry)

    # A2A server — only import fastapi/uvicorn when A2A is actually enabled
    _log_startup("Starting A2A server")
    if config.a2a_enabled:
        from agent.a2a_server import app as a2a_app
        import uvicorn
        import socket

        a2a_app.state.config   = config
        a2a_app.state.registry = registry

        # Check if port is available
        port_in_use = False
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", config.a2a_port))
            except OSError:
                port_in_use = True

        if port_in_use:
            UI.print_error(f"Port {config.a2a_port} is already in use. A2A server disabled. Use --a2a-port <port> to change.")
            a2a_server = None
            a2a_task = None
        else:
            a2a_cfg = uvicorn.Config(
                app=a2a_app,
                host="0.0.0.0",
                port=config.a2a_port,
                log_level="error",
            )
            a2a_server = uvicorn.Server(a2a_cfg)
            a2a_task   = asyncio.create_task(a2a_server.serve())
    else:
        a2a_server = None
        a2a_task   = None

    # History / session
    history    = HistoryManager()
    session_id = args.resume or datetime.now().strftime("%Y%m%d_%H%M%S")
    session_file = config.sessions_dir / f"{session_id}.json"

    if args.resume:
        if session_file.exists():
            history.load(session_file)
            if args.task:
                UI.print_info(f"Resumed session: {session_id}")
        else:
            UI.print_error(f"Session '{session_id}' not found at {session_file}")
            sys.exit(1)
    else:
        if args.task:
            UI.print_info(f"New session: {session_id}")

    # ── CI / single-task mode ─────────────────────────────────────────────────
    if args.task:
        from agent.loop import run_agent_loop
        history.append(provider.make_user_message(args.task))
        await run_agent_loop(
            provider=provider,
            registry=registry,
            history=history,
            config=config,
            max_iterations=config.max_iterations,
            context=repo_context,
        )
        history.save(session_file)
        if a2a_server and a2a_task:
            a2a_server.should_exit = True
            await a2a_task
        await mcp_manager.close()
        sys.exit(0)

    # ── Interactive TUI mode ──────────────────────────────────────────────────
    _log_startup("Starting DevPilot TUI")
    from agent.tui.app import DevPilotApp
    _clear_startup()   # erase progress line before TUI takes over the screen
    app = DevPilotApp(
        provider=provider,
        registry=registry,
        history=history,
        config=config,
        repo_context=repo_context,
    )
    try:
        await app.run_async()
    finally:
        if a2a_server and a2a_task:
            a2a_server.should_exit = True
            await a2a_task
        await mcp_manager.close()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
