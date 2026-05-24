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
from datetime import datetime
from pathlib import Path

from agent.a2a_server import app as a2a_app
from agent.config import Config, ConfigError
from agent.history import HistoryManager
from agent.loop import run_agent_loop
from agent.mcp_client import MCPManager
from agent.providers.factory import create_provider
from agent.tools import ToolRegistry
from agent.ui import UI


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
        success = run_setup_wizard(env_path=Path(".env"))
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
    try:
        config = Config.load()
    except ConfigError as e:
        UI.print_error(str(e))
        sys.exit(1)

    # Handle --setup flag (force wizard even if key exists)
    if args.setup:
        from agent.setup_wizard import run_setup_wizard
        run_setup_wizard(env_path=Path(".env"))
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

    # Wire up provider, context, registry
    provider = create_provider(config)

    from agent.context import RepoContext
    repo_context = RepoContext(config.workdir)
    registry = ToolRegistry(config, _context=repo_context)

    # MCP
    mcp_config_path = Path("mcp_servers.json")
    if not mcp_config_path.exists():
        mcp_config_path = Path(__file__).parent.parent / "mcp_servers.json"
    mcp_manager = MCPManager(mcp_config_path)
    await mcp_manager.connect_all(registry)

    # A2A server
    a2a_app.state.config   = config
    a2a_app.state.registry = registry

    if config.a2a_enabled:
        import uvicorn
        import socket
        
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
    from agent.tui.app import DevPilotApp
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
