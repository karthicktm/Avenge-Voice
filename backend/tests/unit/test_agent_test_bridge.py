"""Unit tests for AgentTestBridge."""

from __future__ import annotations

import base64
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.agent_test_bridge import AgentTestBridge, TestScenario, build_caller_system_prompt


def test_build_caller_system_prompt_contains_persona_and_goal() -> None:
    scenario = TestScenario(
        persona="frustrated customer with a broken product",
        goal="get a full refund",
    )
    prompt = build_caller_system_prompt(scenario)
    assert "frustrated customer with a broken product" in prompt
    assert "get a full refund" in prompt


def test_build_caller_system_prompt_contains_end_call_instruction() -> None:
    scenario = TestScenario(persona="a caller", goal="test the agent")
    prompt = build_caller_system_prompt(scenario)
    assert "end_call" in prompt


def test_build_caller_system_prompt_has_persona_and_goal_labels() -> None:
    scenario = TestScenario(persona="p", goal="g")
    prompt = build_caller_system_prompt(scenario)
    assert "Persona:" in prompt
    assert "Goal:" in prompt


@pytest.mark.asyncio
async def test_forward_caller_audio_to_agent_calls_send_audio() -> None:
    """Audio chunks from caller queue are forwarded to agent via send_audio."""
    bridge = _make_bridge()
    bridge._agent_session = AsyncMock()
    bridge._agent_session.send_audio = AsyncMock()

    raw_bytes = b"\x00\x01\x02\x03"
    b64 = base64.b64encode(raw_bytes).decode()
    await bridge._caller_audio_queue.put(b64)

    # Set stop after one item is processed
    async def _side_effect(data: bytes) -> None:
        bridge._stop_event.set()

    bridge._agent_session.send_audio.side_effect = _side_effect

    await bridge._forward_caller_audio_to_agent()

    bridge._agent_session.send_audio.assert_called_once_with(raw_bytes)


@pytest.mark.asyncio
async def test_forward_agent_audio_to_caller_calls_append() -> None:
    """Audio chunks from agent queue are forwarded to caller via input_audio_buffer.append."""
    bridge = _make_bridge()
    bridge._caller_conn = AsyncMock()
    bridge._caller_conn.input_audio_buffer = AsyncMock()
    bridge._caller_conn.input_audio_buffer.append = AsyncMock()

    b64 = base64.b64encode(b"\xaa\xbb").decode()
    await bridge._agent_audio_queue.put(b64)

    async def _side_effect(**kwargs: object) -> None:
        bridge._stop_event.set()

    bridge._caller_conn.input_audio_buffer.append.side_effect = _side_effect

    await bridge._forward_agent_audio_to_caller()

    bridge._caller_conn.input_audio_buffer.append.assert_called_once_with(audio=b64)


@pytest.mark.asyncio
async def test_caller_event_loop_emits_speech_delta_and_done() -> None:
    """Caller transcript events are emitted to the events queue."""
    bridge = _make_bridge()

    delta_event = MagicMock()
    delta_event.type = "response.audio_transcript.delta"
    delta_event.delta = "Hello, I need"

    done_event = MagicMock()
    done_event.type = "response.audio_transcript.done"
    done_event.transcript = "Hello, I need help."

    stop_event = MagicMock()
    stop_event.type = "session.created"  # unrecognized — just breaks the loop

    async def _fake_conn_iter():
        yield delta_event
        yield done_event
        bridge._stop_event.set()
        yield stop_event

    bridge._caller_conn = _fake_conn_iter()

    await bridge._caller_event_loop()

    events = []
    while not bridge.events.empty():
        events.append(await bridge.events.get())

    types = [e["type"] for e in events]
    assert "caller.speech.delta" in types
    assert "caller.speech.done" in types
    delta_texts = [e["text"] for e in events if e["type"] == "caller.speech.delta"]
    assert "Hello, I need" in delta_texts


@pytest.mark.asyncio
async def test_caller_event_loop_end_call_sets_complete() -> None:
    """end_call function invocation emits session.complete and sets stop_event."""
    bridge = _make_bridge()

    end_call_event = MagicMock()
    end_call_event.type = "response.function_call_arguments.done"
    end_call_event.name = "end_call"
    end_call_event.arguments = "{}"

    async def _fake_conn_iter():
        yield end_call_event

    bridge._caller_conn = _fake_conn_iter()

    await bridge._caller_event_loop()

    assert bridge._stop_event.is_set()
    events = []
    while not bridge.events.empty():
        events.append(await bridge.events.get())
    complete_events = [e for e in events if e["type"] == "session.complete"]
    assert len(complete_events) == 1
    assert complete_events[0]["reason"] == "end_call"


@pytest.mark.asyncio
async def test_agent_event_loop_emits_speech_done() -> None:
    """Agent transcript done event is emitted to events queue."""
    bridge = _make_bridge()
    bridge._agent_session = MagicMock()
    bridge._agent_session.handle_function_call_event = AsyncMock(return_value={"success": True})
    bridge._agent_session.workflow_executor = None

    done_event = MagicMock()
    done_event.type = "response.audio_transcript.done"
    done_event.transcript = "Thank you for calling."

    async def _fake_conn_iter():
        yield done_event
        bridge._stop_event.set()

    bridge._agent_session.connection = _fake_conn_iter()

    await bridge._agent_event_loop()

    events = []
    while not bridge.events.empty():
        events.append(await bridge.events.get())

    done_events = [e for e in events if e["type"] == "agent.speech.done"]
    assert len(done_events) == 1
    assert done_events[0]["text"] == "Thank you for calling."


@pytest.mark.asyncio
async def test_agent_event_loop_emits_tool_call_and_result() -> None:
    """Tool call events are emitted before and after execution."""
    bridge = _make_bridge()
    bridge._agent_session = MagicMock()
    bridge._agent_session.handle_function_call_event = AsyncMock(
        return_value={"success": True, "matched": True}
    )
    bridge._agent_session.workflow_executor = None

    tool_event = MagicMock()
    tool_event.type = "response.function_call_arguments.done"
    tool_event.name = "categorize"
    tool_event.arguments = '{"description": "broken product"}'

    async def _fake_conn_iter():
        yield tool_event
        bridge._stop_event.set()

    bridge._agent_session.connection = _fake_conn_iter()

    await bridge._agent_event_loop()

    events = []
    while not bridge.events.empty():
        events.append(await bridge.events.get())

    types = [e["type"] for e in events]
    assert "agent.tool_call" in types
    assert "agent.tool_result" in types

    tool_call_event = next(e for e in events if e["type"] == "agent.tool_call")
    assert tool_call_event["tool"] == "categorize"
    assert tool_call_event["args"] == {"description": "broken product"}


def _make_bridge() -> AgentTestBridge:
    bridge = AgentTestBridge(
        agent_id=uuid.uuid4(),
        scenario=TestScenario(persona="test", goal="test"),
        db=AsyncMock(),
        user_id=1,
        workspace_id=uuid.uuid4(),
        openai_api_key="sk-test",
    )
    return bridge
