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

        # Create tool registry and execute tool
        tool_registry = ToolRegistry(
            db,
            user_id,
            integrations=integrations,
            workspace_id=workspace_id,
            agent_id=agent_uuid,
            openai_api_key=openai_api_key,
            tool_configs=tool_configs or {},
        )
        result = await tool_registry.execute_tool(request.tool_name, request.arguments)

        tool_logger.info("tool_execution_completed", success=result.get("success", False))

        return result

    except Exception as e:
        tool_logger.exception("tool_execution_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Tool execution failed: {e!s}") from e
