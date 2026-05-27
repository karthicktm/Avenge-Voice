"""Agent test call bridge — connects a caller AI session to a live voice agent session."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog
from openai import AsyncOpenAI

from app.services.gpt_realtime import GPTRealtimeSession

if TYPE_CHECKING:
    import uuid

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
        db: AsyncSession,
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
        start_time = asyncio.get_running_loop().time()

        async def _guard() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(5)
                if self._turn_count >= MAX_TURNS:
                    await self.events.put({"type": "session.complete", "reason": "max_turns"})
                    self._stop_event.set()
                    return
                if asyncio.get_running_loop().time() - start_time >= MAX_DURATION_SECONDS:
                    await self.events.put({"type": "session.complete", "reason": "max_duration"})
                    self._stop_event.set()
                    return

        results = await asyncio.gather(
            self._caller_event_loop(),
            self._agent_event_loop(),
            self._forward_caller_audio_to_agent(),
            self._forward_agent_audio_to_caller(),
            _guard(),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, BaseException) and not isinstance(r, asyncio.CancelledError):
                await self.events.put({"type": "session.error", "message": str(r)})
                break

    async def stop(self) -> None:
        self._stop_event.set()
        if self._caller_conn:
            with contextlib.suppress(Exception):
                await self._caller_conn.__aexit__(None, None, None)
        if self._agent_session:
            with contextlib.suppress(Exception):
                await self._agent_session.__aexit__(None, None, None)

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
            except TimeoutError:
                continue
            if self._agent_session:
                await self._agent_session.send_audio(base64.b64decode(audio_b64))

    async def _forward_agent_audio_to_caller(self) -> None:
        while not self._stop_event.is_set():
            try:
                audio_b64 = await asyncio.wait_for(self._agent_audio_queue.get(), timeout=0.5)
            except TimeoutError:
                continue
            if self._caller_conn:
                await self._caller_conn.input_audio_buffer.append(audio=audio_b64)

    # ── event loops ──────────────────────────────────────────────────────────

    async def _caller_event_loop(self) -> None:
        current_speech = ""
        async for event in self._caller_conn:
            if self._stop_event.is_set():
                break
            event_type = event.type

            if event_type == "response.audio.delta":
                audio_b64 = getattr(event, "delta", "")
                if audio_b64:
                    await self._caller_audio_queue.put(audio_b64)

            elif event_type == "response.audio_transcript.delta":
                current_speech += getattr(event, "delta", "")
                await self.events.put({"type": "caller.speech.delta", "text": current_speech})

            elif event_type == "response.audio_transcript.done":
                text = getattr(event, "transcript", current_speech)
                await self.events.put({"type": "caller.speech.done", "text": text})
                current_speech = ""
                self._turn_count += 1

            elif event_type == "response.function_call_arguments.done":
                if getattr(event, "name", "") == "end_call":
                    await self.events.put({"type": "session.complete", "reason": "end_call"})
                    self._stop_event.set()
                    break

    async def _agent_event_loop(self) -> None:
        import json
        import time

        if not self._agent_session or not self._agent_session.connection:
            return

        current_speech = ""
        async for event in self._agent_session.connection:
            if self._stop_event.is_set():
                break
            event_type = event.type

            if event_type == "response.audio.delta":
                audio_b64 = getattr(event, "delta", "")
                if audio_b64:
                    await self._agent_audio_queue.put(audio_b64)

            elif event_type == "response.audio_transcript.delta":
                current_speech += getattr(event, "delta", "")
                await self.events.put({"type": "agent.speech.delta", "text": current_speech})

            elif event_type == "response.audio_transcript.done":
                text = getattr(event, "transcript", current_speech)
                await self.events.put({"type": "agent.speech.done", "text": text})
                current_speech = ""

            elif event_type == "response.function_call_arguments.done":
                tool_name = getattr(event, "name", "")
                raw_args = getattr(event, "arguments", "{}")
                try:
                    tool_args: dict[str, Any] = (
                        json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    )
                except json.JSONDecodeError:
                    tool_args = {}

                await self.events.put(
                    {"type": "agent.tool_call", "tool": tool_name, "args": tool_args}
                )

                t0 = time.monotonic()
                result = await self._agent_session.handle_function_call_event(event)
                elapsed_ms = (time.monotonic() - t0) * 1000

                await self.events.put(
                    {
                        "type": "agent.tool_result",
                        "tool": tool_name,
                        "result": result,
                        "elapsed_ms": elapsed_ms,
                    }
                )

                # Emit current workflow node if executor is active
                executor = self._agent_session.workflow_executor
                if executor:
                    node = executor.current_node or {}
                    await self.events.put(
                        {
                            "type": "agent.workflow_node",
                            "node_id": executor.current_node_id,
                            "node_type": node.get("type", ""),
                            "node_label": node.get("label", ""),
                        }
                    )
