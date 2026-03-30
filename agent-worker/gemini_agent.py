"""Gemini Live voice agent using livekit-agents 1.x API."""

import asyncio
import json
from typing import Any

import httpx
import structlog
from livekit.agents import Agent, AgentSession, JobContext
from livekit.plugins.google import realtime

from config import settings
from tool_bridge import build_tools

logger = structlog.get_logger()


async def run_gemini_agent(ctx: JobContext) -> None:
    """Run a Gemini Live agent for a LiveKit room."""
    log = logger.bind(room=ctx.room.name)
    log.info("agent_job_started")

    await ctx.connect()

    config: dict[str, Any] = {}
    metadata_str = ctx.room.metadata or "{}"
    try:
        config = json.loads(metadata_str)
    except json.JSONDecodeError:
        pass

    # SIP rooms: resolve agent config from phone number
    if not config.get("agent_id") and ctx.room.name.startswith("sip-"):
        phone_number = ctx.room.name[4:]
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{settings.BACKEND_URL}/internal/phone/{phone_number}",
                    headers={"X-Internal-Secret": settings.INTERNAL_API_SECRET},
                )
                resp.raise_for_status()
                phone_data = resp.json()
                config["agent_id"] = phone_data["agent_id"]
                config["workspace_id"] = phone_data["workspace_id"]
        except Exception as e:
            log.error("sip_phone_lookup_failed", error=str(e))
            return

    agent_id = config.get("agent_id", "")
    workspace_id = config.get("workspace_id", "")
    google_api_key = config.get("google_api_key", "")
    instructions = config.get("instructions", "You are a helpful voice assistant.")
    voice = config.get("voice", "Puck")
    model_name = config.get("model", "gemini-2.0-flash-live-001")
    tool_defs: list[dict] = config.get("tools", [])

    if not google_api_key:
        log.error("missing_google_api_key")
        return

    tools = build_tools(
        tools=tool_defs,
        agent_id=agent_id,
        workspace_id=workspace_id,
        backend_url=settings.BACKEND_URL,
        internal_secret=settings.INTERNAL_API_SECRET,
    ) if tool_defs else []

    model = realtime.RealtimeModel(
        model=model_name,
        voice=voice,
        instructions=instructions,
        api_key=google_api_key,
        temperature=config.get("temperature", 0.7),
    )

    agent = Agent(instructions=instructions, tools=tools)
    session = AgentSession(llm=model)

    log.info("gemini_agent_running", model=model_name, voice=voice, tools=len(tools))

    await session.start(agent=agent, room=ctx.room)

    # Wait until the room disconnects
    disconnected = asyncio.Event()
    ctx.room.on("disconnected", lambda _: disconnected.set())
    # Also handle participant_disconnected for the case where the user leaves
    ctx.room.on("participant_disconnected", lambda p: disconnected.set())

    await disconnected.wait()
    log.info("agent_job_completed")
