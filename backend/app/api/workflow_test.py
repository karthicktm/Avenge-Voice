"""Workflow Test API — ephemeral step-through sessions for workflow debugging."""

from __future__ import annotations

import json
import time
import uuid
from typing import TYPE_CHECKING, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.settings import get_user_api_keys
from app.core.auth import VerifiedUser, user_id_to_uuid
from app.core.config import settings
from app.db.redis import get_redis
from app.db.session import get_db
from app.models.agent import Agent
from app.models.workflow import Workflow
from app.models.workspace import Workspace
from app.services.workflow_engine.executor import WorkflowExecutor
from app.services.workflow_engine.llm_client import LLMConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/workflows", tags=["workflow-test"])

_SIMULATED_TYPES = frozenset(
    {
        "transfer",
        "sms",
        "collect_email",
        "appointment",
        "voicemail",
        "webhook",
        "lookup_then_transfer",
    }
)

TTL = 1800  # 30 min


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class TestSessionOut(BaseModel):
    session_id: str
    current_node_id: str
    current_node_type: str
    current_node_label: str
    context_bag: dict[str, Any]
    is_complete: bool


class VoiceConfigOut(BaseModel):
    provider: str  # "openai" | "elevenlabs" | "browser"
    tts_model: str
    voice: str
    available: bool


# ── helpers ───────────────────────────────────────────────────────────────────


def _redis_key(session_id: str) -> str:
    return f"wf_test_session:{session_id}"


def _make_llm_config(api_key: str) -> LLMConfig:
    return LLMConfig(provider="openai", model="gpt-4o-mini", api_key=api_key)


def _session_out(executor: WorkflowExecutor, session_id: str) -> TestSessionOut:
    node = executor.current_node or {}
    return TestSessionOut(
        session_id=session_id,
        current_node_id=executor.current_node_id,
        current_node_type=node.get("type", ""),
        current_node_label=node.get("label", ""),
        context_bag=executor.context_bag,
        is_complete=node.get("type") == "end_call",
    )


async def _load_executor(session_id: str, api_key: str) -> tuple[WorkflowExecutor, dict[str, Any]]:
    """Load executor from Redis. Raises 404 if session not found.

    NOTE (Task 2): Endpoints that receive a workflow_id URL parameter should
    additionally validate that state.get("workflow_id") == str(workflow_id)
    to prevent a session from being driven against a mismatched workflow.
    """
    redis = await get_redis()
    raw = await redis.get(_redis_key(session_id))
    if not raw:
        raise HTTPException(status_code=404, detail="Test session not found or expired")
    state = json.loads(raw)
    executor = WorkflowExecutor.from_state(state, _make_llm_config(api_key))
    return executor, state


async def _save_executor(
    session_id: str, executor: WorkflowExecutor, extra: dict[str, Any]
) -> None:
    """Persist executor state back to Redis."""
    try:
        redis = await get_redis()
        state = {**executor.to_state(), **extra}
        await redis.set(_redis_key(session_id), json.dumps(state), ex=TTL)
    except Exception:
        logger.exception("wf_test_save_failed", session_id=session_id)
        raise HTTPException(status_code=503, detail="Failed to persist session state") from None


async def _get_openai_key(user: VerifiedUser, workflow: Workflow, db: AsyncSession) -> str:
    user_uuid = user_id_to_uuid(user.id)
    user_settings = await get_user_api_keys(user_uuid, db, workspace_id=workflow.workspace_id)
    key = (user_settings.openai_api_key if user_settings else None) or settings.OPENAI_API_KEY or ""
    return key


