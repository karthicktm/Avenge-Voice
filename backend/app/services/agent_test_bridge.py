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
        from sqlalchemy import select

        from app.models.agent import Agent

        result = await self.db.execute(select(Agent).where(Agent.id == self.agent_id))
        agent = result.scalar_one_or_none()
        if not agent:
            raise ValueError(f"Agent {self.agent_id} not found")

        agent_config: dict[str, Any] = {
            "system_prompt": agent.system_prompt,
            "enabled_tools": agent.enabled_tools or [],
            "enabled_tool_ids": agent.enabled_tool_ids or {},
            "tool_configs": agent.tool_configs or {},
            "language": agent.language or "en-US",
            "voice": agent.voice or "shimmer",
            "temperature": agent.temperature,
            "agent_id": str(agent.id),
            "llm_model": (agent.provider_config or {}).get("llm_model", "gpt-4o-realtime-preview"),
            "turn_detection_mode": agent.turn_detection_mode or "normal",
            "turn_detection_threshold": agent.turn_detection_threshold,
            "turn_detection_prefix_padding_ms": agent.turn_detection_prefix_padding_ms,
            "turn_detection_silence_duration_ms": agent.turn_detection_silence_duration_ms,
            "transcription_model": agent.transcription_model or "gpt-4o-mini-transcribe",
            # Suppress initial greeting — caller speaks first in test mode
            "initial_greeting": None,
        }

        self._agent_session = GPTRealtimeSession(
            db=self.db,
            user_id=self.user_id,
            agent_config=agent_config,
            workspace_id=self.workspace_id,
        )
        await self._agent_session.initialize()
        self._log.info("agent_session_initialized")

    async def _connect_caller_session(self) -> None:
        model = "gpt-4o-realtime-preview"
        if self._agent_session and self._agent_session.agent_config:
            model = self._agent_session.agent_config.get("llm_model", model)

        client = AsyncOpenAI(api_key=self.openai_api_key)
        self._caller_conn = await client.realtime.connect(model=model).__aenter__()

        await self._caller_conn.session.update(
            session={
                "voice": "alloy",
                "instructions": build_caller_system_prompt(self.scenario),
                "turn_detection": {
                    "type": "server_vad",
                    "threshold": 0.5,
                    "prefix_padding_ms": 300,
                    "silence_duration_ms": 500,
                },
                "tools": [_END_CALL_TOOL],
                "tool_choice": "auto",
                "input_audio_transcription": {"model": "gpt-4o-mini-transcribe"},
            }
        )
        self._log.info("caller_session_connected")

    # ── audio forwarding ─────────────────────────────────────────────────────

    async def _forward_caller_audio_to_agent(self) -> None:
        import base64

        while not self._stop_event.is_set():
            try:
                audio_b64 = await asyncio.wait_for(self._caller_audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if self._agent_session:
                await self._agent_session.send_audio(base64.b64decode(audio_b64))

    async def _forward_agent_audio_to_caller(self) -> None:
        while not self._stop_event.is_set():
            try:
                audio_b64 = await asyncio.wait_for(self._agent_audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            if self._caller_conn:
                await self._caller_conn.input_audio_buffer.append(audio=audio_b64)

    # ── event loops ──────────────────────────────────────────────────────────

    async def _caller_event_loop(self) -> None:
        pass  # implemented in Task 6

    async def _agent_event_loop(self) -> None:
        pass  # implemented in Task 7
