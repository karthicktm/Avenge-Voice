"""Unit tests for the workflow test session API."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.db.redis import get_redis
from app.db.session import get_db
from app.main import app
from app.models.user import User

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncSession

WORKFLOW_ID = str(uuid.uuid4())
WORKSPACE_ID = str(uuid.uuid4())

MOCK_WORKFLOW = MagicMock()
MOCK_WORKFLOW.id = uuid.UUID(WORKFLOW_ID)
MOCK_WORKFLOW.workspace_id = uuid.UUID(WORKSPACE_ID)
MOCK_WORKFLOW.nodes = [
    {"id": "n1", "type": "entry", "label": "Entry"},
    {"id": "n2", "type": "categorize", "label": "Categorize", "config": {"tree_name": "test_tree"}},
    {"id": "n3", "type": "transfer", "label": "Transfer"},
]
MOCK_WORKFLOW.edges = [
    {"id": "e1", "from": "n1", "to": "n2"},
    {"id": "e2", "from": "n2", "to": "n3"},
]

MOCK_USER_SETTINGS = MagicMock()
MOCK_USER_SETTINGS.openai_api_key = "sk-test-key"


def _make_test_user() -> User:
    user = User(
        email="testuser@example.com",
        hashed_password="hashed_pw",  # noqa: S106
        full_name="Test User",
        is_active=True,
        is_superuser=False,
        email_verified=True,
    )
    user.id = 1  # type: ignore[assignment]
    return user


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[AsyncClient, None]:
    """Shared async HTTP client with auth + DB overrides for step tests."""
    test_user = _make_test_user()

    mock_db = AsyncMock()
    mock_db.get.return_value = MOCK_WORKFLOW
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = MagicMock()
    mock_db.execute.return_value = mock_execute_result

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db  # type: ignore[misc]

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    try:
        with patch("app.api.workflow_test.get_user_api_keys", return_value=MOCK_USER_SETTINGS):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                yield client
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_start_creates_redis_session() -> None:
    """POSTing to start creates a Redis session with is_test=True."""
    test_user = _make_test_user()
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    mock_db = AsyncMock()
    mock_db.get.return_value = MOCK_WORKFLOW
    # scalar_one_or_none() is a sync call on the result of db.execute(); return a
    # truthy MagicMock so the workspace ownership check passes.
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = MagicMock()
    mock_db.execute.return_value = mock_execute_result

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db  # type: ignore[misc]

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    # Patch get_redis in the workflow_test module (where it was imported) so direct
    # calls like `await get_redis()` in the endpoint are intercepted.
    async def patched_get_redis() -> Any:
        return fake_redis

    try:
        with (
            patch("app.api.workflow_test.get_redis", patched_get_redis),
            patch("app.api.workflow_test.get_user_api_keys", return_value=MOCK_USER_SETTINGS),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/workflows/{WORKFLOW_ID}/test/start",
                    headers={"Authorization": "Bearer test-token"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["current_node_type"] == "entry"
    assert data["is_complete"] is False

    # Verify is_test flag stored in Redis
    session_key = f"wf_test_session:{data['session_id']}"
    raw = await fake_redis.get(session_key)
    assert raw is not None
    stored = json.loads(raw)
    assert stored["is_test"] is True

    await fake_redis.aclose()


@pytest.mark.asyncio
async def test_start_returns_404_for_missing_workflow() -> None:
    """POSTing to start with an unknown workflow_id returns 404."""
    test_user = _make_test_user()
    fake_redis = fakeredis.FakeAsyncRedis(decode_responses=True)

    mock_db = AsyncMock()
    mock_db.get.return_value = None  # workflow not found

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db  # type: ignore[misc]

    async def override_get_current_user() -> User:
        return test_user

    async def override_get_redis() -> Any:
        return fake_redis

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    app.dependency_overrides[get_redis] = override_get_redis

    transport = ASGITransport(app=app)  # type: ignore[arg-type]
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/v1/workflows/{uuid.uuid4()}/test/start",
                headers={"Authorization": "Bearer test-token"},
            )
    finally:
        app.dependency_overrides.clear()

    await fake_redis.aclose()

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Workflow not found"


SESSION_ID = str(uuid.uuid4())
ENTRY_STATE = {
    "workflow_id": WORKFLOW_ID,
    "workspace_id": WORKSPACE_ID,
    "nodes": MOCK_WORKFLOW.nodes,
    "edges": MOCK_WORKFLOW.edges,
    "current_node_id": "n1",
    "context_bag": {},
    "is_test": True,
}
CATEGORIZE_STATE = {**ENTRY_STATE, "current_node_id": "n2"}


@pytest.mark.asyncio
async def test_step_entry_auto_advances() -> None:
    """POSTing to step on an entry node auto-advances to the next node."""
    test_user = _make_test_user()

    mock_db = AsyncMock()
    mock_db.get.return_value = MOCK_WORKFLOW
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = MagicMock()
    mock_db.execute.return_value = mock_execute_result

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db  # type: ignore[misc]

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    # mock_redis.get returns the session JSON for the first call (load_executor)
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(ENTRY_STATE)
    mock_redis.set = AsyncMock()

    async def patched_get_redis() -> Any:
        return mock_redis

    try:
        with (
            patch("app.api.workflow_test.get_redis", patched_get_redis),
            patch("app.api.workflow_test.get_user_api_keys", return_value=MOCK_USER_SETTINGS),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/workflows/{WORKFLOW_ID}/test/{SESSION_ID}/step",
                    json={"caller_input": ""},
                    headers={"Authorization": "Bearer test-token"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert data["current_node_type"] == "categorize"


NODES_WITH_CONDITION = [
    {"id": "n1", "type": "entry", "label": "Entry"},
    {"id": "n2", "type": "categorize", "label": "Categorize", "config": {"tree_name": "t"}},
    {
        "id": "n3",
        "type": "condition",
        "label": "Condition",
        "config": {"condition": "action_type == transfer"},
    },
    {
        "id": "n4",
        "type": "transfer",
        "label": "Transfer",
        "config": {"template": "Transferring to {{transfer_target}}"},
    },
    {"id": "n5", "type": "end_call", "label": "End Call"},
]
EDGES_WITH_CONDITION = [
    {"id": "e1", "from": "n1", "to": "n2"},
    {"id": "e2", "from": "n2", "to": "n3"},
    {"id": "e3", "from": "n3", "to": "n4", "sourceHandle": "yes"},
    {"id": "e4", "from": "n3", "to": "n5", "sourceHandle": "no"},
    {"id": "e5", "from": "n4", "to": "n5"},
]
CONDITION_STATE = {
    "workflow_id": WORKFLOW_ID,
    "workspace_id": WORKSPACE_ID,
    "nodes": NODES_WITH_CONDITION,
    "edges": EDGES_WITH_CONDITION,
    "current_node_id": "n3",
    "context_bag": {"action_type": "transfer", "transfer_target": "+491234"},
    "is_test": True,
}
TRANSFER_STATE = {**CONDITION_STATE, "current_node_id": "n4"}


@pytest.mark.asyncio
async def test_step_condition_routes_to_yes(async_client: AsyncClient) -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(CONDITION_STATE)
    mock_redis.set = AsyncMock()

    async def patched_get_redis() -> Any:
        return mock_redis

    with patch("app.api.workflow_test.get_redis", patched_get_redis):
        resp = await async_client.post(
            f"/api/v1/workflows/{WORKFLOW_ID}/test/{SESSION_ID}/step",
            json={"caller_input": ""},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["current_node_type"] == "transfer"


@pytest.mark.asyncio
async def test_step_transfer_node_simulated(async_client: AsyncClient) -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(TRANSFER_STATE)
    mock_redis.set = AsyncMock()

    async def patched_get_redis() -> Any:
        return mock_redis

    with patch("app.api.workflow_test.get_redis", patched_get_redis):
        resp = await async_client.post(
            f"/api/v1/workflows/{WORKFLOW_ID}/test/{SESSION_ID}/step",
            json={"caller_input": ""},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["simulated"] is True
    assert data["simulation_detail"]["node_type"] == "transfer"
    assert data["simulation_detail"]["would_have"]["target"] == "+491234"


@pytest.mark.asyncio
async def test_step_categorize_runs_pipeline() -> None:
    """POSTing to step on a categorize node invokes run_categorize with caller input."""
    test_user = _make_test_user()

    mock_db = AsyncMock()
    mock_db.get.return_value = MOCK_WORKFLOW
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = MagicMock()
    mock_db.execute.return_value = mock_execute_result

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield mock_db  # type: ignore[misc]

    async def override_get_current_user() -> User:
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    transport = ASGITransport(app=app)  # type: ignore[arg-type]

    # First get call returns session JSON; second (prewarmed trees) returns None
    mock_redis = AsyncMock()
    mock_redis.get.side_effect = [json.dumps(CATEGORIZE_STATE), None]
    mock_redis.set = AsyncMock()

    async def patched_get_redis() -> Any:
        return mock_redis

    mock_run = AsyncMock()

    try:
        with (
            patch("app.api.workflow_test.get_redis", patched_get_redis),
            patch("app.api.workflow_test.get_user_api_keys", return_value=MOCK_USER_SETTINGS),
            patch(
                "app.services.workflow_engine.executor.WorkflowExecutor.run_categorize",
                mock_run,
            ),
        ):
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                resp = await client.post(
                    f"/api/v1/workflows/{WORKFLOW_ID}/test/{SESSION_ID}/step",
                    json={"caller_input": "I need billing help"},
                    headers={"Authorization": "Bearer test-token"},
                )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    data = resp.json()
    assert "elapsed_ms" in data
    mock_run.assert_called_once()


@pytest.mark.asyncio
async def test_patch_context_updates_bag(async_client: AsyncClient) -> None:
    mock_redis = AsyncMock()
    mock_redis.get.return_value = json.dumps(CATEGORIZE_STATE)
    mock_redis.set = AsyncMock()

    async def patched_get_redis() -> Any:
        return mock_redis

    with patch("app.api.workflow_test.get_redis", patched_get_redis):
        resp = await async_client.patch(
            f"/api/v1/workflows/{WORKFLOW_ID}/test/{SESSION_ID}/context",
            json={"context_bag": {"action_type": "emergency", "custom_key": "custom_val"}},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["context_bag"]["action_type"] == "emergency"
    assert data["context_bag"]["custom_key"] == "custom_val"


@pytest.mark.asyncio
async def test_delete_session(async_client: AsyncClient) -> None:
    mock_redis = AsyncMock()
    mock_redis.delete = AsyncMock()

    async def patched_get_redis() -> Any:
        return mock_redis

    with patch("app.api.workflow_test.get_redis", patched_get_redis):
        resp = await async_client.delete(
            f"/api/v1/workflows/{WORKFLOW_ID}/test/{SESSION_ID}",
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 204
    mock_redis.delete.assert_called_once_with(f"wf_test_session:{SESSION_ID}")