async def _resolve_voice_config(
    wf: Workflow,
    user: VerifiedUser,
    db: AsyncSession,
) -> VoiceConfigOut:
    """Resolve TTS voice config from the agent attached to this workflow."""
    agent_result = await db.execute(select(Agent).where(Agent.workflow_id == wf.id))
    agent = agent_result.scalar_one_or_none()

    user_uuid = user_id_to_uuid(user.id)
    user_settings = await get_user_api_keys(user_uuid, db, workspace_id=wf.workspace_id)

    def _openai_key() -> str | None:
        return (user_settings.openai_api_key if user_settings else None) or settings.OPENAI_API_KEY

    def _elevenlabs_key() -> str | None:
        return (
            user_settings.elevenlabs_api_key if user_settings else None
        ) or settings.ELEVENLABS_API_KEY

    def _openai_shimmer_or_browser() -> VoiceConfigOut:
        oai = _openai_key()
        if oai:
            return VoiceConfigOut(
                provider="openai", tts_model="tts-1", voice="shimmer", available=True
            )
        return VoiceConfigOut(provider="browser", tts_model="", voice="", available=False)

    if agent is None:
        return _openai_shimmer_or_browser()

    voice = agent.voice or "shimmer"

    if agent.pricing_tier == "budget":
        el = _elevenlabs_key()
        if el:
            return VoiceConfigOut(
                provider="elevenlabs", tts_model="eleven_flash_v2_5", voice=voice, available=True
            )
        return _openai_shimmer_or_browser()

    # premium, premium-mini, balanced → approximate with OpenAI tts-1 for test simulation
    # (production balanced uses Google TTS; premium-mini uses Realtime — both unavailable here)
    oai = _openai_key()
    if oai:
        return VoiceConfigOut(provider="openai", tts_model="tts-1", voice=voice, available=True)
    return VoiceConfigOut(provider="browser", tts_model="", voice="", available=False)


# ── start ─────────────────────────────────────────────────────────────────────


@router.post("/{workflow_id}/test/start", response_model=TestSessionOut)
async def start_test_session(
    workflow_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> TestSessionOut:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Verify the calling user owns the workspace this workflow belongs to.
    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == wf.workspace_id,
            Workspace.user_id == user.id,
        )
    )
    if ws_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Access denied")

    openai_key = await _get_openai_key(user, wf, db)
    llm_config = _make_llm_config(openai_key)

    session_id = str(uuid.uuid4())
    executor = WorkflowExecutor(
        workflow_id=wf.id,
        nodes=wf.nodes,
        edges=wf.edges,
        llm_config=llm_config,
    )

    state = {**executor.to_state(), "is_test": True, "workspace_id": str(wf.workspace_id)}
    redis = await get_redis()
    await redis.set(_redis_key(session_id), json.dumps(state), ex=TTL)

    logger.info("wf_test_session_started", session_id=session_id, workflow_id=str(workflow_id))
    return _session_out(executor, session_id)


# ── step ──────────────────────────────────────────────────────────────────────


class StepRequest(BaseModel):
    caller_input: str = ""


class StepOut(BaseModel):
    session_id: str
    current_node_id: str
    current_node_type: str
    current_node_label: str
    context_bag: dict[str, Any]
    node_output: str
    simulated: bool
    simulation_detail: dict[str, Any] | None
    elapsed_ms: float
    resolution_layer: str | None
    is_complete: bool


async def _load_prewarmed(workspace_id: str, tree_name: str) -> list[dict[str, Any]]:
    """Load prewarmed category tree nodes from Redis cache."""
    redis = await get_redis()
    raw = await redis.get(f"category_nodes:{workspace_id}")
    if not raw:
        return []
    data: dict[str, Any] = json.loads(raw)
    trees: dict[str, list[dict[str, Any]]] = data.get("trees", {})
    return trees.get(tree_name, [])


class _NodeResult:
    """Intermediate result from processing a single workflow node."""

    __slots__ = ("node_output", "resolution_layer", "simulated", "simulation_detail")

    def __init__(self) -> None:
        self.node_output: str = ""
        self.resolution_layer: str | None = None
        self.simulated: bool = False
        self.simulation_detail: dict[str, Any] | None = None


