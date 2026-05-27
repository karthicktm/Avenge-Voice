"""Agent test call bridge — connects a caller AI session to a live voice agent session."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from openai import AsyncOpenAI

from app.services.gpt_realtime import GPTRealtimeSession

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


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


_END_CALL_TOOL = {
    "type": "function",
    "name": "end_call",
    "description": "End the call when your goal is complete or you wish to end the conversation.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

MAX_TURNS = 50
MAX_DURATION_SECONDS = 600


class AgentTestBridge:
    """Bridges a caller Realtime session to a voice agent Realtime session."""

    def __init__(
        self,
        agent_id: uuid.UUID,
        scenario: TestScenario,
        db: "AsyncSession",
        user_id: int,
        workspace_id: uuid.UUID,
        openai_api_key: str,
    ) -> None:
        self.agent_id = agent_id
        self.scenario = scenario
        self.db = db
        self.user_id = user_id
        self.workspace_id = workspace_id
        self.openai_api_key = openai_api_key

        self.events: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._stop_event = asyncio.Event()
        self._caller_conn: Any = None
        self._agent_session: GPTRealtimeSession | None = None
        self._caller_audio_queue: asyncio.Queue[str] = asyncio.Queue()
        self._agent_audio_queue: asyncio.Queue[str] = asyncio.Queue()
        self._turn_count = 0
        self._log = logger.bind(agent_id=str(agent_id))

    async def start(self) -> None:
        await self._setup_agent_session()
        await self._connect_caller_session()
        await self._caller_conn.response.create()

    async def run(self) -> None:
        start_time = asyncio.get_event_loop().time()

        async def _guard() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(5)
                if self._turn_count >= MAX_TURNS:
                    await self.events.put({"type": "session.complete", "reason": "max_turns"})
                    self._stop_event.set()
                    return
                if asyncio.get_event_loop().time() - start_time >= MAX_DURATION_SECONDS:
                    await self.events.put({"type": "session.complete", "reason": "max_duration"})
                    self._stop_event.set()
                    return

        try:
            await asyncio.gather(
                self._caller_event_loop(),
                self._agent_event_loop(),
                self._forward_caller_audio_to_agent(),
                self._forward_agent_audio_to_caller(),
                _guard(),
                return_exceptions=True,
            )
        except Exception as e:
            await self.events.put({"type": "session.error", "message": str(e)})

    async def stop(self) -> None:
        self._stop_event.set()
        if self._caller_conn:
            try:
                await self._caller_conn.__aexit__(None, None, None)
            except Exception:
                pass
        if self._agent_session:
            try:
                await self._agent_session.__aexit__(None, None, None)
            except Exception:
                pass

    # ── session setup ────────────────────────────────────────────────────────

    async def _setup_agent_session(self) -> None:
        pass  # implemented in Task 4

    async def _connect_caller_session(self) -> None:
        pass  # implemented in Task 3

    # ── audio forwarding ─────────────────────────────────────────────────────

    async def _forward_caller_audio_to_agent(self) -> None:
        pass  # implemented in Task 5

    async def _forward_agent_audio_to_caller(self) -> None:
        pass  # implemented in Task 5

    # ── event loops ──────────────────────────────────────────────────────────

    async def _caller_event_loop(self) -> None:
        pass  # implemented in Task 6

    async def _agent_event_loop(self) -> None:
        pass  # implemented in Task 7
