"""Telephony WebSocket endpoints for Twilio and Telnyx media streaming.

These WebSocket endpoints handle the audio streams from Twilio and Telnyx,
connecting them to our AI voice agent pipeline.
"""

import asyncio
import base64
import contextlib
import json
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.settings import get_user_api_keys
from app.core.auth import user_id_to_uuid
from app.db.session import get_db
from app.models.agent import Agent
from app.models.call_record import CallRecord
from app.models.campaign import Campaign, CampaignContact
from app.models.workspace import AgentWorkspace
from app.services.gpt_realtime import GPTRealtimeSession
from app.services.telephony.telnyx_service import TelnyxService
from app.services.telephony.twilio_service import TwilioService

router = APIRouter(prefix="/ws/telephony", tags=["telephony-ws"])
logger = structlog.get_logger()

# Constants for event logging
EVENT_LOG_THRESHOLD = 20  # Log first N events, then every 100th


async def get_agent_workspace_id(agent_id: uuid.UUID, db: AsyncSession) -> uuid.UUID | None:
    """Get workspace ID for an agent."""
    result = await db.execute(
        select(AgentWorkspace.workspace_id).where(AgentWorkspace.agent_id == agent_id).limit(1)
    )
    row = result.scalar_one_or_none()
    return row


async def _get_telnyx_service(
    user_id: int, db: AsyncSession, workspace_id: uuid.UUID | None
) -> TelnyxService | None:
    user_settings = await get_user_api_keys(user_id_to_uuid(user_id), db, workspace_id=workspace_id)
    if not user_settings or not user_settings.telnyx_api_key:
        return None
    return TelnyxService(
        api_key=user_settings.telnyx_api_key,
        public_key=user_settings.telnyx_public_key,
    )


async def _get_twilio_service(
    user_id: int, db: AsyncSession, workspace_id: uuid.UUID | None
) -> TwilioService | None:
    user_settings = await get_user_api_keys(user_id_to_uuid(user_id), db, workspace_id=workspace_id)
    if (
        not user_settings
        or not user_settings.twilio_account_sid
        or not user_settings.twilio_auth_token
    ):
        return None
    return TwilioService(
        account_sid=user_settings.twilio_account_sid,
        auth_token=user_settings.twilio_auth_token,
    )


async def save_transcript_to_call_record(
    call_sid: str,
    transcript: str,
    db: AsyncSession,
    log: Any,
) -> None:
    """Save transcript to the call record.

    Args:
        call_sid: Provider call ID (CallSid for Twilio, call_control_id for Telnyx)
        transcript: Formatted transcript text
        db: Database session
        log: Logger instance
    """
    if not transcript.strip():
        log.debug("empty_transcript_skipped")
        return

    result = await db.execute(select(CallRecord).where(CallRecord.provider_call_id == call_sid))
    call_record = result.scalar_one_or_none()

    if call_record:
        call_record.transcript = transcript
        await db.commit()
        log.info("transcript_saved", record_id=str(call_record.id), length=len(transcript))
    else:
        log.warning("call_record_not_found_for_transcript", call_sid=call_sid)