async def _process_node(
    executor: WorkflowExecutor,
    node: dict[str, Any],
    caller_input: str,
    workspace_id: str,
) -> _NodeResult:
    """Dispatch node processing and return structured output."""
    result = _NodeResult()
    node_type: str = node.get("type", "")
    node_label: str = node.get("label", "")

    if node_type == "entry":
        next_id = executor.route()
        if next_id:
            executor.current_node_id = next_id
        result.node_output = executor.build_node_instruction() or "Hello! How can I help you today?"

    elif node_type == "categorize":
        cfg = node.get("config") or {}
        tree_name = cfg.get("tree_name", "")
        preloaded = await _load_prewarmed(workspace_id, tree_name)
        await executor.run_categorize(caller_input, preloaded)
        result.resolution_layer = executor.context_bag.get("resolution_layer")
        result.node_output = executor.build_node_instruction()

    elif node_type == "instruction":
        result.node_output = executor.build_node_instruction() or node_label
        next_id = executor.route()
        if next_id:
            executor.current_node_id = next_id

    elif node_type == "condition":
        next_id = executor.route_condition()
        if not next_id:
            logger.warning("wf_test_condition_no_route", node_id=executor.current_node_id)
        result.node_output = f"Condition evaluated: routed to {executor.current_node_id}"

    elif node_type in _SIMULATED_TYPES:
        cfg = node.get("config") or {}
        template = cfg.get("template", "")
        resolved = executor.resolve_template(template) if template else ""
        result.simulated = True
        result.simulation_detail = {
            "node_type": node_type,
            "node_label": node_label,
            "would_have": {
                "target": executor.context_bag.get("transfer_target"),
                "script": resolved or executor.context_bag.get("approved_script"),
                "email_target": executor.context_bag.get("email_target"),
                "sms_body": resolved,
            },
        }
        result.node_output = f"[Simulated] {node_label}: {resolved or node_type}"
        next_id = executor.route()
        if next_id:
            executor.current_node_id = next_id

    elif node_type == "end_call":
        result.node_output = executor.build_node_instruction() or "Thank you for calling. Goodbye!"

    return result


@router.post("/{workflow_id}/test/{session_id}/step", response_model=StepOut)
async def step_test_session(
    workflow_id: uuid.UUID,
    session_id: str,
    body: StepRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> StepOut:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Verify the calling user owns the workspace this workflow belongs to.
    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == wf.workspace_id,
            Workspace.user_id == user.id,
        )
    )
    if ws_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Access denied")

    openai_key = await _get_openai_key(user, wf, db)
    executor, state = await _load_executor(session_id, openai_key)

    if state.get("workflow_id") != str(workflow_id):
        raise HTTPException(status_code=403, detail="Session workflow mismatch")

    workspace_id = state.get("workspace_id", str(wf.workspace_id))
    t0 = time.monotonic()

    node = executor.current_node or {}
    result = await _process_node(executor, node, body.caller_input, workspace_id)

    await _save_executor(session_id, executor, {"is_test": True, "workspace_id": workspace_id})
    elapsed = (time.monotonic() - t0) * 1000

    next_node = executor.current_node or {}
    return StepOut(
        session_id=session_id,
        current_node_id=executor.current_node_id,
        current_node_type=next_node.get("type", ""),
        current_node_label=next_node.get("label", ""),
        context_bag=executor.context_bag,
        node_output=result.node_output,
        simulated=result.simulated,
        simulation_detail=result.simulation_detail,
        elapsed_ms=round(elapsed, 1),
        resolution_layer=result.resolution_layer,
        is_complete=next_node.get("type") == "end_call",
    )


# ── context patch ─────────────────────────────────────────────────────────────


class ContextPatchRequest(BaseModel):
    context_bag: dict[str, Any]


