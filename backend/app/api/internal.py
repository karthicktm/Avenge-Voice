"""Internal API endpoints for the Gemini agent worker.

Secured with X-Internal-Secret header. NOT exposed to public internet.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.api.settings import get_user_api_keys
from app.core.auth import user_id_to_uuid
from app.core.config import settings
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call_record import CallRecord
from app.models.lookup import LookupCollection, LookupRecord
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

    # Resolve agent owner UUID once — used for integrations, API keys, and scoping.
    agent_user_uuid = user_id_to_uuid(agent.user_id)

    # Use the agent owner's UUID so user-scoped integrations (Resend, GHL, etc.) are found.
    integrations = await get_workspace_integrations(agent_user_uuid, workspace_uuid, db)

    # Fetch OpenAI key using the agent owner's user_id — needed for LLM-based tools (categorize, lookup LLM layer)
    openai_api_key: str | None = None
    ws_settings = await get_user_api_keys(agent_user_uuid, db, workspace_id=workspace_uuid)
    if ws_settings:
        openai_api_key = ws_settings.openai_api_key or settings.OPENAI_API_KEY
    else:
        openai_api_key = settings.OPENAI_API_KEY

    # Use agent owner's user_id so user-scoped collections/trees are found correctly.
    # request.user_id defaults to 0 (tool_bridge doesn't send it), which would miss
    # any collections/trees scoped by user_id rather than workspace_id.
    effective_user_id = agent.user_id if agent.user_id else request.user_id
    tool_registry = ToolRegistry(
        db,
        effective_user_id,
        integrations=integrations,
        workspace_id=workspace_uuid,
        agent_id=agent.id,
        openai_api_key=openai_api_key,
        tool_configs=agent.tool_configs or {},
    )

    # Pre-warm category trees before categorize calls — same as GPT Realtime path.
    # This loads all tree nodes into memory so LLM traversal (English→Swedish matching)
    # can run without per-node DB queries.
    if request.tool_name == "categorize":
        import contextlib

        async with contextlib.AsyncExitStack() as stack:
            stack.enter_context(contextlib.suppress(Exception))
            await tool_registry.prewarm_category_trees()

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
    result = await db.execute(select(PhoneNumber).where(PhoneNumber.phone_number == phone_number))
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


@router.get("/debug/lookup/{agent_id}", dependencies=[Depends(_verify_internal_secret)])
async def debug_lookup_scope(
    agent_id: str,
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Debug endpoint: show what lookup collections and records are visible for an agent."""
    agent_uuid = uuid.UUID(agent_id)
    workspace_uuid = uuid.UUID(workspace_id)
    agent = await _get_agent_with_workspace(agent_uuid, workspace_uuid, db)

    # Fetch OpenAI key status
    agent_user_uuid = user_id_to_uuid(agent.user_id)
    ws_settings = await get_user_api_keys(agent_user_uuid, db, workspace_id=workspace_uuid)
    openai_key_source = "none"
    if ws_settings and ws_settings.openai_api_key:
        openai_key_source = "workspace_settings"
    elif settings.OPENAI_API_KEY:
        openai_key_source = "system_env"

    # Count collections visible under OR(workspace_id, user_id) scope
    coll_stmt = (
        select(
            LookupCollection.id,
            LookupCollection.name,
            LookupCollection.workspace_id,
            LookupCollection.user_id,
            LookupCollection.is_active,
            func.count(LookupRecord.id).label("record_count"),
        )
        .outerjoin(LookupRecord, LookupRecord.collection_id == LookupCollection.id)
        .group_by(
            LookupCollection.id,
            LookupCollection.name,
            LookupCollection.workspace_id,
            LookupCollection.user_id,
            LookupCollection.is_active,
        )
        .where(
            or_(
                LookupCollection.workspace_id == workspace_uuid,
                LookupCollection.user_id == agent.user_id,
            )
        )
    )
    result = await db.execute(coll_stmt)
    collections = [
        {
            "id": str(r.id),
            "name": r.name,
            "workspace_id": str(r.workspace_id) if r.workspace_id else None,
            "user_id": r.user_id,
            "is_active": r.is_active,
            "record_count": r.record_count,
        }
        for r in result.fetchall()
    ]

    return {
        "agent_id": agent_id,
        "agent_user_id": agent.user_id,
        "workspace_id": workspace_id,
        "tool_configs": agent.tool_configs,
        "openai_key_source": openai_key_source,
        "visible_collections": collections,
        "total_collections": len(collections),
    }


class EnrichTreeRequest(BaseModel):
    workspace_id: str
    tree_name: str
    user_id: int = 1
    openai_api_key: str | None = None
    overwrite: bool = False


@router.post("/category-trees/enrich", dependencies=[Depends(_verify_internal_secret)])
async def enrich_category_tree(
    body: EnrichTreeRequest,
) -> dict[str, Any]:
    """Trigger metadata enrichment (including action_type) for a category tree.

    Runs synchronously — may take several minutes for large trees.
    Uses the workspace-scoped OpenAI key (same as the normal enrich endpoint).
    """
    from app.core.config import settings as app_settings
    from app.services.category_discovery_worker import _get_openai_key
    from app.services.category_enrichment import enrich_example_queries

    workspace_uuid = uuid.UUID(body.workspace_id)
    openai_api_key = body.openai_api_key
    if not openai_api_key:
        openai_api_key = await _get_openai_key(body.user_id, workspace_uuid)
    if not openai_api_key:
        openai_api_key = app_settings.OPENAI_API_KEY
    if not openai_api_key:
        raise HTTPException(status_code=500, detail="No OPENAI_API_KEY configured")

    return await enrich_example_queries(
        workspace_id=workspace_uuid,
        tree_name=body.tree_name,
        user_id=body.user_id,
        openai_api_key=openai_api_key,
        overwrite=body.overwrite,
    )