async def _load_campaign_context(
    campaign_id: str,
    campaign_contact_id: str,
    db: AsyncSession,
    log: Any,
) -> dict[str, Any] | None:
    """Load campaign + contact context from the database.

    Args:
        campaign_id: Campaign UUID string
        campaign_contact_id: CampaignContact UUID string
        db: Database session
        log: Logger instance

    Returns:
        Campaign context dict or None if not found
    """
    try:
        campaign_uuid = uuid.UUID(campaign_id)
        cc_uuid = uuid.UUID(campaign_contact_id)
    except ValueError:
        log.warning("invalid_campaign_params", campaign_id=campaign_id, cc_id=campaign_contact_id)
        return None

    # Load campaign
    result = await db.execute(select(Campaign).where(Campaign.id == campaign_uuid))
    campaign = result.scalar_one_or_none()
    if not campaign:
        log.warning("campaign_not_found", campaign_id=campaign_id)
        return None

    # Load campaign contact with joined contact
    cc_result = await db.execute(
        select(CampaignContact)
        .options(selectinload(CampaignContact.contact))
        .where(CampaignContact.id == cc_uuid)
    )
    campaign_contact = cc_result.scalar_one_or_none()
    if not campaign_contact:
        log.warning("campaign_contact_not_found", campaign_contact_id=campaign_contact_id)
        return None

    contact = campaign_contact.contact

    context: dict[str, Any] = {
        "campaign_id": campaign_id,
        "campaign_contact_id": campaign_contact_id,
        "campaign_name": campaign.name,
        "campaign_script": campaign.script,
        "campaign_greeting": campaign.campaign_greeting,
    }

    if contact:
        context["contact_name"] = f"{contact.first_name} {contact.last_name or ''}".strip()
        context["contact_company"] = contact.company_name
        context["contact_email"] = contact.email
        context["contact_phone"] = contact.phone_number
        context["contact_tags"] = contact.tags
        context["contact_notes"] = contact.notes

    log.info("campaign_context_loaded", campaign_name=campaign.name, has_contact=bool(contact))
    return context


