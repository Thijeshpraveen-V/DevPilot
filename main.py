"""
main.py
───────
CLI entry point for DevPilot.
Parses arguments, initializes components, and starts the interactive REPL.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout

from agent.a2a_server import app as a2a_app
from agent.config import Config, ConfigError
from agent.history import HistoryManager
from agent.loop import run_agent_loop
from agent.mcp_client import MCPManager
from agent.providers.factory import create_provider
from agent.tools import ToolRegistry
from agent.ui import UI


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="DevPilot: AI-Powered Terminal Coding Agent")
    parser.add_argument("--provider", choices=["anthropic", "openai"], help="Model provider to use")
    parser.add_argument("--model", help="Specific model name to use")
    parser.add_argument("--base-url", help="Base URL for local models (e.g., Ollama)")
    parser.add_argument("--no-confirm", action="store_true", help="Skip confirmation for destructive actions")
    parser.add_argument("--thinking", action="store_true", help="Enable extended thinking (Anthropic Claude only)")
    parser.add_argument("--thinking-budget", type=int, help="Extended thinking token budget (default: 10000)")
    parser.add_argument("--no-web-search", action="store_true", help="Disable Tavily web search tool")
    parser.add_argument("--no-memory", action="store_true", help="Disable long-term memory (ChromaDB)")
    parser.add_argument("--workdir", help="Working directory for file operations (default: cwd)")
    parser.add_argument("--task", help="Run a single task and exit (CI mode)")
    parser.add_argument("--resume", help="Resume a session by ID")
    parser.add_argument("--a2a-port", type=int, help="A2A server port (default: 8000)")
    parser.add_argument("--no-a2a", action="store_true", help="Disable A2A server endpoint")
    return parser.parse_args()


async def main_async():
    args = parse_args()

    # Apply overrides from CLI to environment variables before loading config
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

    try:
        config = Config.load()
    except ConfigError as e:
        UI.print_error(str(e))
        sys.exit(1)

    try:
        config.validate_api_key()
    except ConfigError as e:
        UI.print_error(str(e))
        sys.exit(1)

    # Initialize Provider
    provider = create_provider(config)

    # Initialize Context and Registry
    from agent.context import RepoContext
    repo_context = RepoContext(config.workdir)
    registry = ToolRegistry(config, _context=repo_context)

    # Initialize MCP Manager
    mcp_config_path = Path("mcp_servers.json")
    if not mcp_config_path.exists():
        # Fallback to absolute path relative to main.py
        mcp_config_path = Path(__file__).parent / "mcp_servers.json"
    
    mcp_manager = MCPManager(mcp_config_path)
    await mcp_manager.connect_all(registry)

    # Initialize A2A Server
    a2a_app.state.config = config
    a2a_app.state.registry = registry
    
    import uvicorn
    a2a_server_config = uvicorn.Config(
        app=a2a_app,
        host="0.0.0.0",
        port=config.a2a_port,
        log_level="error",
    )
    a2a_server = uvicorn.Server(a2a_server_config)
    a2a_task = asyncio.create_task(a2a_server.serve())

    # Initialize History
    history = HistoryManager()
    session_id = args.resume or datetime.now().strftime("%Y%m%d_%H%M%S")
    session_file = config.sessions_dir / f"{session_id}.json"

    if args.resume:
        if session_file.exists():
            history.load(session_file)
            UI.print_info(f"Resumed session {session_id}")
        else:
            UI.print_error(f"Session {session_id} not found at {session_file}")
            sys.exit(1)
    else:
        UI.print_info(f"New session: {session_id}")

    # Single task mode (CI)
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
        a2a_server.should_exit = True
        await a2a_task
        await mcp_manager.close()
        sys.exit(0)

    # Interactive REPL
    session = PromptSession()
    UI.print_info("DevPilot is ready. Type your task or 'exit' to quit.")

    while True:
        try:
            with patch_stdout():
                user_input = await session.prompt_async("🚀 > ")
        except (EOFError, KeyboardInterrupt):
            break

        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break

        history.append(provider.make_user_message(user_input))

        await run_agent_loop(
            provider=provider,
            registry=registry,
            history=history,
            config=config,
            max_iterations=config.max_iterations,
            context=repo_context,
        )

        history.save(session_file)

    a2a_server.should_exit = True
    await a2a_task
    await mcp_manager.close()
    UI.print_info("Goodbye!")


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
