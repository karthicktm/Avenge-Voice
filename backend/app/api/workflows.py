"""Workflows API — CRUD for workflow graphs and agent attachment."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import VerifiedUser
from app.db.session import get_db
from app.models.agent import Agent
from app.models.workflow import Workflow

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