@router.websocket("/twilio/{agent_id}")
async def twilio_media_stream(
    websocket: WebSocket,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """WebSocket endpoint for Twilio Media Streams.

    Twilio sends audio via Media Streams in mulaw format at 8kHz.
    This endpoint bridges that audio to our GPT Realtime session.

    Message format from Twilio:
    - {"event": "connected", "protocol": "Call", "version": "1.0.0"}
    - {"event": "start", "start": {"streamSid": "...", "callSid": "..."}}
    - {"event": "media", "media": {"payload": "base64_audio"}}
    - {"event": "stop"}
    """
    session_id = str(uuid.uuid4())
    log = logger.bind(
        endpoint="twilio_media_stream",
        agent_id=agent_id,
        session_id=session_id,
    )

    await websocket.accept()
    log.info("twilio_websocket_connected")

    stream_sid: str = ""
    call_sid: str = ""

    try:
        # Load agent configuration
        result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        agent = result.scalar_one_or_none()

        if not agent:
            log.error("agent_not_found")
            await websocket.close(code=4004, reason="Agent not found")
            return

        if not agent.is_active:
            log.error("agent_not_active")
            await websocket.close(code=4003, reason="Agent is not active")
            return

        log.info("agent_loaded", agent_name=agent.name)

        # agent.user_id is now directly the integer user ID
        user_id_int = agent.user_id

        # Get workspace for the agent
        workspace_id = await get_agent_workspace_id(agent.id, db)

        # Load campaign context if this is a campaign call
        campaign_id_param = websocket.query_params.get("campaign_id", "")
        campaign_contact_id_param = websocket.query_params.get("campaign_contact_id", "")
        campaign_context: dict[str, Any] | None = None
        if campaign_id_param and campaign_contact_id_param:
            campaign_context = await _load_campaign_context(
                campaign_id_param, campaign_contact_id_param, db, log
            )

        # Build agent config
        agent_config: dict[str, Any] = {
            "agent_id": str(agent.id),
            "system_prompt": agent.system_prompt,
            "enabled_tools": agent.enabled_tools,
            "enabled_tool_ids": agent.enabled_tool_ids,
            "tool_configs": agent.tool_configs,
            "language": agent.language,
            "voice": agent.voice or "shimmer",
            "temperature": agent.temperature,
            "enable_transcript": agent.enable_transcript,
            "initial_greeting": agent.initial_greeting,
            "llm_model": agent.provider_config.get("llm_model", "gpt-realtime-1.5"),
            "turn_detection_mode": agent.turn_detection_mode,
            "turn_detection_threshold": agent.turn_detection_threshold,
            "turn_detection_prefix_padding_ms": agent.turn_detection_prefix_padding_ms,
            "turn_detection_silence_duration_ms": agent.turn_detection_silence_duration_ms,
        }

        # Add campaign context and override greeting if present
        if campaign_context:
            agent_config["campaign_context"] = campaign_context
            if campaign_context.get("campaign_greeting"):
                agent_config["initial_greeting"] = campaign_context["campaign_greeting"]

        # Initialize GPT Realtime session
        async with GPTRealtimeSession(
            db=db,
            user_id=user_id_int,
            agent_config=agent_config,
            session_id=session_id,
            workspace_id=workspace_id,
        ) as realtime_session:
            # Handle Twilio media stream and capture call_sid
            call_sid, ended_by_agent = await _handle_twilio_stream(
                websocket=websocket,
                realtime_session=realtime_session,
                log=log,
                enable_transcript=agent.enable_transcript,
            )

            # Hang up the phone call if the agent triggered end_call
            if ended_by_agent and call_sid:
                twilio_svc = await _get_twilio_service(user_id_int, db, workspace_id)
                if twilio_svc:
                    with contextlib.suppress(Exception):
                        await twilio_svc.hangup_call(call_sid)
                        log.info("twilio_call_hungup", call_sid=call_sid)
                else:
                    log.warning("twilio_service_unavailable_for_hangup", call_sid=call_sid)

            # Save transcript to call record if enabled
            if agent.enable_transcript and call_sid:
                transcript = realtime_session.get_transcript()
                await save_transcript_to_call_record(call_sid, transcript, db, log)

    except WebSocketDisconnect:
        log.warning("twilio_websocket_disconnected")
    except Exception as e:
        log.exception("twilio_websocket_error", error=str(e))
    finally:
        log.warning("twilio_websocket_closed", stream_sid=stream_sid, call_sid=call_sid)


async def _handle_twilio_stream(  # noqa: PLR0915
    websocket: WebSocket,
    realtime_session: GPTRealtimeSession,
    log: Any,
    enable_transcript: bool = False,
) -> tuple[str, bool]:
    """Handle Twilio Media Stream messages.

    Args:
        websocket: WebSocket connection from Twilio
        realtime_session: GPT Realtime session
        log: Logger instance
        enable_transcript: Whether to capture transcript

    Returns:
        Tuple of (call_sid, should_end_call)
    """
    stream_sid = ""
    call_sid = ""
    should_end_call = False  # Flag to signal call should end

    async def twilio_to_realtime() -> None:
        """Forward audio from Twilio to GPT Realtime."""
        nonlocal stream_sid, call_sid, should_end_call

        try:
            while not should_end_call:
                message = await websocket.receive_text()
                data = json.loads(message)
                event = data.get("event", "")

                if event == "connected":
                    log.info("twilio_stream_connected")

                elif event == "start":
                    start_data = data.get("start", {})
                    stream_sid = start_data.get("streamSid", "")
                    call_sid = start_data.get("callSid", "")
                    log.info(
                        "twilio_stream_started",
                        stream_sid=stream_sid,
                        call_sid=call_sid,
                    )

                elif event == "media":
                    # Decode base64 mulaw audio and forward to Realtime
                    media = data.get("media", {})
                    payload = media.get("payload", "")
                    if payload:
                        audio_bytes = base64.b64decode(payload)
                        await realtime_session.send_audio(audio_bytes)

                elif event == "stop":
                    log.info("twilio_stream_stopped")
                    break

                elif event == "mark":
                    # Mark events indicate playback position
                    log.debug("twilio_mark_event", name=data.get("mark", {}).get("name"))

        except WebSocketDisconnect:
            log.warning("twilio_to_realtime_disconnected")
        except Exception as e:
            log.exception("twilio_to_realtime_error", error=str(e))

    async def realtime_to_twilio() -> None:  # noqa: PLR0912, PLR0915
        """Forward audio from GPT Realtime to Twilio."""
        nonlocal should_end_call

        try:
            if not realtime_session.connection:
                log.error("no_realtime_connection")
                return

            log.warning("realtime_to_twilio_started", waiting_for_events=True)
            event_count = 0
            pending_end_call = False  # True when end_call requested but waiting for AI to finish
            greeting_triggered = False  # Track if we've triggered the greeting

            # Trigger the initial greeting immediately — session.updated is consumed
            # internally by the OpenAI SDK's session.update() call and never arrives
            # in our event loop, so we cannot rely on that event as a trigger.
            # The greeting is sent before the loop; the SDK buffers the resulting
            # audio events so realtime_to_twilio will receive them as soon as the
            # loop starts.
            if not greeting_triggered:
                greeting_triggered = True
                triggered = await realtime_session.trigger_initial_greeting()
                log.warning(
                    "greeting_triggered_before_loop",
                    triggered=triggered,
                    stream_sid_at_trigger=stream_sid or "EMPTY",
                )

            async for event in realtime_session.connection:
                event_type = event.type
                event_count += 1

                # Log all events for debugging
                if event_count <= EVENT_LOG_THRESHOLD or event_count % 100 == 0:
                    log.info("realtime_event_received", event_type=event_type, count=event_count)

                # Handle audio output
                if event_type == "response.audio.delta":
                    # Get audio delta and send to Twilio
                    # Check various possible attribute names for the audio data
                    delta_data = getattr(event, "delta", None)
                    if not delta_data:
                        # Log event attributes for debugging
                        log.warning(
                            "audio_delta_missing",
                            event_attrs=dir(event),
                            has_delta=hasattr(event, "delta"),
                        )
                        continue

                    try:
                        audio_bytes = base64.b64decode(delta_data)
                        # Encode for Twilio (already in g711_ulaw format now)
                        payload = base64.b64encode(audio_bytes).decode("utf-8")
                        log.warning(
                            "sending_audio_to_twilio",
                            audio_size=len(audio_bytes),
                            stream_sid=stream_sid or "EMPTY",
                        )
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {"payload": payload},
                                }
                            )
                        )
                    except Exception as audio_err:
                        log.exception("audio_send_error", error=str(audio_err))

                # Handle tool calls
                elif event_type == "response.function_call_arguments.done":
                    log.info(
                        "handling_function_call",
                        call_id=event.call_id,
                        name=event.name,
                    )
                    result = await realtime_session.handle_function_call_event(event)
                    # Check if this is an end_call action
                    if result.get("action") == "end_call":
                        log.info("end_call_action_received", reason=result.get("reason"))
                        pending_end_call = True
                    # Handle disposition tool result
                    elif result.get("action") == "set_disposition":
                        await realtime_session.save_campaign_disposition(
                            disposition=result.get("disposition", ""),
                            notes=result.get("notes"),
                        )
                        log.info("disposition_saved", disposition=result.get("disposition"))

                # Capture transcript events
                elif (
                    enable_transcript
                    and event_type == "conversation.item.input_audio_transcription.completed"
                ):
                    # User speech transcription
                    if hasattr(event, "transcript") and event.transcript:
                        realtime_session.add_user_transcript(event.transcript)
                        log.debug("user_transcript_captured", length=len(event.transcript))

                elif enable_transcript and event_type == "response.audio_transcript.delta":
                    # Assistant speech transcript delta
                    if hasattr(event, "delta") and event.delta:
                        realtime_session.accumulate_assistant_text(event.delta)

                elif enable_transcript and event_type == "response.audio_transcript.done":
                    # Assistant speech transcript complete
                    realtime_session.flush_assistant_text()

                # Handle response completion - check if we should end the call
                elif event_type == "response.done":
                    # Log full response details for debugging
                    response_data = getattr(event, "response", None)
                    if response_data:
                        status = getattr(response_data, "status", "unknown")
                        status_details = getattr(response_data, "status_details", None)
                        output = getattr(response_data, "output", [])
                        output_count = len(output) if output else 0
                        log.info(
                            "response_done_details",
                            status=status,
                            status_details=str(status_details) if status_details else None,
                            output_count=output_count,
                        )
                    else:
                        log.debug("realtime_event", event_type=event_type)
                    if pending_end_call:
                        log.info("ending_call_after_response_complete")
                        should_end_call = True
                        break

                # Log other events
                elif event_type in [
                    "response.audio.done",
                    "input_audio_buffer.speech_started",
                    "input_audio_buffer.speech_stopped",
                ]:
                    log.debug("realtime_event", event_type=event_type)

        except WebSocketDisconnect:
            log.warning("realtime_to_twilio_disconnected")
        except Exception as e:
            log.exception("realtime_to_twilio_error", error=str(e))
        else:
            # Loop exited normally (OpenAI connection closed without exception)
            log.warning(
                "realtime_to_twilio_exited",
                event_count=event_count,
                greeting_triggered=greeting_triggered,
            )

    # Run both directions concurrently with timeout to prevent hung tasks
    try:
        await asyncio.wait_for(
            asyncio.gather(
                twilio_to_realtime(),
                realtime_to_twilio(),
                return_exceptions=True,
            ),
            timeout=300.0,  # 5 minute max call duration before forced cleanup
        )
    except TimeoutError:
        log.warning("twilio_bridge_timeout", message="Call exceeded max duration, forcing cleanup")

    # Close WebSocket to hang up the call if end_call was triggered
    if should_end_call:
        log.info("closing_websocket_for_end_call")
        with contextlib.suppress(Exception):
            await websocket.close(code=1000, reason="Call ended by agent")

    return call_sid, should_end_call


