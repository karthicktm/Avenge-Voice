"""LiveKit voice agent worker.

Each deployed agent runs this as a worker process. It:
- Connects to a LiveKit room when dispatched a job
- Loads agent config + tools from the database
- Uses OpenAI Realtime API for voice (gpt-4o-realtime)
- Bridges tool calls to the existing ToolRegistry
- Supports both Docker and Railway per-agent container deployment
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from typing import Any

import structlog
from livekit.agents import (  # type: ignore[import-not-found]
    Agent,
    AgentSession,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    function_tool,
)
from livekit.agents.beta.tools import EndCallTool  # type: ignore[import-not-found]
from livekit.plugins.openai import realtime as lk_realtime  # type: ignore[import-not-found]
from livekit.plugins.openai.realtime import realtime_model as _lk_rm  # type: ignore[import-not-found]
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models.agent import Agent as AgentModel
from app.models.user_settings import UserSettings
from app.services.gpt_realtime import build_instructions_with_language
from app.services.tools.registry import ToolRegistry

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Database — reuse settings from app config (loads .env automatically)
# ---------------------------------------------------------------------------


def _make_engine() -> Any:
    from app.core.config import settings

    db_url = str(settings.DATABASE_URL)
    return create_async_engine(db_url, pool_size=3, max_overflow=5, pool_pre_ping=True)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        _make_engine(),
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


# Lazy init — engine is created on first use so import-time has no side effects
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = _make_session_factory()
    return _session_factory


# ---------------------------------------------------------------------------
# Agent model (per-room)
# ---------------------------------------------------------------------------

_AGENT_ID = os.environ.get("AGENT_ID")  # set when running per-agent container


def _realtime_model_for_tier(
    pricing_tier: str, agent_config: dict[str, Any]
) -> lk_realtime.RealtimeModel:
    """Build a LiveKit RealtimeModel from agent config."""
    from app.core.config import settings

    model_name = agent_config.get("llm_model", "gpt-realtime-1.5")
    voice = agent_config.get("voice", "shimmer")
    temperature = float(agent_config.get("temperature") or 0.6)

    turn_detection_mode = agent_config.get("turn_detection_mode", "normal")
    turn_detection: Any
    if turn_detection_mode == "disabled":
        turn_detection = None
    else:
        turn_detection = _lk_rm.TurnDetection(
            type="server_vad",
            threshold=agent_config.get("turn_detection_threshold") or 0.5,
            prefix_padding_ms=agent_config.get("turn_detection_prefix_padding_ms") or 300,
            silence_duration_ms=agent_config.get("turn_detection_silence_duration_ms") or 500,
        )

    return lk_realtime.RealtimeModel(
        model=model_name,
        voice=voice,
        temperature=temperature,
        turn_detection=turn_detection,
        api_key=agent_config.get("openai_api_key") or settings.OPENAI_API_KEY,
    )


def _build_dynamic_tools(
    tool_defs: list[dict[str, Any]],
    registry: ToolRegistry,
) -> list[Any]:
    """Convert OpenAI-format tool definitions into LiveKit function tools.

    Each tool is a thin wrapper that delegates to the existing ToolRegistry.
    We use raw_schema so the LLM sees the exact same schema as before.
    """
    tools = []

    for tool_def in tool_defs:
        name = tool_def.get("name", "")
        if not name:
            continue

        # raw_schema must have 'name' and 'parameters' at minimum
        raw: dict[str, Any] = {
            "name": name,
            "description": tool_def.get("description", ""),
            "parameters": tool_def.get("parameters", {"type": "object", "properties": {}}),
        }

        # Capture name and registry in closure.
        # raw_schema drives the schema sent to the LLM; the function
        # receives the parsed arguments as **kwargs at runtime.
        async def _dispatch(
            _name: str = name,
            _registry: ToolRegistry = registry,
            raw_arguments: dict[str, Any] | None = None,
        ) -> str:
            # For RawFunctionTool, LiveKit passes the parsed args as raw_arguments
            result = await _registry.execute_tool(_name, raw_arguments or {})
            return json.dumps(result)

        tool = function_tool(_dispatch, raw_schema=raw)
        tools.append(tool)

    return tools


class VoiceAgent(Agent):  # type: ignore[misc]
    """A LiveKit voice agent backed by OpenAI Realtime + our ToolRegistry."""

    def __init__(
        self,
        instructions: str,
        llm: lk_realtime.RealtimeModel,
        tools: list[Any],
        initial_greeting: str | None,
    ) -> None:
        super().__init__(
            instructions=instructions,
            llm=llm,
            tools=tools,
        )
        self._initial_greeting = initial_greeting

    async def on_enter(self) -> None:
        """Called when the agent enters the session (user joined the room)."""
        if self._initial_greeting:
            await asyncio.sleep(0.5)  # small pause before greeting
            await self.session.say(self._initial_greeting)


# ---------------------------------------------------------------------------
# Worker entrypoint
# ---------------------------------------------------------------------------


async def entrypoint(ctx: JobContext) -> None:  # noqa: PLR0915
    """Main entrypoint called by the LiveKit worker for each dispatched job."""
    log = logger.bind(room=ctx.room.name)
    log.info("livekit_agent_job_started")

    # Extract agent_id from room metadata or env (per-container mode).
    # ctx.job.room is the proto snapshot populated before connect(); ctx.room.metadata
    # is only available after ctx.connect() so we read from the job proto instead.
    agent_id_str: str | None = _AGENT_ID or ctx.job.room.metadata or None
    if not agent_id_str:
        log.error("no_agent_id_in_room_metadata_or_env")
        ctx.shutdown(reason="no agent_id")
        return

    try:
        agent_uuid = uuid.UUID(agent_id_str)
    except ValueError:
        log.exception("invalid_agent_id", value=agent_id_str)
        ctx.shutdown(reason="invalid agent_id")
        return

    log = log.bind(agent_id=agent_id_str)

    async with _get_session_factory()() as db:
        # Load agent from DB
        result = await db.execute(select(AgentModel).where(AgentModel.id == agent_uuid))
        agent = result.scalar_one_or_none()

        if not agent:
            log.error("agent_not_found")
            ctx.shutdown(reason="agent not found")
            return

        if not agent.is_active:
            log.warning("agent_not_active")
            ctx.shutdown(reason="agent not active")
            return

        log.info("agent_loaded", name=agent.name, tier=agent.pricing_tier)

        # Build instructions
        instructions = build_instructions_with_language(
            system_prompt=agent.system_prompt or "You are a helpful voice assistant.",
            language=agent.language,
            enabled_tools=agent.enabled_tools or [],
            timezone="UTC",
            use_best_practices=agent.use_best_practices,
        )

        # Resolve OpenAI API key: agent provider_config → workspace settings → env
        from sqlalchemy import and_

        from app.core.auth import user_id_to_uuid
        from app.core.config import settings as app_settings
        from app.models.workspace import AgentWorkspace

        user_uuid = user_id_to_uuid(agent.user_id)

        # Get the agent's workspace
        ws_row = await db.execute(
            select(AgentWorkspace.workspace_id).where(AgentWorkspace.agent_id == agent.id).limit(1)
        )
        workspace_id = ws_row.scalar_one_or_none()

        # Look up API keys for that workspace
        user_settings_result = await db.execute(
            select(UserSettings).where(
                and_(
                    UserSettings.user_id == user_uuid,
                    UserSettings.workspace_id == workspace_id,
                )
            )
        )
        user_settings = user_settings_result.scalar_one_or_none()

        openai_api_key: str | None = (
            agent.provider_config.get("openai_api_key")
            or (user_settings.openai_api_key if user_settings else None)
            or app_settings.OPENAI_API_KEY
        )

        if not openai_api_key:
            log.error("no_openai_api_key")
            ctx.shutdown(reason="no openai api key")
            return

        # Load workspace integrations (Google Calendar, CRM, etc.)
        from app.api.integrations import get_workspace_integrations

        integrations: dict[str, Any] = {}
        if workspace_id is not None:
            integrations = await get_workspace_integrations(user_uuid, workspace_id, db)

        # Build tool registry
        tool_registry = ToolRegistry(
            db=db,
            user_id=agent.user_id,
            integrations=integrations,
            workspace_id=workspace_id,
            agent_id=agent.id,
            openai_api_key=openai_api_key,
            tool_configs=agent.tool_configs or {},
        )

        # Build agent config dict for the model
        agent_config: dict[str, Any] = {
            "llm_model": agent.provider_config.get("llm_model", "gpt-realtime-1.5"),
            "voice": agent.voice or "shimmer",
            "temperature": agent.temperature,
            "turn_detection_mode": agent.turn_detection_mode,
            "turn_detection_threshold": agent.turn_detection_threshold,
            "turn_detection_prefix_padding_ms": agent.turn_detection_prefix_padding_ms,
            "turn_detection_silence_duration_ms": agent.turn_detection_silence_duration_ms,
            "openai_api_key": openai_api_key,
        }

        # Build tool definitions and LiveKit function tools
        tool_defs = tool_registry.get_all_tool_definitions(
            agent.enabled_tools or [],
            agent.enabled_tool_ids,
        )
        dynamic_tools = _build_dynamic_tools(tool_defs, tool_registry)

        # Always include end_call via LiveKit's built-in tool
        # Only add EndCallTool if call_control hasn't already registered end_call
        has_end_call = any(
            getattr(getattr(t, "info", None), "name", None) == "end_call" for t in dynamic_tools
        )
        lk_tools: list[Any] = dynamic_tools if has_end_call else [EndCallTool(), *dynamic_tools]

        # Build RealtimeModel
        llm_model = _realtime_model_for_tier(agent.pricing_tier, agent_config)

        voice_agent = VoiceAgent(
            instructions=instructions,
            llm=llm_model,
            tools=lk_tools,
            initial_greeting=agent.initial_greeting,
        )

    # Connect to the room and start the session
    await ctx.connect()

    session: AgentSession[None] = AgentSession()
    log.info("livekit_session_starting")

    await session.start(agent=voice_agent, room=ctx.room)

    # Wait until the room disconnects before cleaning up
    disconnected = asyncio.Event()
    ctx.room.on("disconnected", lambda *_: disconnected.set())
    await disconnected.wait()

    log.info("livekit_agent_job_done")


def prewarm(proc: JobProcess) -> None:
    """Optional prewarm hook — load heavy resources once per worker process."""
    logging.basicConfig(level=logging.INFO)
    logger.info("livekit_worker_prewarm")


# ---------------------------------------------------------------------------
# CLI entrypoint — run this file directly to start the worker
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from app.core.config import settings

    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
            ws_url=settings.LIVEKIT_URL,
            api_key=settings.LIVEKIT_API_KEY,
            api_secret=settings.LIVEKIT_API_SECRET,
        )
    )
