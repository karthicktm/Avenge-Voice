"""Converts backend OpenAI-format tool definitions into LiveKit FunctionContext callables."""

from typing import Annotated, Any

import httpx
import structlog
from livekit.agents import llm

logger = structlog.get_logger()


def build_function_context(
    tools: list[dict[str, Any]],
    agent_id: str,
    workspace_id: str,
    backend_url: str,
    internal_secret: str,
) -> llm.FunctionContext:
    """Build a LiveKit FunctionContext from OpenAI-format tool definitions."""
    fnc_ctx = llm.FunctionContext()
    headers = {"X-Internal-Secret": internal_secret, "Content-Type": "application/json"}

    for tool_def in tools:
        name = tool_def.get("name", "")
        description = tool_def.get("description", "")
        properties = tool_def.get("parameters", {}).get("properties", {})
        required = set(tool_def.get("parameters", {}).get("required", []))

        if not name:
            continue

        async def _make_handler(
            _name: str = name,
            _agent_id: str = agent_id,
            _workspace_id: str = workspace_id,
            _backend_url: str = backend_url,
            _headers: dict = headers,
            **kwargs: Any,
        ) -> str:
            log = logger.bind(tool=_name)
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        f"{_backend_url}/internal/tools/{_agent_id}/execute",
                        json={"tool_name": _name, "arguments": kwargs, "workspace_id": _workspace_id},
                        headers=_headers,
                    )
                    resp.raise_for_status()
                    return str(resp.json().get("result", "Done"))
            except Exception as e:
                log.exception("tool_call_failed", error=str(e))
                return f"Tool {_name} failed: {e}"

        annotations: dict[str, Any] = {}
        for param_name, param_schema in properties.items():
            param_desc = param_schema.get("description", param_name)
            annotations[param_name] = Annotated[str, llm.TypeInfo(description=param_desc)]

        _make_handler.__name__ = name
        _make_handler.__doc__ = description
        _make_handler.__annotations__ = {**annotations, "return": str}

        fnc_ctx.ai_callable(name=name, description=description)(_make_handler)

    return fnc_ctx