@router.websocket("/telnyx/{agent_id}")
async def telnyx_media_stream(
    websocket: WebSocket,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """WebSocket endpoint for Telnyx Media Streams.

    Telnyx sends audio via Media Streams in PCMU format at 8kHz.
    This endpoint bridges that audio to our GPT Realtime session.

    Message format from Telnyx:
    - {"event": "start", "stream_id": "...", "call_control_id": "..."}
    - {"event": "media", "media": {"payload": "base64_audio"}}
    - {"event": "stop"}
    """
    session_id = str(uuid.uuid4())
    log = logger.bind(
        endpoint="telnyx_media_stream",
        agent_id=agent_id,
        session_id=session_id,
    )

    await websocket.accept()
    log.info("telnyx_websocket_connected")

    stream_id: str = ""
    call_control_id: str = ""

    try:
        # Load agent configuration
        result = await db.execute(select(Agent).where(Agent.id == uuid.UUID(agent_id)))
        agent = result.scalar_one_or_none()

        if not agent:
            log.error("agent_not_found")
            await websocket.close(code=4004, reason="Agent not found")
            return

        if not agent.is_active:
            log.error("agent_not_active")
            await websocket.close(code=4003, reason="Agent is not active")
            return

        log.info("agent_loaded", agent_name=agent.name)

        # agent.user_id is now directly the integer user ID
        user_id_int = agent.user_id

        # Get workspace for the agent
        workspace_id = await get_agent_workspace_id(agent.id, db)

        # Load campaign context if this is a campaign call
        campaign_id_param = websocket.query_params.get("campaign_id", "")
        campaign_contact_id_param = websocket.query_params.get("campaign_contact_id", "")
        campaign_context: dict[str, Any] | None = None
        if campaign_id_param and campaign_contact_id_param:
            campaign_context = await _load_campaign_context(
                campaign_id_param, campaign_contact_id_param, db, log
            )

        # Build agent config
        agent_config: dict[str, Any] = {
            "agent_id": str(agent.id),
            "system_prompt": agent.system_prompt,
            "enabled_tools": agent.enabled_tools,
            "enabled_tool_ids": agent.enabled_tool_ids,
            "tool_configs": agent.tool_configs,
            "language": agent.language,
            "voice": agent.voice or "shimmer",
            "temperature": agent.temperature,
            "enable_transcript": agent.enable_transcript,
            "initial_greeting": agent.initial_greeting,
            "llm_model": agent.provider_config.get("llm_model", "gpt-realtime-1.5"),
            "turn_detection_mode": agent.turn_detection_mode,
            "turn_detection_threshold": agent.turn_detection_threshold,
            "turn_detection_prefix_padding_ms": agent.turn_detection_prefix_padding_ms,
            "turn_detection_silence_duration_ms": agent.turn_detection_silence_duration_ms,
        }

        # Add campaign context and override greeting if present
        if campaign_context:
            agent_config["campaign_context"] = campaign_context
            if campaign_context.get("campaign_greeting"):
                agent_config["initial_greeting"] = campaign_context["campaign_greeting"]

        # Initialize GPT Realtime session
        async with GPTRealtimeSession(
            db=db,
            user_id=user_id_int,
            agent_config=agent_config,
            session_id=session_id,
            workspace_id=workspace_id,
        ) as realtime_session:
            # Handle Telnyx media stream and capture call_control_id
            call_control_id, ended_by_agent = await _handle_telnyx_stream(
                websocket=websocket,
                realtime_session=realtime_session,
                log=log,
                enable_transcript=agent.enable_transcript,
            )

            # Hang up the phone call if the agent triggered end_call
            if ended_by_agent and call_control_id:
                telnyx_svc = await _get_telnyx_service(user_id_int, db, workspace_id)
                if telnyx_svc:
                    with contextlib.suppress(Exception):
                        await telnyx_svc.hangup_call(call_control_id)
                        log.info("telnyx_call_hungup", call_control_id=call_control_id)
                else:
                    log.warning(
                        "telnyx_service_unavailable_for_hangup",
                        call_control_id=call_control_id,
                    )

            # Save transcript to call record if enabled
            if agent.enable_transcript and call_control_id:
                transcript = realtime_session.get_transcript()
                await save_transcript_to_call_record(call_control_id, transcript, db, log)

    except WebSocketDisconnect:
        log.info("telnyx_websocket_disconnected")
    except Exception as e:
        log.exception("telnyx_websocket_error", error=str(e))
    finally:
        log.info("telnyx_websocket_closed", stream_id=stream_id, call_control_id=call_control_id)


async def _handle_telnyx_stream(  # noqa: PLR0915
    websocket: WebSocket,
    realtime_session: GPTRealtimeSession,
    log: Any,
    enable_transcript: bool = False,
) -> tuple[str, bool]:
    """Handle Telnyx Media Stream messages.

    Args:
        websocket: WebSocket connection from Telnyx
        realtime_session: GPT Realtime session
        log: Logger instance
        enable_transcript: Whether to capture transcript

    Returns:
        Tuple of (call_control_id, should_end_call)
    """
    stream_id = ""
    call_control_id = ""
    should_end_call = False  # Flag to signal call should end

    async def telnyx_to_realtime() -> None:
        """Forward audio from Telnyx to GPT Realtime."""
        nonlocal stream_id, call_control_id, should_end_call

        try:
            while not should_end_call:
                message = await websocket.receive_text()
                data = json.loads(message)
                event = data.get("event", "")

                if event == "start":
                    stream_id = data.get("stream_id", "")
                    start_data = data.get("start", {})
                    call_control_id = start_data.get("call_control_id", "")
                    log.info(
                        "telnyx_stream_started",
                        stream_id=stream_id,
                        call_control_id=call_control_id,
                    )

                elif event == "media":
                    # Decode base64 PCMU audio and forward to Realtime
                    media = data.get("media", {})
                    payload = media.get("payload", "")
                    if payload:
                        audio_bytes = base64.b64decode(payload)
                        await realtime_session.send_audio(audio_bytes)

                elif event == "stop":
                    log.info("telnyx_stream_stopped")
                    break

        except WebSocketDisconnect:
            log.info("telnyx_to_realtime_disconnected")
        except Exception as e:
            log.exception("telnyx_to_realtime_error", error=str(e))

    async def realtime_to_telnyx() -> None:  # noqa: PLR0912
        """Forward audio from GPT Realtime to Telnyx."""
        nonlocal should_end_call

        try:
            if not realtime_session.connection:
                log.error("no_realtime_connection")
                return

            pending_end_call = False  # True when end_call requested but waiting for AI to finish
            greeting_triggered = False  # Track if we've triggered the greeting

            async for event in realtime_session.connection:
                event_type = event.type

                # Trigger initial greeting after session is configured
                # This avoids race condition where audio events arrive before listener is ready
                if event_type == "session.updated" and not greeting_triggered:
                    greeting_triggered = True
                    triggered = await realtime_session.trigger_initial_greeting()
                    if triggered:
                        log.info("initial_greeting_triggered_after_session_update")

                # Handle audio output
                elif event_type == "response.audio.delta":
                    if hasattr(event, "delta") and event.delta:
                        audio_bytes = base64.b64decode(event.delta)
                        payload = base64.b64encode(audio_bytes).decode("utf-8")
                        await websocket.send_text(
                            json.dumps(
                                {
                                    "event": "media",
                                    "stream_id": stream_id,
                                    "media": {"payload": payload},
                                }
                            )
                        )

                # Handle tool calls
                elif event_type == "response.function_call_arguments.done":
                    log.info(
                        "handling_function_call",
                        call_id=event.call_id,
                        name=event.name,
                    )
                    result = await realtime_session.handle_function_call_event(event)
                    # Check if this is an end_call action
                    if result.get("action") == "end_call":
                        log.info("end_call_action_received", reason=result.get("reason"))
                        pending_end_call = True
                    # Handle disposition tool result
                    elif result.get("action") == "set_disposition":
                        await realtime_session.save_campaign_disposition(
                            disposition=result.get("disposition", ""),
                            notes=result.get("notes"),
                        )
                        log.info("disposition_saved", disposition=result.get("disposition"))

                # Capture transcript events
                elif (
                    enable_transcript
                    and event_type == "conversation.item.input_audio_transcription.completed"
                ):
                    # User speech transcription
                    if hasattr(event, "transcript") and event.transcript:
                        realtime_session.add_user_transcript(event.transcript)
                        log.debug("user_transcript_captured", length=len(event.transcript))

                elif enable_transcript and event_type == "response.audio_transcript.delta":
                    # Assistant speech transcript delta
                    if hasattr(event, "delta") and event.delta:
                        realtime_session.accumulate_assistant_text(event.delta)

                elif enable_transcript and event_type == "response.audio_transcript.done":
                    # Assistant speech transcript complete
                    realtime_session.flush_assistant_text()

                # Handle response completion - check if we should end the call
                elif event_type == "response.done":
                    log.debug("realtime_event", event_type=event_type)
                    if pending_end_call:
                        log.info("ending_call_after_response_complete")
                        should_end_call = True
                        break

                elif event_type in [
                    "response.audio.done",
                    "input_audio_buffer.speech_started",
                    "input_audio_buffer.speech_stopped",
                ]:
                    log.debug("realtime_event", event_type=event_type)

        except Exception as e:
            log.exception("realtime_to_telnyx_error", error=str(e))

    # Run both directions concurrently with timeout to prevent hung tasks
    try:
        await asyncio.wait_for(
            asyncio.gather(
                telnyx_to_realtime(),
                realtime_to_telnyx(),
                return_exceptions=True,
            ),
            timeout=300.0,  # 5 minute max call duration before forced cleanup
        )
    except TimeoutError:
        log.warning("telnyx_bridge_timeout", message="Call exceeded max duration, forcing cleanup")

    # Close WebSocket to hang up the call if end_call was triggered
    if should_end_call:
        log.info("closing_websocket_for_end_call")
        with contextlib.suppress(Exception):
            await websocket.close(code=1000, reason="Call ended by agent")

    return call_control_id, should_end_call
