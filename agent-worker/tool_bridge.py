"""Converts backend OpenAI-format tool definitions into livekit-agents 1.x tool list."""

import asyncio
from typing import Any

import httpx
import structlog
from livekit.agents import llm

logger = structlog.get_logger()


def build_tools(
    tools: list[dict[str, Any]],
    agent_id: str,
    workspace_id: str,
    backend_url: str,
    internal_secret: str,
    end_call_event: "asyncio.Event | None" = None,
) -> list[Any]:
    """Build a list of livekit-agents tools from OpenAI-format tool definitions.

    Each tool uses llm.function_tool with raw_schema so livekit-agents sends
    the tool definition as-is to Gemini and forwards raw JSON arguments to
    our executor function.
    """
    headers = {"X-Internal-Secret": internal_secret, "Content-Type": "application/json"}
    result: list[Any] = []

    for tool_def in tools:
        name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        parameters = tool_def.get("parameters", {"type": "object", "properties": {}})

        if not name:
            continue

        # raw_schema must include "name" and "parameters" keys
        raw_schema = {
            "name": name,
            "description": description,
            "parameters": parameters,
        }

        # Capture loop variables via default args
        async def _execute(
            raw_arguments: str,
            _name: str = name,
            _agent_id: str = agent_id,
            _workspace_id: str = workspace_id,
            _backend_url: str = backend_url,
            _headers: dict = headers,
            _end_call_event: "asyncio.Event | None" = end_call_event,
        ) -> str:
            log = logger.bind(tool=_name)
            try:
                import json as _json
                # In livekit-agents 1.x, raw_arguments may be a dict or a JSON string
                if isinstance(raw_arguments, dict):
                    arguments = raw_arguments
                elif raw_arguments:
                    arguments = _json.loads(raw_arguments)
                else:
                    arguments = {}
                log.info("tool_call_input", arguments=arguments)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{_backend_url}/internal/tools/{_agent_id}/execute",
                        json={
                            "tool_name": _name,
                            "arguments": arguments,
                            "workspace_id": _workspace_id,
                        },
                        headers=_headers,
                    )
                    resp.raise_for_status()
                    resp_data = resp.json()
                    raw_result = resp_data.get("result", "Done")
                    # Detect end_call action before stringifying
                    if isinstance(raw_result, dict) and raw_result.get("action") == "end_call":
                        if _end_call_event:
                            _end_call_event.set()
                    result = str(raw_result)
                    log.info("tool_call_result", result=result[:300])
                    return result
            except Exception as e:
                log.exception("tool_call_failed", error=str(e))
                return f"Tool {_name} failed: {e}"

        _execute.__name__ = name

        tool = llm.function_tool(raw_schema=raw_schema)(_execute)
        result.append(tool)
        logger.info("tool_registered", name=name)

    return result
