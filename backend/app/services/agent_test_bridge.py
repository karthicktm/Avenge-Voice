"""Agent test call bridge — connects a caller AI session to a live voice agent session."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TestScenario:
    persona: str
    goal: str


def build_caller_system_prompt(scenario: TestScenario) -> str:
    return (
        "You are simulating a caller on a phone support line.\n"
        f"Persona: {scenario.persona}\n"
        f"Goal: {scenario.goal}\n"
        "Speak naturally. One or two sentences per turn.\n"
        "When your goal is complete or you choose to end the call, use end_call()."
    )
