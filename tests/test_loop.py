import pytest
from unittest.mock import AsyncMock, MagicMock
from agent.loop import run_agent_loop
from agent.history import HistoryManager
from agent.config import Config
from agent.providers.base import ProviderResponse, ToolUseBlock
from agent.tools import ToolResult

@pytest.fixture
def mock_config(tmp_path):
    return Config(
        provider="anthropic",
        model="test-model",
        base_url=None,
        max_iterations=5,
        no_confirm=True,
        a2a_port=8000,
        a2a_token=None,
        workdir=str(tmp_path),
        extended_thinking=False,
        thinking_budget=10000,
        web_search_enabled=False,
        memory_enabled=False,
        a2a_enabled=False,
        sessions_dir=tmp_path
    )

async def test_run_agent_loop_terminates_no_tools(mock_config):
    provider = MagicMock()
    provider.chat_stream = AsyncMock(return_value=ProviderResponse(
        text="Hello there!",
        tool_uses=[],
        stop_reason="end_turn",
        assistant_message={"role": "assistant", "content": "Hello there!"}
    ))
    
    registry = MagicMock()
    registry.schemas = []
    
    history = HistoryManager()
    
    await run_agent_loop(
        provider=provider,
        registry=registry,
        history=history,
        config=mock_config,
        max_iterations=5
    )
    
    assert provider.chat_stream.call_count == 1
    assert len(history.get_messages()) == 1

async def test_run_agent_loop_with_tool_call(mock_config):
    provider = MagicMock()
    
    # First turn: model calls a tool
    resp1 = ProviderResponse(
        text="I will use a tool.",
        tool_uses=[ToolUseBlock(id="t1", name="read_file", input={"path": "test.txt"})],
        stop_reason="tool_use",
        assistant_message={"role": "assistant", "content": "I will use a tool."}
    )
    # Second turn: model answers
    resp2 = ProviderResponse(
        text="Tool finished.",
        tool_uses=[],
        stop_reason="end_turn",
        assistant_message={"role": "assistant", "content": "Tool finished."}
    )
    provider.chat_stream = AsyncMock(side_effect=[resp1, resp2])
    provider.make_tool_result_message = MagicMock(return_value={"role": "user", "content": "mocked result"})
    
    registry = MagicMock()
    registry.schemas = []
    registry.execute = AsyncMock(return_value=ToolResult(output="file contents", is_error=False))
    
    history = HistoryManager()
    
    await run_agent_loop(
        provider=provider,
        registry=registry,
        history=history,
        config=mock_config,
        max_iterations=5
    )
    
    assert provider.chat_stream.call_count == 2
    assert registry.execute.call_count == 1
    # History should have: [resp1_assistant, tool_result, resp2_assistant]
    msgs = history.get_messages()
    assert len(msgs) == 3
