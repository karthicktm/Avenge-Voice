"""Gemini Live voice agent using livekit-agents 1.x API."""

import asyncio
import json
import time
from typing import Any

import httpx
import structlog
from livekit.agents import Agent, AgentSession, ConversationItemAddedEvent, JobContext, UserInputTranscribedEvent
from livekit.plugins.google import realtime

from config import settings
from tool_bridge import build_tools

logger = structlog.get_logger()


def _publish_transcript(room: Any, speaker: str, text: str) -> None:
    """Send a transcript event to frontend via LiveKit data channel."""
    try:
        payload = json.dumps({"type": "transcript", "speaker": speaker, "text": text}).encode()
        room.local_participant.publish_data(payload, reliable=True)
    except Exception as e:
        logger.warning("transcript_publish_failed", error=str(e))


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
    model_name = config.get("model", "gemini-3.1-flash-live-preview")
    tool_defs: list[dict] = config.get("tools", [])
    initial_greeting = config.get("initial_greeting")

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
        api_version="v1alpha",
        temperature=config.get("temperature", 0.7),
    )

    agent = Agent(instructions=instructions, tools=tools)
    session = AgentSession(llm=model)

    # Issue 2 & 3: Transcript + visibility into what is said
    @session.on("user_input_transcribed")
    def on_user_transcribed(ev: UserInputTranscribedEvent) -> None:
        if ev.is_final and ev.transcript.strip():
            log.info("user_said", text=ev.transcript)
            _publish_transcript(ctx.room, "user", ev.transcript)

    @session.on("conversation_item_added")
    def on_item_added(ev: ConversationItemAddedEvent) -> None:
        msg = ev.item
        role = getattr(msg, "role", None)
        text = getattr(msg, "text_content", None) or ""
        if role == "assistant" and text.strip():
            log.info("agent_said", text=text)
            _publish_transcript(ctx.room, "assistant", text)

    t_start = time.monotonic()
    await session.start(agent=agent, room=ctx.room)
    log.info("gemini_agent_running", model=model_name, voice=voice, tools=len(tools),
             session_start_ms=round((time.monotonic() - t_start) * 1000))

    # Issue 1: Speak immediately to reduce perceived latency
    if initial_greeting:
        await session.say(initial_greeting)
    else:
        # Trigger an immediate greeting to warm up the audio path
        await session.generate_reply()

    # Issue 4: Wait for room disconnect (session close_on_disconnect=True handles cleanup)
    disconnected = asyncio.Event()
    ctx.room.on("disconnected", lambda *_: disconnected.set())
    await disconnected.wait()

    log.info("agent_job_completed")
