"""Gemini Live voice agent using livekit-agents MultimodalAgent."""

import json
from typing import Any

import httpx
import structlog
from livekit.agents import AutoSubscribe, JobContext, llm
from livekit.agents.multimodal import MultimodalAgent
from livekit.plugins import google

from config import settings
from tool_bridge import build_function_context

logger = structlog.get_logger()


async def run_gemini_agent(ctx: JobContext) -> None:
    """Run a Gemini Live agent for a LiveKit room."""
    log = logger.bind(room=ctx.room.name)
    log.info("agent_job_started")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

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
    tools: list[dict] = config.get("tools", [])

    fnc_ctx: llm.FunctionContext | None = None
    if tools:
        fnc_ctx = build_function_context(
            tools=tools,
            agent_id=agent_id,
            workspace_id=workspace_id,
            backend_url=settings.BACKEND_URL,
            internal_secret=settings.INTERNAL_API_SECRET,
        )

    model = google.beta.realtime.RealtimeModel(
        model=model_name,
        voice=voice,
        system_instruction=instructions,
        api_key=google_api_key,
        temperature=config.get("temperature", 0.7),
    )

    agent = MultimodalAgent(model=model, fnc_ctx=fnc_ctx)
    agent.start(ctx.room)

    log.info("gemini_agent_running", model=model_name, voice=voice, tools=len(tools))
    await ctx.wait_for_disconnect()
    log.info("agent_job_completed")
