"""Internal API endpoints for the Gemini agent worker.

Secured with X-Internal-Secret header. NOT exposed to public internet.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.api.settings import get_user_api_keys
from app.core.config import settings
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call_record import CallRecord
from app.models.phone_number import PhoneNumber
from app.models.workspace import AgentWorkspace
from app.services.tools.registry import ToolRegistry

router = APIRouter(prefix="/internal", tags=["internal"])
logger = structlog.get_logger()

# Sentinel UUID used when no real user ID is available (internal/system calls)
_SYSTEM_USER_UUID = uuid.UUID(int=0)


def _verify_internal_secret(x_internal_secret: str = Header(...)) -> None:
    if x_internal_secret != settings.INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid internal secret")


async def _get_agent_with_workspace(
    agent_id: uuid.UUID, workspace_id: uuid.UUID, db: AsyncSession
) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    ws_check = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.agent_id == agent_id,
            AgentWorkspace.workspace_id == workspace_id,
        )
    )
    if not ws_check.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Agent not in workspace")
    return agent


class ExecuteToolRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any]
    workspace_id: str
    user_id: int = 0


class SaveTranscriptRequest(BaseModel):
    session_id: str
    transcript: str
    duration_seconds: int = 0
    provider: str = "gemini-live"


@router.post("/tools/{agent_id}/execute", dependencies=[Depends(_verify_internal_secret)])
async def execute_tool(
    agent_id: str,
    request: ExecuteToolRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Execute a tool call on behalf of the agent worker."""
    agent_uuid = uuid.UUID(agent_id)
    workspace_uuid = uuid.UUID(request.workspace_id)
    agent = await _get_agent_with_workspace(agent_uuid, workspace_uuid, db)

    integrations = await get_workspace_integrations(_SYSTEM_USER_UUID, workspace_uuid, db)

    # Fetch workspace OpenAI key — needed for embedding-based tools (lookup, categorize)
    openai_api_key: str | None = None
    ws_settings = await get_user_api_keys(_SYSTEM_USER_UUID, db, workspace_id=workspace_uuid)
    if ws_settings:
        openai_api_key = ws_settings.openai_api_key or settings.OPENAI_API_KEY
    else:
        openai_api_key = settings.OPENAI_API_KEY

    tool_registry = ToolRegistry(
        db,
        request.user_id,
        integrations=integrations,
        workspace_id=workspace_uuid,
        agent_id=agent.id,
        openai_api_key=openai_api_key,
        tool_configs=agent.tool_configs or {},
    )
    result = await tool_registry.execute_tool(request.tool_name, request.arguments)
    return {"result": result}


@router.post("/transcripts/{agent_id}", dependencies=[Depends(_verify_internal_secret)])
async def save_transcript(
    agent_id: str,
    workspace_id: str,
    request: SaveTranscriptRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Save a call transcript from the agent worker."""
    agent_uuid = uuid.UUID(agent_id)
    workspace_uuid = uuid.UUID(workspace_id)
    agent = await _get_agent_with_workspace(agent_uuid, workspace_uuid, db)

    ended_at = datetime.now(UTC)
    started_at = ended_at - timedelta(seconds=request.duration_seconds)

    call_record = CallRecord(
        user_id=_SYSTEM_USER_UUID,
        workspace_id=workspace_uuid,
        agent_id=agent.id,
        provider=request.provider,
        provider_call_id=request.session_id,
        direction="inbound",
        from_number="web",
        to_number="web",
        status="completed",
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=request.duration_seconds,
        transcript=request.transcript,
    )
    db.add(call_record)
    await db.commit()
    await db.refresh(call_record)
    return {"success": True, "call_id": str(call_record.id)}


@router.get("/phone/{phone_number}", dependencies=[Depends(_verify_internal_secret)])
async def get_agent_for_phone(
    phone_number: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Look up which Gemini agent is assigned to a phone number (for SIP rooms)."""
    result = await db.execute(
        select(PhoneNumber).where(PhoneNumber.phone_number == phone_number)
    )
    phone = result.scalar_one_or_none()
    if not phone or not phone.assigned_agent_id:
        raise HTTPException(status_code=404, detail="No agent assigned to this number")

    agent_result = await db.execute(select(Agent).where(Agent.id == phone.assigned_agent_id))
    agent = agent_result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    provider = (agent.provider_config or {}).get("provider", "openai")
    if provider != "gemini-live":
        raise HTTPException(status_code=400, detail="Agent is not a Gemini Live agent")

    ws_result = await db.execute(
        select(AgentWorkspace).where(AgentWorkspace.agent_id == agent.id).limit(1)
    )
    ws = ws_result.scalar_one_or_none()

    return {
        "agent_id": str(agent.id),
        "workspace_id": str(ws.workspace_id) if ws else None,
    }
