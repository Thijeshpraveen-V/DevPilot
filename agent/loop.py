"""
agent/loop.py
─────────────
The core agentic loop.
"""

from __future__ import annotations

from agent.config import Config
from agent.history import HistoryManager
from agent.providers.base import BaseProvider
from agent.tools import ToolRegistry
from agent.ui import UI


async def run_agent_loop(
    provider: BaseProvider,
    registry: ToolRegistry,
    history: HistoryManager,
    config: Config,
    max_iterations: int = 50,
    context=None,
) -> None:
    """
    Executes the agentic loop until the model stops returning tool_uses or
    max_iterations is reached.

    Uses chat_stream() by default so tokens are printed in real time.
    Falls back transparently for providers/modes that don't support streaming
    (e.g. extended thinking).
    """
    heal_attempts = 0

    for iteration in range(max_iterations):
        messages = history.get_messages()
        tools = registry.schemas

        # Build system prompt, injecting repo context awareness if available
        system: str | None = None
        if context is not None:
            ctx_block = context.build_context_block()
            if ctx_block:
                system = (
                    "You are DevPilot, an expert AI coding agent running in a terminal.\n\n"
                    f"## Session Context\n{ctx_block}"
                )

        try:
            # chat_stream() prints text tokens live and returns the full response.
            # For extended thinking or providers without streaming it falls back to chat().
            response = await provider.chat_stream(messages, tools, system=system)
        except Exception as e:
            UI.print_error(f"Provider error: {e}")
            break

        # Append the assistant's message to history
        history.append(response.assistant_message)

        # UI: render extended thinking if present (Anthropic only; non-streaming path)
        if response.thinking:
            UI.print_thinking_block(response.thinking)

        # UI: print assistant text only when NOT already streamed live.
        if response.text and not response.streamed_text:
            UI.print_assistant_message(response.text)

        if not response.has_tool_uses:
            # The model is done
            break

        should_break_outer = False

        for tool_use in response.tool_uses:
            UI.print_tool_call(tool_use.name, tool_use.input)

            tool_result = await registry.execute(tool_use.name, tool_use.input)

            UI.print_tool_result(tool_use.name, tool_result.output, tool_result.is_error)

            # Format and append tool result message
            tool_msg = provider.make_tool_result_message(
                tool_use_id=tool_use.id,
                content=tool_result.output,
                is_error=tool_result.is_error,
            )
            history.append(tool_msg)
            
            if tool_result.is_error:
                heal_attempts += 1
                if heal_attempts >= 3:
                    UI.print_error("Too many consecutive tool errors (>= 3). Aborting loop to prevent infinite retries.")
                    should_break_outer = True
                    break
                # Inject explicit user prod to fix for this specific tool
                history.append(provider.make_user_message(
                    f"Tool '{tool_use.name}' failed with: {tool_result.output}\n"
                    "Please analyze the error, fix the underlying issue, and retry."
                ))
            else:
                heal_attempts = 0

        if should_break_outer:
            break

    else:
        UI.print_error(f"Max iterations ({max_iterations}) reached. Terminating loop.")
