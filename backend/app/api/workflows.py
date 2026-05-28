"""Workflows API — CRUD for workflow graphs and agent attachment."""

import uuid
from typing import Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.settings import get_user_api_keys
from app.core.auth import VerifiedUser, user_id_to_uuid
from app.core.config import settings as app_settings
from app.db.session import get_db
from app.models.agent import Agent
from app.models.workflow import Workflow
from app.models.workspace import Workspace
from app.services.workflow_generator import GeneratedWorkflow as _GeneratedWorkflow
from app.services.workflow_generator import GenerateRequest, generate_workflow

logger = structlog.get_logger()

router = APIRouter(prefix="/workflows", tags=["workflows"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class WorkflowCreate(BaseModel):
    workspace_id: uuid.UUID
    name: str
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []


class WorkflowUpdate(BaseModel):
    name: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class WorkflowOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]

    model_config = {"from_attributes": True}


class GenerateWorkflowIn(BaseModel):
    workspace_id: uuid.UUID
    workflow_id: uuid.UUID
    prompt: str
    provider: Literal["openai", "anthropic", "google"] = "openai"
    model: str = "gpt-4o-mini"


class GenerateWorkflowOut(BaseModel):
    intent: Literal["node", "workflow"]
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    agent_name: str | None = None  # echoed back so the UI can confirm context was used


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.post("", response_model=WorkflowOut)
async def create_workflow(
    body: WorkflowCreate,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    wf = Workflow(
        workspace_id=body.workspace_id,
        name=body.name,
        nodes=body.nodes,
        edges=body.edges,
    )
    db.add(wf)
    await db.commit()
    await db.refresh(wf)
    logger.info("workflow_created", id=str(wf.id), user_id=user.id)
    return wf


@router.get("", response_model=list[WorkflowOut])
async def list_workflows(
    workspace_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> list[Workflow]:
    result = await db.execute(
        select(Workflow)
        .where(Workflow.workspace_id == workspace_id)
        .order_by(Workflow.created_at.desc())
    )
    return list(result.scalars().all())


_MAX_SYSTEM_PROMPT_CHARS = 1500


def _build_agent_context(agent: Agent) -> str:
    """Build a detailed context string from agent configuration for the LLM prompt.

    Includes full system prompt, all enabled integrations, and per-integration
    tool IDs so the generator can select appropriate node types.
    """
    parts: list[str] = [f"Name: {agent.name}"]

    if agent.description:
        parts.append(f"Description: {agent.description}")

    if agent.system_prompt:
        prompt_text = agent.system_prompt[:_MAX_SYSTEM_PROMPT_CHARS]
        if len(agent.system_prompt) > _MAX_SYSTEM_PROMPT_CHARS:
            prompt_text += "\n[truncated]"
        parts.append(f"System prompt:\n{prompt_text}")

    if agent.initial_greeting:
        parts.append(f"Initial greeting: {agent.initial_greeting}")

    if agent.enabled_tool_ids:
        tool_lines = []
        for integration_id, tool_ids in agent.enabled_tool_ids.items():
            if tool_ids:
                tool_lines.append(f"  - {integration_id}: {', '.join(tool_ids)}")
            else:
                tool_lines.append(f"  - {integration_id}")
        if tool_lines:
            parts.append("Integrations and tools:\n" + "\n".join(tool_lines))
    elif agent.enabled_tools:
        parts.append(f"Integrations: {', '.join(agent.enabled_tools)}")

    parts.append(f"Language: {agent.language}")
    parts.append(f"Pricing tier: {agent.pricing_tier}")

    return "\n".join(parts)


@router.post("/generate", response_model=GenerateWorkflowOut)
async def generate_workflow_endpoint(
    body: GenerateWorkflowIn,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> GenerateWorkflowOut:
    user_uuid = user_id_to_uuid(user.id)

    ws_check = await db.execute(
        select(Workspace).where(
            Workspace.id == body.workspace_id,
            Workspace.user_id == user.id,
        )
    )
    if not ws_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Workspace not found")

    user_settings = await get_user_api_keys(user_uuid, db, workspace_id=body.workspace_id)

    if body.provider == "anthropic":
        api_key = app_settings.ANTHROPIC_API_KEY or ""
    elif body.provider == "google":
        api_key = (user_settings.google_api_key if user_settings else None) or ""
    else:
        api_key = (
            (user_settings.openai_api_key if user_settings else None)
            or app_settings.OPENAI_API_KEY
            or ""
        )

    if not api_key:
        raise HTTPException(status_code=400, detail=f"No {body.provider} API key configured")

    wf_check = await db.execute(
        select(Workflow).where(
            Workflow.id == body.workflow_id,
            Workflow.workspace_id == body.workspace_id,
        )
    )
    if not wf_check.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Workflow not found")

    agent_result = await db.execute(select(Agent).where(Agent.workflow_id == body.workflow_id))
    agent = agent_result.scalar_one_or_none()
    agent_context = _build_agent_context(agent) if agent else ""

    result: _GeneratedWorkflow = await generate_workflow(
        GenerateRequest(
            prompt=body.prompt,
            provider=body.provider,
            model=body.model,
            api_key=api_key,
            agent_context=agent_context,
        )
    )
    return GenerateWorkflowOut(
        intent=result.intent,
        nodes=result.nodes,
        edges=result.edges,
        agent_name=agent.name if agent else None,
    )


@router.get("/{workflow_id}", response_model=WorkflowOut)
async def get_workflow(
    workflow_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.put("/{workflow_id}", response_model=WorkflowOut)
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> Workflow:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    if body.name is not None:
        wf.name = body.name
    if body.nodes is not None:
        wf.nodes = body.nodes
    if body.edges is not None:
        wf.edges = body.edges
    await db.commit()
    await db.refresh(wf)
    return wf


@router.delete("/{workflow_id}", status_code=204)
async def delete_workflow(
    workflow_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await db.delete(wf)
    await db.commit()


@router.post("/{workflow_id}/attach/{agent_id}", response_model=dict[str, str])
async def attach_workflow(
    workflow_id: uuid.UUID,
    agent_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.workflow_id = workflow_id
    await db.commit()
    logger.info("workflow_attached", workflow_id=str(workflow_id), agent_id=str(agent_id))
    return {"status": "attached", "agent_id": str(agent_id), "workflow_id": str(workflow_id)}


@router.post("/{workflow_id}/detach/{agent_id}", response_model=dict[str, str])
async def detach_workflow(
    workflow_id: uuid.UUID,
    agent_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if str(agent.workflow_id) != str(workflow_id):
        raise HTTPException(status_code=400, detail="Workflow not attached to this agent")
    agent.workflow_id = None
    await db.commit()
    return {"status": "detached", "agent_id": str(agent_id)}
