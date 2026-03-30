"""Gemini Live API — LiveKit token vending for Gemini voice agents."""

import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from livekit.api import AccessToken, CreateRoomRequest, LiveKitAPI, VideoGrants
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.api.settings import get_user_api_keys
from app.core.auth import VerifiedUser, user_id_to_uuid
from app.core.config import settings
from app.db.session import get_db
from app.models.agent import Agent
from app.models.workspace import AgentWorkspace, Workspace
from app.services.gpt_realtime import build_instructions_with_language
from app.services.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1/gemini", tags=["gemini"])
logger = structlog.get_logger()


async def _get_gemini_agent(agent_id: uuid.UUID, db: AsyncSession) -> Agent:
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
    if not agent.is_active:
        raise HTTPException(status_code=400, detail="Agent is not active")
    if agent.pricing_tier not in ("premium", "premium-mini"):
        raise HTTPException(status_code=400, detail="Gemini Live requires premium tier")
    provider = (agent.provider_config or {}).get("provider", "openai")
    if provider != "gemini-live":
        raise HTTPException(status_code=400, detail="Agent is not configured for Gemini Live")
    return agent


async def _get_google_api_key(
    user_uuid: uuid.UUID,
    workspace_uuid: uuid.UUID | None,
    db: AsyncSession,
) -> str:
    user_settings = await get_user_api_keys(user_uuid, db, workspace_id=workspace_uuid)
    if user_settings and user_settings.google_api_key:
        return user_settings.google_api_key
    raise HTTPException(
        status_code=400,
        detail="Google API key not configured. Please add it in Settings > API Keys.",
    )


async def _create_room_with_metadata(room_name: str, metadata: str) -> None:
    """Create a LiveKit room with agent config metadata."""
    async with LiveKitAPI(
        settings.LIVEKIT_URL, settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET
    ) as lk:
        await lk.room.create_room(CreateRoomRequest(name=room_name, metadata=metadata))


def _create_livekit_token(room_name: str, participant_identity: str) -> str:
    token = (
        AccessToken(settings.LIVEKIT_API_KEY, settings.LIVEKIT_API_SECRET)
        .with_identity(participant_identity)
        .with_name(participant_identity)
        .with_grants(VideoGrants(room_join=True, room=room_name))
    )
    return token.to_jwt()


@router.get("/token/{agent_id}")
async def get_gemini_token(
    agent_id: str,
    workspace_id: str,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Vend a LiveKit room token for a Gemini Live voice session."""
    user_id = current_user.id
    user_uuid = user_id_to_uuid(user_id)
    token_logger = logger.bind(endpoint="gemini_token", agent_id=agent_id)

    try:
        agent_uuid = uuid.UUID(agent_id)
        workspace_uuid = uuid.UUID(workspace_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid agent or workspace ID format") from e

    agent = await _get_gemini_agent(agent_uuid, db)

    ws_check = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.agent_id == agent_uuid,
            AgentWorkspace.workspace_id == workspace_uuid,
        )
    )
    if not ws_check.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Agent not authorized for this workspace")

    google_api_key = await _get_google_api_key(user_uuid, workspace_uuid, db)

    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_uuid))
    workspace = ws_result.scalar_one_or_none()
    workspace_timezone = (
        workspace.settings.get("timezone", "UTC") if workspace and workspace.settings else "UTC"
    )

    enabled_tools = agent.enabled_tools or []
    instructions = build_instructions_with_language(
        agent.system_prompt or "You are a helpful voice assistant.",
        agent.language,
        enabled_tools=enabled_tools,
        timezone=workspace_timezone,
        use_best_practices=agent.use_best_practices,
    )

    integrations = await get_workspace_integrations(user_uuid, workspace_uuid, db)
    tool_registry = ToolRegistry(
        db,
        user_id,
        integrations=integrations,
        workspace_id=workspace_uuid,
        agent_id=agent.id,
        openai_api_key=None,
        tool_configs=agent.tool_configs or {},
    )
    tools = tool_registry.get_all_tool_definitions(enabled_tools, agent.enabled_tool_ids)

    room_name = f"gemini-{agent_id}-{uuid.uuid4().hex[:8]}"
    participant_identity = f"user-{user_id}"

    categorize_tree_name = (agent.tool_configs or {}).get("categorize", {}).get("tree_name", "")

    room_metadata = json.dumps(
        {
            "agent_id": str(agent.id),
            "workspace_id": workspace_id,
            "google_api_key": google_api_key,
            "instructions": instructions,
            "voice": agent.voice or "Puck",
            "model": (agent.provider_config or {}).get("model", "gemini-3.1-flash-live-preview"),
            "temperature": agent.temperature,
            "initial_greeting": agent.initial_greeting or "",
            "tools": tools,
            "categorize_tree_name": categorize_tree_name,
        }
    )

    await _create_room_with_metadata(room_name, room_metadata)

    token = _create_livekit_token(room_name, participant_identity)

    token_logger.info("gemini_token_created", room=room_name, tool_count=len(tools))

    return {
        "livekit_url": settings.LIVEKIT_URL,
        "token": token,
        "room_name": room_name,
        "agent": {
            "id": str(agent.id),
            "name": agent.name,
            "voice": agent.voice or "Puck",
            "language": agent.language,
            "initial_greeting": agent.initial_greeting,
        },
        "tools": tools,
    }
