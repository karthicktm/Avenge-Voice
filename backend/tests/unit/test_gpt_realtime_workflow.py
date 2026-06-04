"""Unit tests for GPTRealtimeSession workflow integration.

Tests verify that when a workflow is attached to an agent:
1. The `categorize` tool is injected into the session config so the LLM can call it.
2. The workflow routing note is appended to session instructions.
3. Neither injection occurs when no workflow is attached.
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.gpt_realtime import GPTRealtimeSession

# ── helpers ────────────────────────────────────────────────────────────────────


def _make_session(agent_config: dict[str, Any] | None = None) -> GPTRealtimeSession:
    """Return a GPTRealtimeSession instance with minimal mocked dependencies."""
    db = AsyncMock()
    # workspace query: return no workspace so the timezone branch is skipped cleanly
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session = GPTRealtimeSession(
        db=db,
        user_id=1,
        agent_config=agent_config
        or {
            "system_prompt": "You are a helpful agent.",
            "enabled_tools": [],
            "enabled_tool_ids": {},
            "tool_configs": {},
            "language": "en-US",
            "voice": "shimmer",
            "temperature": 0.8,
            "agent_id": str(uuid.uuid4()),
            "llm_model": "gpt-realtime",
            "turn_detection_mode": "normal",
            "turn_detection_threshold": 0.5,
            "turn_detection_prefix_padding_ms": 300,
            "turn_detection_silence_duration_ms": 500,
            "transcription_model": "gpt-4o-transcribe",
        },
        workspace_id=None,
    )
    # Mock the OpenAI connection so session.update calls can be captured
    session.connection = AsyncMock()
    session.connection.session = AsyncMock()
    session.connection.session.update = AsyncMock()
    # Mock tool registry to return an empty tool list by default
    session.tool_registry = MagicMock()
    session.tool_registry.get_all_tool_definitions = MagicMock(return_value=[])
    return session


def _make_workflow_executor(has_categorize_node: bool = True) -> MagicMock:
    """Return a mock WorkflowExecutor."""
    executor = MagicMock()
    if has_categorize_node:
        executor.nodes_by_id = {
            "entry-1": {"id": "entry-1", "type": "entry"},
            "cat-1": {"id": "cat-1", "type": "categorize", "config": {"tree_name": "issues"}},
        }
        # route() from entry → categorize node (used by _build_workflow_entry_routing_note)
        executor.route = MagicMock(return_value="cat-1")
    else:
        executor.nodes_by_id = {
            "entry-1": {"id": "entry-1", "type": "entry"},
            "instr-1": {"id": "instr-1", "type": "instruction", "config": {"template": "Hello"}},
        }
        executor.route = MagicMock(return_value="instr-1")
    return executor


def _get_session_update_call(session: GPTRealtimeSession) -> dict[str, Any]:
    """Return the `session` kwarg from the first session.update() call."""
    call_args = session.connection.session.update.call_args
    assert call_args is not None, "session.update was never called"
    result: dict[str, Any] = call_args.kwargs.get("session") or call_args.args[0]
    return result


# ── categorize tool injection ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_categorize_tool_injected_when_workflow_has_categorize_node() -> None:
    """session.update includes the `categorize` tool when the workflow has a categorize node."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor(has_categorize_node=True)

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    tool_names = [t.get("name") for t in sent_config.get("tools", [])]
    assert "categorize" in tool_names


@pytest.mark.asyncio
async def test_categorize_tool_not_injected_without_workflow() -> None:
    """session.update does NOT include `categorize` when no workflow is attached."""
    session = _make_session()
    # workflow_executor is None by default

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    tool_names = [t.get("name") for t in sent_config.get("tools", [])]
    assert "categorize" not in tool_names


@pytest.mark.asyncio
async def test_categorize_tool_not_injected_when_workflow_has_no_categorize_node() -> None:
    """session.update does NOT include `categorize` when workflow contains no categorize nodes."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor(has_categorize_node=False)

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    tool_names = [t.get("name") for t in sent_config.get("tools", [])]
    assert "categorize" not in tool_names


@pytest.mark.asyncio
async def test_categorize_tool_not_duplicated_when_already_enabled() -> None:
    """Categorize is not added twice if it is already in the registry's tool list."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor(has_categorize_node=True)
    # Simulate agent already having categorization enabled
    assert session.tool_registry is not None
    session.tool_registry.get_all_tool_definitions = MagicMock(  # type: ignore[method-assign]
        return_value=[{"type": "function", "name": "categorize"}]
    )

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    categorize_count = sum(1 for t in sent_config.get("tools", []) if t.get("name") == "categorize")
    assert categorize_count == 1


# ── routing note injection ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_routing_note_appended_to_instructions_when_workflow_active() -> None:
    """session.update instructions include the WORKFLOW ROUTING note when executor is active."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor(has_categorize_node=True)

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "WORKFLOW ROUTING" in instructions
    assert "categorize" in instructions


@pytest.mark.asyncio
async def test_routing_note_not_present_without_workflow() -> None:
    """session.update instructions do NOT contain routing note when no workflow is attached."""
    session = _make_session()
    # workflow_executor is None by default

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "WORKFLOW ROUTING" not in instructions


@pytest.mark.asyncio
async def test_routing_note_not_present_when_workflow_has_no_categorize_node() -> None:
    """No routing note when the workflow's first node is not a categorize node."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor(has_categorize_node=False)

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "WORKFLOW ROUTING" not in instructions


