# backend/tests/unit/test_agent_test_api.py
"""Unit tests for the agent test call API."""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import fakeredis
import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.db.session import get_db
from app.main import app
from app.models.user import User

AGENT_ID = str(uuid.uuid4())
WORKSPACE_ID = str(uuid.uuid4())

MOCK_USER_SETTINGS = MagicMock()
MOCK_USER_SETTINGS.openai_api_key = "sk-test-key"


def _make_mock_agent() -> MagicMock:
    agent = MagicMock()
    agent.id = uuid.UUID(AGENT_ID)
    agent.is_active = True
    agent.pricing_tier = "premium"
    agent.system_prompt = "You are a support agent."
    agent.language = "en-US"
    agent.voice = "shimmer"
    agent.enabled_tools = []
    agent.enabled_tool_ids = {}
    agent.tool_configs = {}
    agent.provider_config = {"llm_model": "gpt-4o-realtime-preview"}
    agent.workflow_id = None
    agent.turn_detection_mode = "normal"
    agent.turn_detection_threshold = 0.5
    agent.turn_detection_prefix_padding_ms = 300
    agent.turn_detection_silence_duration_ms = 500
    agent.transcription_model = "gpt-4o-mini-transcribe"
    agent.temperature = 0.7
    agent.user_id = 1
    return agent


def _make_test_user() -> User:
    user = User(
        email="test@example.com",
        hashed_password="hashed",  # noqa: S106
        full_name="Test User",
        is_active=True,
        is_superuser=False,
        email_verified=True,
    )
    user.id = 1  # type: ignore[assignment]
    return user


@pytest.mark.asyncio
async def test_create_test_call_returns_session_id() -> None:
    test_user = _make_test_user()
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    mock_db = AsyncMock()
    ws_check = MagicMock()
    ws_check.scalar_one_or_none.return_value = MagicMock()
    mock_db.execute.return_value = ws_check

    async def override_db() -> AsyncGenerator[Any, None]:
        yield mock_db

    async def override_user() -> User:
        return test_user

    mock_bridge = AsyncMock()
    mock_bridge.start = AsyncMock()
    mock_bridge.events = asyncio.Queue()

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    async def patched_get_redis() -> Any:
        return fake_redis

    try:
        with (
            patch("app.api.agent_test.get_redis", patched_get_redis),
            patch("app.api.agent_test.get_user_api_keys", return_value=MOCK_USER_SETTINGS),
            patch(
                "app.api.agent_test._load_agent_and_workspace",
                return_value=(_make_mock_agent(), uuid.UUID(WORKSPACE_ID)),
            ),
            patch("app.api.agent_test.AgentTestBridge", return_value=mock_bridge),
        ):
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/agents/{AGENT_ID}/test-calls",
                    json={"persona": "angry caller", "goal": "get refund"},
                    headers={"Authorization": "Bearer test"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    await fake_redis.aclose()


@pytest.mark.asyncio
async def test_create_test_call_404_for_missing_agent() -> None:
    test_user = _make_test_user()

    async def override_db() -> AsyncGenerator[Any, None]:
        yield AsyncMock()

    async def override_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user

    try:
        with patch(
            "app.api.agent_test._load_agent_and_workspace",
            side_effect=HTTPException(status_code=404, detail="Agent not found"),
        ):
            transport = ASGITransport(app=app)  # type: ignore[arg-type]
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/agents/{AGENT_ID}/test-calls",
                    json={"persona": "caller", "goal": "help"},
                    headers={"Authorization": "Bearer test"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
