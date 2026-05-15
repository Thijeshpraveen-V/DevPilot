"""
agent/a2a_server.py
───────────────────
FastAPI server implementing the Agent-to-Agent (A2A) protocol.
Handles incoming task delegation requests and streams results via SSE.
"""

import asyncio
import uuid
from typing import Any, AsyncGenerator

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from agent.config import Config
from agent.history import HistoryManager
from agent.loop import run_agent_loop
from agent.providers.factory import create_provider
from agent.tools import ToolRegistry

app = FastAPI(title="DevPilot A2A Server")
security = HTTPBearer(auto_error=False)

# Global task queues for SSE streaming
# task_id -> asyncio.Queue
_task_queues: dict[str, asyncio.Queue] = {}

# We'll store config, registry, etc in app.state during startup
# app.state.config
# app.state.registry


class TaskRequest(BaseModel):
    prompt: str


def verify_token(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> None:
    config: Config = app.state.config
    if config.a2a_token:
        if not credentials or credentials.credentials != config.a2a_token:
            raise HTTPException(status_code=401, detail="Invalid or missing bearer token")


@app.get("/.well-known/agent.json")
async def get_agent_card() -> dict[str, Any]:
    """Return the A2A AgentCard describing this agent."""
    port = app.state.config.a2a_port
    return {
        "name": "DevPilot",
        "description": "AI-Powered Terminal Coding Agent",
        "protocols": ["A2A v0.2"],
        "endpoints": {
            "tasks": f"http://localhost:{port}/tasks/send"
        }
    }


async def background_task_runner(task_id: str, prompt: str) -> None:
    """Executes the agentic loop in the background and pushes SSE events."""
    queue = _task_queues[task_id]
    await queue.put({"event": "status", "data": "working"})

    try:
        config: Config = app.state.config
        registry: ToolRegistry = app.state.registry
        
        # Instantiate a fresh provider and history for this task
        provider = create_provider(config)
        history = HistoryManager()
        
        # Add the prompt
        history.append(provider.make_user_message(prompt))
        
        # Run loop. We force no_confirm=True for background tasks to avoid hanging.
        # Use dataclasses.replace() so we don't duplicate every field.
        import dataclasses
        task_config = dataclasses.replace(config, no_confirm=True)
        
        await run_agent_loop(
            provider=provider,
            registry=registry,
            history=history,
            config=task_config,
            max_iterations=task_config.max_iterations,
        )
        
        # After loop finishes, the last message should be the assistant's final output
        messages = history.get_messages()
        if messages and messages[-1].get("role") == "assistant":
            content = messages[-1].get("content", "")
            if isinstance(content, list):
                # Canonical format: list of typed blocks — extract text blocks only
                final_text = " ".join(
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text"
                ).strip() or "Task completed."
            else:
                final_text = str(content)
        else:
            final_text = "Task completed, but no final response was generated."
            
        await queue.put({"event": "artifact", "data": final_text})
        await queue.put({"event": "status", "data": "completed"})
        
    except Exception as e:
        await queue.put({"event": "artifact", "data": f"Error: {e}"})
        await queue.put({"event": "status", "data": "failed"})
    finally:
        await queue.put(None)  # Sentinel to close stream


@app.post("/tasks/send", dependencies=[Depends(verify_token)])
async def create_task(request: TaskRequest) -> dict[str, str]:
    """Receive a task, spin up background executor, and return task_id."""
    task_id = str(uuid.uuid4())
    _task_queues[task_id] = asyncio.Queue()
    
    # Spin up background task
    asyncio.create_task(background_task_runner(task_id, request.prompt))
    
    return {"task_id": task_id}


@app.get("/tasks/{task_id}/stream", dependencies=[Depends(verify_token)])
async def stream_task(task_id: str, request: Request) -> EventSourceResponse:
    """Stream SSE events for a specific task."""
    if task_id not in _task_queues:
        raise HTTPException(status_code=404, detail="Task not found")
        
    queue = _task_queues[task_id]

    async def event_generator() -> AsyncGenerator[dict[str, str], None]:
        while True:
            if await request.is_disconnected():
                break
            
            event = await queue.get()
            if event is None:
                # Task finished
                del _task_queues[task_id]
                break
                
            yield event

    return EventSourceResponse(event_generator())
