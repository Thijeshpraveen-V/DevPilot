"""
agent/a2a_client.py
───────────────────
A2A client implementation. Discovers peer agents via their AgentCard
and delegates tasks to them using HTTP SSE.
"""

import json
from typing import Any

import httpx

from agent.tools import ToolResult
from agent.ui import UI


async def _fetch_agent_card(peer_url: str, token: str | None) -> dict[str, Any]:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        
    card_url = f"{peer_url.rstrip('/')}/.well-known/agent.json"
    async with httpx.AsyncClient() as client:
        response = await client.get(card_url, headers=headers)
        response.raise_for_status()
        return response.json()


async def delegate_task_to_peer(peer_url: str, prompt: str, token: str | None = None) -> ToolResult:
    """
    Delegate a task to an A2A peer agent.
    1. Fetch AgentCard to find the /tasks/send endpoint.
    2. POST the task.
    3. Stream SSE events to get the artifact.
    """
    try:
        card = await _fetch_agent_card(peer_url, token)
    except Exception as e:
        return ToolResult(f"Failed to fetch AgentCard from {peer_url}: {e}", is_error=True)

    endpoints = card.get("endpoints", {})
    send_url = endpoints.get("tasks")
    if not send_url:
        return ToolResult(f"Peer AgentCard missing 'tasks' endpoint. Card: {card}", is_error=True)

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        async with httpx.AsyncClient() as client:
            # Send task
            response = await client.post(send_url, json={"prompt": prompt}, headers=headers)
            response.raise_for_status()
            data = response.json()
            task_id = data.get("task_id")
            
            if not task_id:
                return ToolResult("Peer did not return a task_id.", is_error=True)
                
            base = send_url[: send_url.rfind("/send")]
            stream_url = f"{base}/{task_id}/stream"
            
            # Read SSE
            UI.print_info(f"Delegated task {task_id} to {peer_url}. Waiting for results...")
            
            final_artifact = ""
            status = "working"
            
            async with client.stream("GET", stream_url, headers=headers) as stream_resp:
                stream_resp.raise_for_status()
                async for line in stream_resp.aiter_lines():
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith("event: "):
                        current_event = line[7:]
                    elif line.startswith("data: "):
                        data_payload = line[6:]
                        if "current_event" in locals():
                            if current_event == "artifact":
                                final_artifact += data_payload + "\n"
                            elif current_event == "status":
                                status = data_payload
            
            if status == "failed":
                return ToolResult(f"Task failed on peer: {final_artifact}", is_error=True)
                
            return ToolResult(f"Task completed successfully by peer. Artifact:\n{final_artifact}", is_error=False)

    except Exception as e:
        return ToolResult(f"A2A connection error: {e}", is_error=True)


# The schema to expose this to the DevPilot ToolRegistry
A2A_DELEGATE_SCHEMA = {
    "name": "a2a_delegate_task",
    "description": (
        "Delegate a subtask to an external A2A (Agent-to-Agent) peer. "
        "Use this when you need help from a specialist agent or another node. "
        "Provide the base URL of the peer agent and the task prompt."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "peer_url": {
                "type": "string",
                "description": "Base URL of the peer agent (e.g., http://localhost:8001)"
            },
            "prompt": {
                "type": "string",
                "description": "The coding task or instruction to delegate."
            },
            "token": {
                "type": "string",
                "description": "Optional Bearer token if the peer requires authentication."
            }
        },
        "required": ["peer_url", "prompt"]
    }
}
