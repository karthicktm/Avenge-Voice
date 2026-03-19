"""Abstract interface for agent deployment backends."""

from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_deployment import AgentDeployment


class AgentDeploymentBackend(Protocol):
    """Protocol for agent deployment backends (Docker, Railway, etc.)."""

    async def deploy(self, agent_id: str, db: AsyncSession) -> AgentDeployment:
        """Deploy a new container/service for the given agent.

        Creates or replaces the deployment, registers the URL in Redis,
        waits for the health endpoint to become available, and updates
        the AgentDeployment row to status='running'.

        Args:
            agent_id: Agent UUID string.
            db: Async database session.

        Returns:
            Updated AgentDeployment record with status='running'.
        """
        ...

    async def teardown(self, agent_id: str, db: AsyncSession) -> None:
        """Stop and remove the container/service for the given agent.

        Removes the Redis routing key, stops the container/service,
        and updates the AgentDeployment row to status='stopped'.

        Args:
            agent_id: Agent UUID string.
            db: Async database session.
        """
        ...

    async def get_agent_url(self, agent_id: str) -> str | None:
        """Look up the internal URL for an agent's running container/service.

        Reads from Redis key ``agent:container:{agent_id}``.

        Args:
            agent_id: Agent UUID string.

        Returns:
            Internal URL (e.g. ``http://agent-abc123:8001``) or None if not deployed.
        """
        ...
