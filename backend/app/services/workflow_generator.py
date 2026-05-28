"""AI-powered workflow generation from natural language prompts."""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import HTTPException

from app.services.workflow_engine.llm_client import LLMConfig, call_llm

_SYSTEM = """\
You are a workflow designer for a voice agent platform.
Given a user description (and optional agent context), return ONLY a JSON object — no markdown fences, no extra text.

RETURN FORMAT:
{
  "intent": "node" | "workflow",
  "nodes": [
    {"id": "n1", "type": "<type>", "label": "<label>", "config": {}, "position": {"x": 400, "y": 50}}
  ],
  "edges": [
    {"id": "e1", "from": "n1", "to": "n2", "sourceHandle": null, "condition": null, "label": null}
  ]
}

AVAILABLE NODE TYPES AND THEIR CONFIGS:
- entry: {} — workflow start (always first in a workflow)
- categorize: {"tree_name": "default", "llm_model": "gpt-4o-mini"} — classify caller intent
- condition: {"key": "action_type", "operator": "==", "value": "<string>"} — branch yes/no
- transfer: {"target_template": "<phone>", "label": "<name>"} — transfer call
- instruction: {"instruction_template": "<text to speak>"} — give caller information
- collect_email: {"prompt_template": "<question to ask>"} — collect email address
- sms: {"to_template": "{{caller_number}}", "body_template": "<message>"} — send SMS
- appointment: {"calendar_id": ""} — schedule appointment (use when agent has calendar integration)
- webhook: {"method": "POST", "url": "<url>", "body_template": "{}", "response_key": ""} — HTTP call
- voicemail: {"prompt": "<instruction>"} — take voicemail
- end_call: {} — terminate call
- lookup_transfer: {"phonebook_id": "", "fallback_number": ""} — phonebook lookup, then transfer call
- subagent: {"system_prompt": "", "voice": ""} — override agent prompt/model/voice for this step

CONTEXT VARIABLES (use {{variable}} in templates):
{{caller_number}}, {{label}}, {{code}}, {{action_type}}, {{transfer_target}}

LAYOUT RULES:
- entry node at x=400, y=50
- each successive row: y += 150
- sibling branches: x ± 200 from centre (x=400)
- condition node yes-edge: sourceHandle="yes", no-edge: sourceHandle="no"

INTENT RULES:
- Short, specific request ("add a transfer node"): intent="node", one node, empty edges array.
- Descriptive request ("build a clinic intake workflow"): intent="workflow", include entry + all nodes + edges.

When AGENT CONTEXT is provided in the request, use it to:
- Choose node types that match the agent's integrations (e.g. use appointment node when google_calendar is listed)
- Use the agent's system prompt purpose to write meaningful instruction_template and transfer label text
- Match category tree names to the agent's domain
- Reflect the agent's language in any text fields\
"""


@dataclass
class GenerateRequest:
    prompt: str
    provider: str
    model: str
    api_key: str
    agent_context: str = field(default="")


@dataclass
class GeneratedWorkflow:
    intent: Literal["node", "workflow"]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]


def _strip_fences(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```[a-z]*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()


def _remap_ids(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Replace short LLM-generated IDs with UUIDs to avoid canvas collisions."""
    id_map: dict[str, str] = {}
    for node in nodes:
        new_id = str(uuid.uuid4())
        id_map[node["id"]] = new_id
        node["id"] = new_id
    for edge in edges:
        edge["id"] = str(uuid.uuid4())
        edge["from"] = id_map.get(edge["from"], edge["from"])
        edge["to"] = id_map.get(edge["to"], edge["to"])


async def generate_workflow(req: GenerateRequest) -> GeneratedWorkflow:
    """Call the selected LLM and parse the response into workflow nodes and edges."""
    if req.agent_context:
        user_prompt = f"AGENT CONTEXT:\n{req.agent_context}\n\nREQUEST:\n{req.prompt}"
    else:
        user_prompt = req.prompt

    config = LLMConfig(provider=req.provider, model=req.model, api_key=req.api_key)
    raw = await call_llm(config, _SYSTEM, user_prompt, max_tokens=2000)
    try:
        data: dict[str, Any] = json.loads(_strip_fences(raw))
        nodes: list[dict[str, Any]] = data["nodes"]
        edges: list[dict[str, Any]] = data.get("edges", [])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(
            status_code=422,
            detail="LLM returned an unparseable response — try rephrasing your prompt",
        ) from exc
    _remap_ids(nodes, edges)
    return GeneratedWorkflow(intent=data["intent"], nodes=nodes, edges=edges)
