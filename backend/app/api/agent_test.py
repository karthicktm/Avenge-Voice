"""Agent Test Call API — two Realtime sessions bridged for AI-vs-AI testing."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import select

from app.api.settings import get_user_api_keys
from app.core.auth import VerifiedUser, user_id_to_uuid
from app.db.redis import get_redis
from app.db.session import get_db
from app.models.agent import Agent
from app.models.workspace import AgentWorkspace, Workspace
from app.services.agent_test_bridge import AgentTestBridge, TestScenario

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

http_router = APIRouter(prefix="/api/v1/agents", tags=["agent-test"])
ws_router = APIRouter(prefix="/ws", tags=["agent-test-ws"])

_TTL = 3600
_active_bridges: dict[str, AgentTestBridge] = {}
_bridge_tasks: dict[str, asyncio.Task[None]] = {}


class TestCallRequest(BaseModel):
    """Request body for creating a test call session."""

    persona: str
    goal: str


class TestCallResponse(BaseModel):
    """Response containing the new test session ID."""

    session_id: str


def _redis_key(session_id: str) -> str:
    return f"agent_test:{session_id}"


def _cleanup_session(session_id: str) -> Callable[[asyncio.Task[None]], None]:
    """Return a done-callback that removes session entries when the task finishes."""

    def _cb(t: asyncio.Task[None]) -> None:
        _active_bridges.pop(session_id, None)
        _bridge_tasks.pop(session_id, None)

    return _cb


async def _load_agent_and_workspace(
    agent_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession,
) -> tuple[Agent, uuid.UUID]:
    """Load agent and resolve its primary workspace, verifying ownership.

    Args:
        agent_id: Agent UUID to load.
        user: Verified user making the request.
        db: Database session.

    Returns:
        Tuple of (Agent, workspace_id UUID).

    Raises:
        HTTPException 404: If the agent does not exist or the user has no
            workspace association for it.
    """
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Resolve workspace: find the agent's default workspace owned by this user.
    # Join AgentWorkspace → Workspace to ensure ownership.
    aw_result = await db.execute(
        select(AgentWorkspace).where(
            AgentWorkspace.agent_id == agent_id,
        )
    )
    agent_workspace = aw_result.scalars().first()

    if not agent_workspace:
        raise HTTPException(status_code=404, detail="No workspace found for this agent.")

    workspace_id: uuid.UUID = agent_workspace.workspace_id

    # Verify the workspace belongs to this user.
    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == workspace_id,
            Workspace.user_id == user.id,
        )
    )
    if not ws_result.scalar_one_or_none():
        raise HTTPException(
            status_code=403, detail="Not authorized to access this agent's workspace."
        )

    return agent, workspace_id


@http_router.post("/{agent_id}/test-calls", response_model=TestCallResponse)
async def create_test_call(
    agent_id: uuid.UUID,
    body: TestCallRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> TestCallResponse:
    """Create a new AI-vs-AI test call session for the given agent.

    Starts an AgentTestBridge that connects a simulated caller Realtime session
    to the agent's Realtime session and runs them until the caller ends the call
    or the turn/time limits are reached.

    Args:
        agent_id: Agent UUID to test.
        body: Caller persona and goal for the test scenario.
        user: Verified user making the request.
        db: Database session.

    Returns:
        TestCallResponse with a new session_id.

    Raises:
        HTTPException 404: If agent or workspace not found.
        HTTPException 400: If OpenAI API key is not configured.
    """
    agent, workspace_id = await _load_agent_and_workspace(agent_id, user, db)

    user_uuid = user_id_to_uuid(user.id)
    user_settings = await get_user_api_keys(user_uuid, db, workspace_id=workspace_id)
    if not user_settings or not user_settings.openai_api_key:
        raise HTTPException(
            status_code=400,
            detail="OpenAI API key not configured for this workspace.",
        )

    session_id = str(uuid.uuid4())
    scenario = TestScenario(persona=body.persona, goal=body.goal)

    bridge = AgentTestBridge(
        agent_id=agent_id,
        scenario=scenario,
        db=db,
        user_id=agent.user_id,
        workspace_id=workspace_id,
        openai_api_key=user_settings.openai_api_key,
    )

    await bridge.start()
    task: asyncio.Task[None] = asyncio.create_task(
        bridge.run(), name=f"agent_test_bridge_{session_id}"
    )
    task.add_done_callback(_cleanup_session(session_id))

    _active_bridges[session_id] = bridge
    _bridge_tasks[session_id] = task

    redis = await get_redis()
    await redis.set(
        _redis_key(session_id),
        json.dumps(
            {
                "agent_id": str(agent_id),
                "user_id": user.id,
                "workspace_id": str(workspace_id),
                "scenario": {"persona": body.persona, "goal": body.goal},
                "status": "running",
            }
        ),
        ex=_TTL,
    )

    logger.info("agent_test_session_created", session_id=session_id, agent_id=str(agent_id))
    return TestCallResponse(session_id=session_id)


@http_router.delete("/{agent_id}/test-calls/{session_id}", status_code=204)
async def delete_test_call(
    agent_id: uuid.UUID,
    session_id: str,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Stop and delete an active test call session.

    Args:
        agent_id: Agent UUID (used for routing only; session_id is the key).
        session_id: Test session ID to delete.
        user: Verified user making the request.
        db: Database session.
    """
    # Verify ownership via Redis metadata
    redis = await get_redis()
    raw = await redis.get(_redis_key(session_id))
    if raw:
        state = json.loads(raw)
        if str(state.get("user_id")) != str(user.id):
            raise HTTPException(status_code=403, detail="Access denied")

    bridge = _active_bridges.pop(session_id, None)
    task = _bridge_tasks.pop(session_id, None)

    if bridge:
        await bridge.stop()
    if task and not task.done():
        task.cancel()

    await redis.delete(_redis_key(session_id))
    logger.info("agent_test_session_deleted", session_id=session_id)


@ws_router.websocket("/agent-test/{session_id}")
async def agent_test_websocket(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=""),
) -> None:
    """Stream test call events to a WebSocket client.

    Forwards events from the AgentTestBridge event queue until the session
    completes, errors, or the client disconnects.

    Authentication is done via the 'token' query parameter (JWT bearer token).

    Args:
        websocket: Client WebSocket connection.
        session_id: Test session ID to stream events from.
        token: JWT access token for authentication.
    """
    from app.core.auth import decode_access_token

    # Verify token before accepting the connection
    payload = decode_access_token(token) if token else None
    if not payload:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    # Verify the session belongs to this user
    redis = await get_redis()
    raw = await redis.get(_redis_key(session_id))
    if raw:
        state = json.loads(raw)
        token_user_id = payload.get("sub")
        if token_user_id is None or str(state.get("user_id")) != str(token_user_id):
            await websocket.close(code=4003, reason="Access denied")
            return

    await websocket.accept()

    bridge = _active_bridges.get(session_id)
    if not bridge:
        await websocket.send_json({"type": "session.error", "message": "Session not found"})
        await websocket.close(code=4004)
        return

    await websocket.send_json({"type": "session.started"})

    try:
        while True:
            try:
                event: dict[str, Any] = await asyncio.wait_for(bridge.events.get(), timeout=30)
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue

            await websocket.send_json(event)
            if event.get("type") in ("session.complete", "session.error"):
                break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.exception("agent_test_ws_error", session_id=session_id, error=str(e))
    finally:
        await websocket.close()