@pytest.mark.asyncio
async def test_session_instructions_attr_includes_routing_note() -> None:
    """_session_instructions (used by trigger_initial_greeting) also gets the routing note."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor(has_categorize_node=True)

    await session._configure_session()

    assert "WORKFLOW ROUTING" in (session._session_instructions or "")


# ── non-categorize entry ───────────────────────────────────────────────────────


def _make_workflow_executor_instruction_entry(
    template: str = "Hello, how can I help?",
) -> MagicMock:
    """Workflow: entry → instruction node (no categorize)."""
    executor = MagicMock()
    executor.nodes_by_id = {
        "entry-1": {"id": "entry-1", "type": "entry"},
        "instr-1": {
            "id": "instr-1",
            "type": "instruction",
            "config": {"template": template},
        },
    }
    executor.current_node_id = "entry-1"
    executor.current_node = executor.nodes_by_id["entry-1"]
    executor.route = MagicMock(return_value="instr-1")
    executor.build_node_instruction = MagicMock(return_value=template)
    return executor


def _make_workflow_executor_transfer_entry(
    target: str = "+1234567890", template: str = "Transferring you now."
) -> MagicMock:
    """Workflow: entry → transfer node (no categorize)."""
    executor = MagicMock()
    executor.nodes_by_id = {
        "entry-1": {"id": "entry-1", "type": "entry"},
        "xfer-1": {
            "id": "xfer-1",
            "type": "transfer",
            "config": {"transfer_target": target, "template": template},
        },
    }
    executor.current_node_id = "entry-1"
    executor.current_node = executor.nodes_by_id["entry-1"]
    executor.route = MagicMock(return_value="xfer-1")
    executor.build_node_instruction = MagicMock(return_value=template)
    executor.resolve_template = MagicMock(return_value=target)
    return executor


@pytest.mark.asyncio
async def test_instruction_entry_node_directive_in_session_instructions() -> None:
    """session.update instructions include 'Say exactly' when entry routes to instruction node."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor_instruction_entry("Welcome to support.")

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "Welcome to support." in instructions


@pytest.mark.asyncio
async def test_transfer_entry_node_directive_in_session_instructions() -> None:
    """session.update instructions include transfer target when entry routes to transfer node."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor_transfer_entry(target="+1234567890")

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "+1234567890" in instructions


@pytest.mark.asyncio
async def test_non_categorize_entry_does_not_add_routing_note() -> None:
    """WORKFLOW ROUTING note is not added when entry routes to a non-categorize node."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor_instruction_entry()

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "WORKFLOW ROUTING" not in instructions


@pytest.mark.asyncio
async def test_executor_advanced_past_entry_for_instruction_node() -> None:
    """Executor current_node_id is advanced to the instruction node at session start."""
    session = _make_session()
    executor = _make_workflow_executor_instruction_entry()
    session.workflow_executor = executor

    await session._configure_session()

    assert executor.current_node_id == "instr-1"


@pytest.mark.asyncio
async def test_session_instructions_attr_includes_start_directive() -> None:
    """_session_instructions also includes the start directive for non-categorize entry."""
    session = _make_session()
    session.workflow_executor = _make_workflow_executor_instruction_entry("Opening script here.")

    await session._configure_session()

    assert "Opening script here." in (session._session_instructions or "")


# ── skip duplicate greeting ────────────────────────────────────────────────────


def _make_session_with_greeting(greeting: str = "Hello, welcome!") -> GPTRealtimeSession:
    """Return a session whose agent_config includes an initial_greeting."""
    import uuid

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))
    session = GPTRealtimeSession(
        db=db,
        user_id=1,
        agent_config={
            "system_prompt": "You are a helpful agent.",
            "enabled_tools": [],
            "enabled_tool_ids": {},
            "tool_configs": {},
            "language": "en-US",
            "voice": "shimmer",
            "temperature": 0.8,
            "agent_id": str(uuid.uuid4()),
            "llm_model": "gpt-realtime",
            "turn_detection_mode": "normal",
            "turn_detection_threshold": 0.5,
            "turn_detection_prefix_padding_ms": 300,
            "turn_detection_silence_duration_ms": 500,
            "transcription_model": "gpt-4o-transcribe",
            "initial_greeting": greeting,
        },
        workspace_id=None,
    )
    session.connection = AsyncMock()
    session.connection.session = AsyncMock()
    session.connection.session.update = AsyncMock()
    session.tool_registry = MagicMock()
    session.tool_registry.get_all_tool_definitions = MagicMock(return_value=[])
    return session


@pytest.mark.asyncio
async def test_workflow_instruction_directive_suppressed_when_initial_greeting_set() -> None:
    """[WORKFLOW] directive is NOT injected when agent has initial_greeting and entry→instruction."""
    session = _make_session_with_greeting("Hello, welcome to our service!")
    session.workflow_executor = _make_workflow_executor_instruction_entry("Welcome to support.")

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "[WORKFLOW]" not in instructions


@pytest.mark.asyncio
async def test_executor_still_advanced_when_greeting_suppressed() -> None:
    """Executor current_node_id is advanced even when the greeting directive is suppressed."""
    session = _make_session_with_greeting("Hello!")
    executor = _make_workflow_executor_instruction_entry()
    session.workflow_executor = executor

    await session._configure_session()

    assert executor.current_node_id == "instr-1"


@pytest.mark.asyncio
async def test_transfer_directive_not_suppressed_when_initial_greeting_set() -> None:
    """Transfer directive is still injected even when agent has initial_greeting (not greeting-type)."""
    session = _make_session_with_greeting("Hello!")
    session.workflow_executor = _make_workflow_executor_transfer_entry(target="+1234567890")

    await session._configure_session()

    sent_config = _get_session_update_call(session)
    instructions: str = sent_config.get("instructions", "")
    assert "+1234567890" in instructions
