"""Unit tests for AgentTestBridge."""

from __future__ import annotations

import asyncio
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

    b64 = base64.b64encode(b"\xAA\xBB").decode()
    await bridge._agent_audio_queue.put(b64)

    async def _side_effect(**kwargs: object) -> None:
        bridge._stop_event.set()

    bridge._caller_conn.input_audio_buffer.append.side_effect = _side_effect

    await bridge._forward_agent_audio_to_caller()

    bridge._caller_conn.input_audio_buffer.append.assert_called_once_with(audio=b64)


def _make_bridge() -> "AgentTestBridge":
    bridge = AgentTestBridge(
        agent_id=uuid.uuid4(),
        scenario=TestScenario(persona="test", goal="test"),
        db=AsyncMock(),
        user_id=1,
        workspace_id=uuid.uuid4(),
        openai_api_key="sk-test",
    )
    return bridge