@router.patch("/{workflow_id}/test/{session_id}/context", response_model=TestSessionOut)
async def patch_context(
    workflow_id: uuid.UUID,
    session_id: str,
    body: ContextPatchRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> TestSessionOut:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    openai_key = await _get_openai_key(user, wf, db)
    executor, state = await _load_executor(session_id, openai_key)
    executor.context_bag.update(body.context_bag)
    workspace_id = state.get("workspace_id", str(wf.workspace_id))
    await _save_executor(session_id, executor, {"is_test": True, "workspace_id": workspace_id})
    return _session_out(executor, session_id)


# ── delete session ────────────────────────────────────────────────────────────


@router.delete("/{workflow_id}/test/{session_id}", status_code=204)
async def delete_test_session(
    workflow_id: uuid.UUID,
    session_id: str,
    user: VerifiedUser,
) -> None:
    redis = await get_redis()
    await redis.delete(_redis_key(session_id))


# ── voice config ──────────────────────────────────────────────────────────────


@router.get("/{workflow_id}/test/voice-config", response_model=VoiceConfigOut)
async def get_voice_config(
    workflow_id: uuid.UUID,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> VoiceConfigOut:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    ws_result = await db.execute(
        select(Workspace).where(
            Workspace.id == wf.workspace_id,
            Workspace.user_id == user.id,
        )
    )
    if ws_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=403, detail="Access denied")
    return await _resolve_voice_config(wf, user, db)


# ── AI step ───────────────────────────────────────────────────────────────────

_AI_CALLER_SYSTEM = (
    "You are simulating a caller on a voice support line. "
    "Persona: {persona}. "
    "Current workflow node: {node_type} — {node_label}. "
    "Conversation so far: {transcript}. "
    "Respond ONLY as the caller would speak — natural, conversational, one or two sentences. "
    "Do not explain yourself. Do not break character."
)

_COPILOT_SUGGESTION_COUNT = 3

_AI_CALLER_COPILOT_SYSTEM = (
    "You are simulating a caller on a voice support line. "
    "Persona: {persona}. "
    "Current workflow node: {node_type} — {node_label}. "
    "Generate exactly 3 short, distinct things the caller might say next. "
    "One per line. No labels, numbers, or punctuation at the start. "
    "Do not explain yourself. Vary the phrasing meaningfully."
)


class AiStepRequest(BaseModel):
    persona: str
    mode: str  # "autopilot" | "copilot"
    transcript: str = ""


class AiStepOut(BaseModel):
    session_id: str
    mode: str
    ai_input: str | None = None
    suggestions: list[str] | None = None
    step_result: StepOut | None = None


async def _call_openai_chat(system: str, user_msg: str, api_key: str, max_tokens: int = 100) -> str:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key)
    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=max_tokens,
        temperature=0.7,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
    )
    return (response.choices[0].message.content or "").strip()


@router.post("/{workflow_id}/test/{session_id}/ai-step", response_model=AiStepOut)
async def ai_step_test_session(
    workflow_id: uuid.UUID,
    session_id: str,
    body: AiStepRequest,
    user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> AiStepOut:
    wf = await db.get(Workflow, workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    openai_key = await _get_openai_key(user, wf, db)
    executor, _ = await _load_executor(session_id, openai_key)
    node = executor.current_node or {}
    node_type = node.get("type", "")
    node_label = node.get("label", "")

    if body.mode == "copilot":
        system = _AI_CALLER_COPILOT_SYSTEM.format(
            persona=body.persona, node_type=node_type, node_label=node_label
        )
        raw = await _call_openai_chat(
            system, body.transcript or "Start of call", openai_key, max_tokens=150
        )
        suggestions = [line.strip() for line in raw.splitlines() if line.strip()][
            :_COPILOT_SUGGESTION_COUNT
        ]
        while len(suggestions) < _COPILOT_SUGGESTION_COUNT:
            suggestions.append(suggestions[0] if suggestions else "Hello")
        return AiStepOut(session_id=session_id, mode="copilot", suggestions=suggestions)

    system = _AI_CALLER_SYSTEM.format(
        persona=body.persona,
        node_type=node_type,
        node_label=node_label,
        transcript=body.transcript or "Start of call",
    )
    ai_input = await _call_openai_chat(system, "What would you say now?", openai_key)

    step_result = await step_test_session(
        workflow_id=workflow_id,
        session_id=session_id,
        body=StepRequest(caller_input=ai_input),
        user=user,
        db=db,
    )
    return AiStepOut(
        session_id=session_id, mode="autopilot", ai_input=ai_input, step_result=step_result
    )
