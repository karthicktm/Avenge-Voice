import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from app.services.workflow_generator import (
    GenerateRequest,
    _strip_fences,
    generate_workflow,
)


def _node(id_: str, type_: str = "transfer") -> dict:
    return {
        "id": id_,
        "type": type_,
        "label": "Test",
        "config": {},
        "position": {"x": 400, "y": 50},
    }


def _edge(id_: str, from_: str, to_: str) -> dict:
    return {
        "id": id_,
        "from": from_,
        "to": to_,
        "sourceHandle": None,
        "condition": None,
        "label": None,
    }


def test_strip_fences_plain():
    assert _strip_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_block():
    assert _strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_strip_fences_plain_block():
    assert _strip_fences('```\n{"a": 1}\n```') == '{"a": 1}'


@pytest.mark.asyncio
async def test_generate_single_node():
    """Returns intent=node with one node and no edges; IDs replaced with UUIDs."""
    payload = json.dumps({"intent": "node", "nodes": [_node("n1")], "edges": []})
    with patch("app.services.workflow_generator.call_llm", new=AsyncMock(return_value=payload)):
        result = await generate_workflow(
            GenerateRequest(
                prompt="add a transfer node", provider="openai", model="gpt-4o-mini", api_key="k"
            )
        )
    assert result.intent == "node"
    assert len(result.nodes) == 1
    assert len(result.edges) == 0
    uuid.UUID(result.nodes[0]["id"])  # must be a valid UUID, not "n1"


@pytest.mark.asyncio
async def test_generate_full_workflow_remaps_ids():
    """All node IDs replaced with UUIDs; edge from/to updated to match."""
    payload = json.dumps(
        {
            "intent": "workflow",
            "nodes": [_node("n1", "entry"), _node("n2", "categorize"), _node("n3", "end_call")],
            "edges": [_edge("e1", "n1", "n2"), _edge("e2", "n2", "n3")],
        }
    )
    with patch("app.services.workflow_generator.call_llm", new=AsyncMock(return_value=payload)):
        result = await generate_workflow(
            GenerateRequest(
                prompt="build a workflow",
                provider="anthropic",
                model="claude-haiku-4-5-20251001",
                api_key="k",
            )
        )
    assert result.intent == "workflow"
    assert len(result.nodes) == 3
    assert len(result.edges) == 2
    node_ids = {n["id"] for n in result.nodes}
    for edge in result.edges:
        assert edge["from"] in node_ids, "edge.from must reference a remapped node id"
        assert edge["to"] in node_ids, "edge.to must reference a remapped node id"
    for n in result.nodes:
        uuid.UUID(n["id"])


@pytest.mark.asyncio
async def test_generate_strips_markdown_fences():
    """Parser handles LLM responses wrapped in markdown code fences."""
    inner = json.dumps({"intent": "node", "nodes": [_node("n1", "end_call")], "edges": []})
    payload = f"```json\n{inner}\n```"
    with patch("app.services.workflow_generator.call_llm", new=AsyncMock(return_value=payload)):
        result = await generate_workflow(
            GenerateRequest(
                prompt="add end call", provider="google", model="gemini-2.0-flash", api_key="k"
            )
        )
    assert result.intent == "node"
    assert result.nodes[0]["type"] == "end_call"


@pytest.mark.asyncio
async def test_generate_includes_agent_context_in_prompt():
    """When agent_context is set, it is prepended to the user prompt sent to the LLM."""
    payload = json.dumps({"intent": "node", "nodes": [_node("n1")], "edges": []})
    captured: list[str] = []

    async def mock_llm(config, system, user, max_tokens=10):
        captured.append(user)
        return payload

    with patch("app.services.workflow_generator.call_llm", new=mock_llm):
        await generate_workflow(
            GenerateRequest(
                prompt="add a transfer node",
                provider="openai",
                model="gpt-4o-mini",
                api_key="k",
                agent_context="Name: Dental Receptionist\nIntegrations: google_calendar, crm",
            )
        )
    assert "Dental Receptionist" in captured[0]
    assert "add a transfer node" in captured[0]
