"""Unit tests for AgentTestBridge."""

from __future__ import annotations

import pytest

from app.services.agent_test_bridge import TestScenario, build_caller_system_prompt


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
