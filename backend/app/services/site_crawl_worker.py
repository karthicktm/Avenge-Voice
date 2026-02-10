"""Scheduled site crawl worker — re-crawls agent websites on a configurable schedule.

Follows the CampaignWorker pattern: a background asyncio task that polls on a
fixed interval, checks which agents need re-crawling based on their configured
schedule, and runs the crawl sequentially (one agent at a time).

Schedule configuration lives in the agent's ``tool_configs.site_search`` JSON:

    {
        "site_search": {
            "site_url": "https://example.com",
            "crawl_schedule_hours": 24,        # 0 = manual only
            "last_crawl_at": "2026-02-10T15:00:00+00:00"
        }
    }
"""

import asyncio
import contextlib
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.models.agent import Agent
from app.models.workspace import AgentWorkspace

logger = structlog.get_logger()

POLL_INTERVAL_SECONDS = 60  # Check every minute


class SiteCrawlWorker:
    """Background worker that re-crawls agent websites on schedule."""

    def __init__(self) -> None:
        self.running = False
        self.logger = logger.bind(component="site_crawl_worker")
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the background worker task."""
        if self.running:
            self.logger.warning("Site crawl worker already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._run_loop())
        self.logger.info("Site crawl worker started")

    async def stop(self) -> None:
        """Stop the background worker."""
        self.running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self.logger.info("Site crawl worker stopped")

    async def _run_loop(self) -> None:
        """Main polling loop."""
        while self.running:
            try:
                await self._check_and_crawl()
            except Exception:
                self.logger.exception("Error in site crawl worker loop")

            await asyncio.sleep(POLL_INTERVAL_SECONDS)

    async def _check_and_crawl(self) -> None:
        """Check all agents for due crawls and run them sequentially."""
        async with AsyncSessionLocal() as db:
            agents = await self._get_due_agents(db)
            if not agents:
                return

            self.logger.info("Found agents due for site crawl", count=len(agents))

            for agent in agents:
                try:
                    await self._crawl_agent(agent, db)
                except Exception:
                    self.logger.exception(
                        "Site crawl failed for agent",
                        agent_id=str(agent.id),
                        agent_name=agent.name,
                    )

    async def _get_due_agents(self, db: AsyncSession) -> list[Agent]:
        """Find agents whose scheduled crawl is due."""
        result = await db.execute(select(Agent).where(Agent.is_active.is_(True)))
        all_agents = result.scalars().all()

        now = datetime.now(UTC)
        due: list[Agent] = []

        for agent in all_agents:
            site_config = (agent.tool_configs or {}).get("site_search", {})
            site_url = site_config.get("site_url")
            try:
                schedule_hours = int(site_config.get("crawl_schedule_hours", 0))
            except (ValueError, TypeError):
                schedule_hours = 0

            if not site_url or schedule_hours <= 0:
                continue

            last_crawl_str = site_config.get("last_crawl_at")
            if not last_crawl_str:
                # Never crawled — due immediately
                due.append(agent)
                continue

            try:
                last_crawl = datetime.fromisoformat(last_crawl_str)
            except (ValueError, TypeError):
                # Invalid timestamp — treat as never crawled
                due.append(agent)
                continue

            next_crawl = last_crawl + timedelta(hours=schedule_hours)
            if now >= next_crawl:
                due.append(agent)

        return due

    async def _crawl_agent(self, agent: Agent, db: AsyncSession) -> None:
        """Run a crawl for a single agent and update last_crawl_at."""
        site_config = (agent.tool_configs or {}).get("site_search", {})
        site_url = site_config.get("site_url", "")

        self.logger.info(
            "Starting scheduled crawl",
            agent_id=str(agent.id),
            agent_name=agent.name,
            site_url=site_url,
        )

        # Get embedding config from workspace integrations
        embedding_config = await self._get_embedding_config(agent, db)
        if not embedding_config.get("api_key"):
            self.logger.warning(
                "No embedding API key configured, skipping crawl",
                agent_id=str(agent.id),
            )
            return

        from app.services.site_indexer import SiteIndexer

        indexer = SiteIndexer(db, agent.id, embedding_config=embedding_config)
        result = await indexer.crawl_and_index(site_url, max_pages=50)
        await indexer.update_last_crawl_at()

        self.logger.info(
            "Scheduled crawl complete",
            agent_id=str(agent.id),
            **result,
        )

    async def _get_embedding_config(self, agent: Agent, db: AsyncSession) -> dict[str, Any]:
        """Get embedding config for an agent via its workspace integrations."""
        from app.api.integrations import get_workspace_integrations

        ws_result = await db.execute(
            select(AgentWorkspace).where(AgentWorkspace.agent_id == agent.id).limit(1)
        )
        agent_workspace = ws_result.scalar_one_or_none()
        if not agent_workspace:
            return {}

        from app.core.auth import user_id_to_uuid

        user_uuid = user_id_to_uuid(agent.user_id)
        workspace_integrations = await get_workspace_integrations(
            user_uuid, agent_workspace.workspace_id, db
        )
        kb_credentials = workspace_integrations.get("knowledge_base", {})

        agent_kb_settings = (
            agent.tool_configs.get("knowledge_base", {}) if agent.tool_configs else {}
        )

        return {
            "api_key": kb_credentials.get("api_key"),
            "embedding_model": kb_credentials.get("embedding_model", "text-embedding-3-small"),
            "embedding_provider": kb_credentials.get("embedding_provider", "openai"),
            "enable_translation": agent_kb_settings.get("enable_translation", "false"),
            "translation_model": agent_kb_settings.get("translation_model", "gpt-4o-mini"),
        }


# ---------------------------------------------------------------------------
# Global worker instance
# ---------------------------------------------------------------------------

_site_crawl_worker: SiteCrawlWorker | None = None


async def start_site_crawl_worker() -> SiteCrawlWorker:
    """Start the global site crawl worker."""
    global _site_crawl_worker
    if _site_crawl_worker is None:
        _site_crawl_worker = SiteCrawlWorker()
        await _site_crawl_worker.start()
    return _site_crawl_worker


async def stop_site_crawl_worker() -> None:
    """Stop the global site crawl worker."""
    global _site_crawl_worker
    if _site_crawl_worker:
        await _site_crawl_worker.stop()
        _site_crawl_worker = None
