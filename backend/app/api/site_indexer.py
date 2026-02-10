"""Site indexer API — trigger website crawling for knowledge base."""

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.core.auth import get_current_user, user_id_to_uuid
from app.db.session import get_db
from app.models.agent import Agent
from app.models.user import User
from app.models.workspace import AgentWorkspace

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/agents", tags=["site-indexer"])


class CrawlRequest(BaseModel):
    """Request body for triggering a site crawl."""

    site_url: str
    max_pages: int = 50


class CrawlResponse(BaseModel):
    """Response after triggering a crawl."""

    status: str
    message: str


async def _run_crawl_background(
    agent_id: uuid.UUID,
    site_url: str,
    max_pages: int,
    embedding_config: dict[str, Any],
) -> None:
    """Background task to crawl and index a site."""
    from app.db.session import AsyncSessionLocal
    from app.services.site_indexer import SiteIndexer

    async with AsyncSessionLocal() as db:
        try:
            indexer = SiteIndexer(db, agent_id, embedding_config=embedding_config)
            result = await indexer.crawl_and_index(site_url, max_pages=max_pages)
            await indexer.update_last_crawl_at()
            logger.info("site_crawl_background_complete", agent_id=str(agent_id), **result)
        except Exception:
            logger.exception("site_crawl_background_failed", agent_id=str(agent_id))


@router.post(
    "/{agent_id}/crawl",
    response_model=CrawlResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_site_crawl(
    agent_id: uuid.UUID,
    request: CrawlRequest,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CrawlResponse:
    """Trigger a background crawl of a website for knowledge base indexing.

    Crawls the specified site, extracts content, and processes it through
    the RAG pipeline (chunking, translation, embedding).
    """
    # Verify agent ownership
    result = await db.execute(
        select(Agent).where(Agent.id == agent_id, Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )

    # Validate max_pages
    max_pages = min(request.max_pages, 100)

    # Get embedding credentials from workspace integrations
    kb_credentials: dict[str, Any] = {}
    ws_result = await db.execute(
        select(AgentWorkspace).where(AgentWorkspace.agent_id == agent_id).limit(1)
    )
    agent_workspace = ws_result.scalar_one_or_none()

    if agent_workspace:
        user_uuid = user_id_to_uuid(current_user.id)
        workspace_integrations = await get_workspace_integrations(
            user_uuid, agent_workspace.workspace_id, db
        )
        kb_credentials = workspace_integrations.get("knowledge_base", {})

    if not kb_credentials.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge Base not configured. Please connect the Knowledge Base integration in the workspace Integrations page.",
        )

    # Get agent-specific translation settings
    agent_kb_settings = agent.tool_configs.get("knowledge_base", {}) if agent.tool_configs else {}

    embedding_config: dict[str, Any] = {
        "api_key": kb_credentials.get("api_key"),
        "embedding_model": kb_credentials.get("embedding_model", "text-embedding-3-small"),
        "embedding_provider": kb_credentials.get("embedding_provider", "openai"),
        "enable_translation": agent_kb_settings.get("enable_translation", "false"),
        "translation_model": agent_kb_settings.get("translation_model", "gpt-4o-mini"),
    }

    # Launch background crawl
    background_tasks.add_task(
        _run_crawl_background,
        agent_id,
        request.site_url,
        max_pages,
        embedding_config,
    )

    return CrawlResponse(
        status="crawling",
        message=f"Crawl started for {request.site_url} (up to {max_pages} pages). "
        "Documents will appear in the Knowledge Base as they are processed.",
    )
