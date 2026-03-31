"""Gemini Live voice agent using livekit-agents 1.x API."""

import asyncio
import json
import time
from typing import Any

import httpx
import structlog
from livekit.agents import Agent, AgentSession, ConversationItemAddedEvent, JobContext, UserInputTranscribedEvent
from livekit.plugins.google import realtime
from livekit.plugins.google.beta.gemini_tts import TTS as GeminiTTS

from config import settings
from tool_bridge import build_tools

logger = structlog.get_logger()


async def _publish_transcript(room: Any, speaker: str, text: str) -> None:
    """Send a transcript event to frontend via LiveKit data channel."""
    try:
        if room is None or room.local_participant is None:
            logger.warning("transcript_skip_no_participant")
            return
        payload = json.dumps({"type": "transcript", "speaker": speaker, "text": text}).encode()
        result = room.local_participant.publish_data(payload, reliable=True)
        # publish_data may be async in some versions
        if asyncio.iscoroutine(result):
            await result
        logger.debug("transcript_published", speaker=speaker, length=len(text))
    except Exception as e:
        logger.warning("transcript_publish_failed", error=str(e), speaker=speaker)


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
    initial_greeting = config.get("initial_greeting") or ""
    categorize_tree_name = config.get("categorize_tree_name", "")

    if not google_api_key:
        log.error("missing_google_api_key")
        return

    # Event to signal end_call tool was invoked
    end_call_event = asyncio.Event()

    tools = build_tools(
        tools=tool_defs,
        agent_id=agent_id,
        workspace_id=workspace_id,
        backend_url=settings.BACKEND_URL,
        internal_secret=settings.INTERNAL_API_SECRET,
        end_call_event=end_call_event,
    ) if tool_defs else []


    # Build effective instructions: tool-use rules FIRST (highest priority for Gemini),
    # then system prompt. Greeting is handled separately via TTS — do NOT instruct Gemini to greet.
    categorize_rule = (
        f"1. CATEGORIZE ISSUES — SAY ACK FIRST, THEN CALL TOOL: When a caller describes a problem or issue, "
        f"FIRST say a brief spoken acknowledgment — for example 'Let me note that down', 'One moment', or 'Got it, let me log that' — "
        f"and THEN immediately call categorize(text=<issue description>, tree_name='{categorize_tree_name}'). "
        "NEVER state, guess or invent any category, issue type or priority before calling the tool. "
        "The ack keeps the caller informed while the tool runs. Silence during tool calls is not acceptable.\n"
        if categorize_tree_name else
        "1. NEVER guess or invent categories — only speak about categories after calling a tool.\n"
    )
    effective_instructions = (
        "## CRITICAL TOOL RULES — FOLLOW BEFORE ANYTHING ELSE\n"
        + categorize_rule
        + "2. NEVER say 'I wasn't able to find' or 'I couldn't find' without FIRST calling a tool.\n"
        "3. For EXISTING tenants (STEP 3): as soon as they provide their phone number, call lookup_search(query=<phone number>) immediately to look up their record before continuing.\n"
        "4. For NEW/PROSPECTIVE tenants (STEP 2): as soon as they mention a property name, area or city, call lookup_search(query=<their input>) immediately. This applies to queries like 'Stockholm', 'Vällingby', 'Hinderbanan' etc.\n"
        "5. For EXISTING tenants (STEP 5): after confirming their property and collecting the issue, call lookup_search(query=<property name>) immediately.\n"
        "6. ALWAYS say a brief acknowledgment (e.g. 'One moment', 'Let me check') BEFORE calling any tool — then call the tool — then speak based on what it returns. Never guess or use internal knowledge. Never be silent during tool calls.\n"
        "7. The opening greeting has already been spoken. DO NOT greet again. Wait for the caller to respond.\n\n"
        + instructions
    )

    model = realtime.RealtimeModel(
        model=model_name,
        voice=voice,
        instructions=effective_instructions,
        api_key=google_api_key,
        api_version="v1alpha",
        temperature=config.get("temperature", 0.7),
    )

    agent = Agent(instructions=effective_instructions, tools=tools)
    session = AgentSession(llm=model)

    # Transcript: publish to frontend via LiveKit data channel
    @session.on("user_input_transcribed")
    def on_user_transcribed(ev: UserInputTranscribedEvent) -> None:
        if ev.is_final and ev.transcript.strip():
            log.info("user_said", text=ev.transcript)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_publish_transcript(ctx.room, "user", ev.transcript))
            except RuntimeError:
                pass  # no running loop — skip

    @session.on("conversation_item_added")
    def on_item_added(ev: ConversationItemAddedEvent) -> None:
        msg = ev.item
        role = getattr(msg, "role", None)
        text = getattr(msg, "text_content", None) or ""
        if role == "assistant" and text.strip():
            log.info("agent_said", text=text)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(_publish_transcript(ctx.room, "assistant", text))
            except RuntimeError:
                pass  # no running loop — skip

    # Wait for the user participant to join before starting — ensures audio
    # subscription is established so the greeting is actually heard
    log.info("waiting_for_participant")
    await ctx.wait_for_participant()
    log.info("participant_joined")

    t_start = time.monotonic()
    await session.start(agent=agent, room=ctx.room)
    log.info("gemini_agent_running", model=model_name, voice=voice, tools=len(tools),
             session_start_ms=round((time.monotonic() - t_start) * 1000))

    # Brief pause for audio track subscription to complete.
    await asyncio.sleep(0.5)

    # Speak the initial greeting via Gemini TTS, then Gemini Live takes over.
    greeting_text = initial_greeting or "Hello, thanks for calling. How can I help you today?"
    try:
        tts_engine = GeminiTTS(api_key=google_api_key, voice_name=voice)

        async def _greeting_audio():
            async for chunk in tts_engine.synthesize(greeting_text):
                yield chunk.frame

        session.say(greeting_text, audio=_greeting_audio())
        log.info("greeting_via_tts", text=greeting_text)
    except Exception as e:
        log.warning("greeting_tts_failed", error=str(e))

    # Wait for either: room disconnect OR end_call tool invoked
    disconnected = asyncio.Event()
    ctx.room.on("disconnected", lambda *_: disconnected.set())

    # Issue 1 (end_call): When assistant invokes end_call, disconnect after a short delay
    # so the farewell audio finishes playing before we hang up
    async def _handle_end_call() -> None:
        await end_call_event.wait()
        log.info("end_call_tool_invoked_disconnecting")
        await asyncio.sleep(3.0)  # Let farewell audio finish
        result = ctx.room.disconnect()
        if asyncio.iscoroutine(result):
            await result

    end_call_task = asyncio.create_task(_handle_end_call())

    await disconnected.wait()
    end_call_task.cancel()

    log.info("agent_job_completed")
