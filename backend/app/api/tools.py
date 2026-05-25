"""API endpoints for tool execution."""

import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.api.settings import get_user_api_keys
from app.core.auth import VerifiedUser, user_id_to_uuid
from app.db.session import get_db
from app.models.agent import Agent
from app.models.workspace import AgentWorkspace
from app.services.tools.registry import ToolRegistry

router = APIRouter(prefix="/api/v1/tools", tags=["tools"])
logger = structlog.get_logger()


class ToolExecuteRequest(BaseModel):
    """Request body for tool execution."""

    tool_name: str
    arguments: dict[str, Any]
    agent_id: str
    wf_session_id: str | None = None


@router.post("/execute")
async def execute_tool(
    request: ToolExecuteRequest,
    current_user: VerifiedUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Execute a tool and return the result.

    This endpoint is called by the frontend when the GPT Realtime model
    makes a function call. The tool is executed on the backend and the
    result is returned to be sent back to the model.

    Args:
        request: Tool execution request
        current_user: Authenticated user
        db: Database session

    Returns:
        Tool execution result
    """
    user_id = current_user.id
    tool_logger = logger.bind(
        endpoint="execute_tool",
        tool_name=request.tool_name,
        agent_id=request.agent_id,
        user_id=user_id,
    )

    tool_logger.info("tool_execution_requested", arguments=request.arguments)

    try:
        # Get workspace and agent for proper scoping
        workspace_id: uuid.UUID | None = None
        agent_uuid: uuid.UUID | None = None
        agent: Agent | None = None

        if request.agent_id:
            try:
                agent_uuid = uuid.UUID(request.agent_id)

                # Get agent to access tool_configs
                agent_result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
                agent = agent_result.scalar_one_or_none()

                # Get workspace for the agent
                workspace_result = await db.execute(
                    select(AgentWorkspace).where(AgentWorkspace.agent_id == agent_uuid).limit(1)
                )
                agent_workspace = workspace_result.scalar_one_or_none()
                if agent_workspace:
                    workspace_id = agent_workspace.workspace_id
            except ValueError:
                tool_logger.warning("invalid_agent_id_format", agent_id=request.agent_id)

        # Get integration credentials for the workspace
        user_uuid = user_id_to_uuid(user_id)
        integrations: dict[str, dict[str, Any]] = {}
        if workspace_id:
            integrations = await get_workspace_integrations(user_uuid, workspace_id, db)

        # Get OpenAI API key for RAG embeddings fallback
        openai_api_key: str | None = None
        user_settings = await get_user_api_keys(user_uuid, db, workspace_id=workspace_id)
        if user_settings and user_settings.openai_api_key:
            openai_api_key = user_settings.openai_api_key

        # Get tool_configs from agent if available
        tool_configs = agent.tool_configs if agent else {}

        # Create tool registry (needed for prewarmed tree even in workflow path)
        tool_registry = ToolRegistry(
            db,
            user_id,
            integrations=integrations,
            workspace_id=workspace_id,
            agent_id=agent_uuid,
            openai_api_key=openai_api_key,
            tool_configs=tool_configs or {},
        )

        # Workflow intercept — if this is a categorize call inside a workflow session,
        # run it through the WorkflowExecutor instead of the bare tool registry.
        if request.tool_name == "categorize" and request.wf_session_id:
            wf_result = await _run_workflow_categorize(
                wf_session_id=request.wf_session_id,
                arguments=request.arguments,
                tool_registry=tool_registry,
                openai_api_key=openai_api_key or "",
                log=tool_logger,
            )
            if wf_result is not None:
                tool_logger.warning(
                    "wf_categorize_intercepted_webrtc",
                    label=wf_result.get("label"),
                    action_type=wf_result.get("action_type"),
                )
                return wf_result

        result = await tool_registry.execute_tool(request.tool_name, request.arguments)

        tool_logger.info("tool_execution_completed", success=result.get("success", False))

        return result

    except Exception as e:
        tool_logger.exception("tool_execution_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {e!s}") from e


async def _run_workflow_categorize(
    wf_session_id: str,
    arguments: dict[str, Any],
    tool_registry: ToolRegistry,
    openai_api_key: str,
    log: Any,
) -> dict[str, Any] | None:
    """Run a categorize tool call through the WorkflowExecutor for a WebRTC session.

    Loads executor state from Redis, runs categorize, persists updated state,
    and returns the tool result plus the next node's resolved instruction.
    Returns None if the session is not found or an error occurs (caller falls back).
    """
    import json as _json

    try:
        from app.db.redis import get_redis
        from app.services.workflow_engine.executor import WorkflowExecutor
        from app.services.workflow_engine.llm_client import LLMConfig

        redis = await get_redis()
        raw = await redis.get(f"wf_session:{wf_session_id}")
        if not raw:
            log.warning("wf_session_not_found", wf_session_id=wf_session_id)
            return None

        state = _json.loads(raw)
        llm_config = LLMConfig(provider="openai", model="gpt-4o-mini", api_key=openai_api_key)
        executor = WorkflowExecutor.from_state(state, llm_config)

        # Auto-advance from entry to categorize node (same as telephony path)
        cur_type = (executor.current_node or {}).get("type", "")
        if cur_type == "entry":
            next_id = executor.route()
            if next_id and (executor.nodes_by_id.get(next_id) or {}).get("type") == "categorize":
                executor.current_node_id = next_id
                cur_type = "categorize"

        if cur_type != "categorize":
            log.warning("wf_session_not_at_categorize", cur_type=cur_type)
            return None

        text = str(arguments.get("text", ""))
        node_cfg: dict[str, Any] = (executor.current_node or {}).get("config") or {}
        tree_name = str(arguments.get("tree_name", "") or node_cfg.get("tree_name", ""))
        prewarmed = tool_registry.get_prewarmed_tree(tree_name) if tree_name else []

        await executor.run_categorize(text, prewarmed)

        # Persist updated state back to Redis
        await redis.set(
            f"wf_session:{wf_session_id}",
            _json.dumps(executor.to_state()),
            ex=3600,
        )

        result: dict[str, Any] = {
            "success": True,
            "code": executor.context_bag.get("code"),
            "label": executor.context_bag.get("label"),
            "confidence": executor.context_bag.get("confidence"),
            "resolution_layer": executor.context_bag.get("resolution_layer"),
            "action_type": executor.context_bag.get("action_type"),
        }

        # Include next node instruction so the frontend can inject it into the session
        workflow_instruction = executor.build_node_instruction()
        if workflow_instruction:
            result["workflow_instruction"] = workflow_instruction

        return result

    except Exception:
        log.exception("wf_categorize_webrtc_failed")
        return None
