"""Slim FastAPI app serving a single voice agent.

This process:
- Reads AGENT_ID from env to know which agent it serves
- Exposes GET /health for readiness checks
- Exposes WS /ws/realtime/{agent_id} for GPT Realtime voice sessions
- Reuses GPTRealtimeSession from the main app (shared codebase)
- Uses a small connection pool (pool_size=2) to conserve Postgres connections
"""

import asyncio
import contextlib
import uuid
from collections.abc import AsyncIterator
from typing import Any

import structlog
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from agent_runtime.config import runtime_settings
from app.models.agent import Agent
from app.services.gpt_realtime import GPTRealtimeSession

logger = structlog.get_logger()

# ---------------------------------------------------------------------------
# Database — small pool to conserve Postgres connections
# ---------------------------------------------------------------------------
_engine = create_async_engine(
    runtime_settings.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://").replace(
        "postgres://", "postgresql+asyncpg://"
    ),
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
)

_AsyncSessionLocal = async_sessionmaker(
    _engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# ---------------------------------------------------------------------------
# App lifecycle
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    logger.info(
        "agent_runtime_started",
        agent_id=runtime_settings.AGENT_ID,
        port=runtime_settings.PORT,
    )
    yield
    await _engine.dispose()
    logger.info("agent_runtime_stopped")


app = FastAPI(title="Agent Runtime", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------


@app.get("/health")
async def health() -> dict[str, str]:
    """Readiness probe used by the control plane."""
    return {"status": "ok", "agent_id": runtime_settings.AGENT_ID}


# ---------------------------------------------------------------------------
# WebSocket — GPT Realtime voice session
# ---------------------------------------------------------------------------


@app.websocket("/ws/realtime/{agent_id}")
async def realtime_websocket(
    websocket: WebSocket,
    agent_id: str,
    workspace_id: str,
) -> None:
    """WebSocket endpoint for GPT Realtime voice calls.

    Mirrors the control plane's realtime_websocket but is locked to the single
    agent configured via AGENT_ID. Rejects misrouted requests immediately.
    """
    session_id = str(uuid.uuid4())
    log = logger.bind(
        endpoint="agent_runtime_ws",
        agent_id=agent_id,
        workspace_id=workspace_id,
        session_id=session_id,
    )

    await websocket.accept()

    # Reject misrouted requests
    if agent_id != runtime_settings.AGENT_ID:
        log.warning(
            "misrouted_request",
            expected_agent=runtime_settings.AGENT_ID,
            got_agent=agent_id,
        )
        await websocket.send_json({"type": "error", "error": "Agent mismatch"})
        await websocket.close(code=4000)
        return

    log.info("agent_runtime_ws_connected")

    try:
        # Validate workspace UUID
        try:
            agent_uuid = uuid.UUID(agent_id)
            workspace_uuid = uuid.UUID(workspace_id)
        except ValueError:
            await websocket.send_json(
                {"type": "error", "error": "Invalid agent or workspace ID format"}
            )
            await websocket.close(code=4000)
            return

        async with _AsyncSessionLocal() as db:
            # Load agent
            result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
            agent = result.scalar_one_or_none()

            if not agent:
                await websocket.send_json({"type": "error", "error": f"Agent {agent_id} not found"})
                await websocket.close()
                return

            if not agent.is_active:
                await websocket.send_json({"type": "error", "error": "Agent is not active"})
                await websocket.close()
                return

            if agent.pricing_tier not in ("premium", "premium-mini"):
                await websocket.send_json(
                    {
                        "type": "error",
                        "error": "GPT Realtime only available for Premium tier agents",
                    }
                )
                await websocket.close()
                return

            agent_config: dict[str, Any] = {
                "system_prompt": agent.system_prompt,
                "enabled_tools": agent.enabled_tools,
                "enabled_tool_ids": agent.enabled_tool_ids,
                "tool_configs": agent.tool_configs,
                "language": agent.language,
                "voice": agent.voice or "shimmer",
                "temperature": agent.temperature,
                "agent_id": str(agent.id),
                "llm_model": agent.provider_config.get("llm_model", "gpt-realtime-1.5"),
                "turn_detection_mode": agent.turn_detection_mode,
                "turn_detection_threshold": agent.turn_detection_threshold,
                "turn_detection_prefix_padding_ms": agent.turn_detection_prefix_padding_ms,
                "turn_detection_silence_duration_ms": agent.turn_detection_silence_duration_ms,
            }

            async with GPTRealtimeSession(
                db=db,
                user_id=agent.user_id,
                agent_config=agent_config,
                session_id=session_id,
                workspace_id=workspace_uuid,
            ) as realtime_session:
                await websocket.send_json(
                    {
                        "type": "session.ready",
                        "session_id": session_id,
                        "agent": {
                            "id": str(agent.id),
                            "name": agent.name,
                            "tier": agent.pricing_tier,
                        },
                    }
                )
                await _bridge_audio_streams(websocket, realtime_session, log)

    except WebSocketDisconnect:
        log.info("agent_runtime_ws_disconnected")
    except Exception as exc:
        log.exception("agent_runtime_ws_error", error=str(exc))
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "error": str(exc)})
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
        log.info("agent_runtime_ws_closed")


async def _bridge_audio_streams(
    client_ws: WebSocket,
    realtime_session: GPTRealtimeSession,
    log: Any,
) -> None:
    """Bidirectional bridge between client WebSocket and GPT Realtime."""

    async def client_to_realtime() -> None:
        try:
            while True:
                message = await client_ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if message["type"] == "websocket.receive" and "bytes" in message:
                    await realtime_session.send_audio(message["bytes"])
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            log.exception("runtime_client_to_realtime_error", error=str(exc))

    async def realtime_to_client() -> None:
        try:
            if not realtime_session.connection:
                log.error("no_realtime_connection")
                return
            async for event in realtime_session.connection:
                try:
                    event_type = event.type
                    if event_type == "response.function_call_arguments.done":
                        await realtime_session.handle_function_call_event(event)
                    await client_ws.send_json(
                        {
                            "type": event_type,
                            "event": event.model_dump() if hasattr(event, "model_dump") else {},
                        }
                    )
                except Exception as exc:
                    log.exception("runtime_event_forward_error", error=str(exc))
        except Exception as exc:
            log.exception("runtime_realtime_to_client_error", error=str(exc))

    results = await asyncio.gather(
        client_to_realtime(),
        realtime_to_client(),
        return_exceptions=True,
    )

    for i, result in enumerate(results):
        if isinstance(result, BaseException):
            task_name = "client_to_realtime" if i == 0 else "realtime_to_client"
            log.error(
                "runtime_bridge_task_failed",
                task=task_name,
                error=str(result),
            )
