"""Railway deployment backend for per-agent service management."""

import asyncio
import uuid as _uuid
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.redis import get_redis
from app.models.agent_deployment import AgentDeployment

logger = structlog.get_logger()

_RAILWAY_GRAPHQL_URL = "https://backboard.railway.com/graphql/v2"
_REDIS_KEY_PREFIX = "agent:container:"
_HEALTH_POLL_INTERVAL = 5.0  # seconds
_HEALTH_POLL_TIMEOUT = 300.0  # seconds (Railway takes 60-120s to provision)

_CREATE_SERVICE_MUTATION = """
mutation CreateService($input: ServiceCreateInput!) {
  serviceCreate(input: $input) {
    id
    name
  }
}
"""

_SET_VARIABLES_MUTATION = """
mutation SetVars($input: VariableCollectionUpsertInput!) {
  variableCollectionUpsert(input: $input) {
    id
  }
}
"""

_DELETE_SERVICE_MUTATION = """
mutation DeleteService($serviceId: String!) {
  serviceDelete(id: $serviceId)
}
"""


class RailwayBackend:
    """Manages per-agent Railway services via the Railway GraphQL API."""

    def _service_name(self, agent_id: str) -> str:
        return f"agent-{agent_id.replace('-', '')[:12]}"

    def _internal_url(self, name: str) -> str:
        return f"http://{name}.railway.internal:8001"

    async def _graphql(
        self,
        client: httpx.AsyncClient,
        query: str,
        variables: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a Railway GraphQL mutation/query."""
        if not settings.RAILWAY_TOKEN:
            msg = "RAILWAY_TOKEN not configured"
            raise RuntimeError(msg)

        response = await client.post(
            _RAILWAY_GRAPHQL_URL,
            headers={
                "Authorization": f"Bearer {settings.RAILWAY_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables},
            timeout=30.0,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        if "errors" in data:
            msg = f"Railway GraphQL error: {data['errors']}"
            raise RuntimeError(msg)
        result: dict[str, Any] = data.get("data", {})
        return result

    async def _create_service(self, client: httpx.AsyncClient, service_name: str) -> str:
        """Create a Railway service and return its ID."""
        if not settings.RAILWAY_PROJECT_ID:
            msg = "RAILWAY_PROJECT_ID not configured"
            raise RuntimeError(msg)

        data = await self._graphql(
            client,
            _CREATE_SERVICE_MUTATION,
            {
                "input": {
                    "projectId": settings.RAILWAY_PROJECT_ID,
                    "name": service_name,
                    "source": {"image": settings.RAILWAY_AGENT_IMAGE},
                }
            },
        )
        service_id: str = data["serviceCreate"]["id"]
        return service_id

    async def _set_variables(
        self,
        client: httpx.AsyncClient,
        service_id: str,
        variables: dict[str, str],
    ) -> None:
        """Set environment variables for a Railway service."""
        if not settings.RAILWAY_PROJECT_ID or not settings.RAILWAY_ENVIRONMENT_ID:
            msg = "RAILWAY_PROJECT_ID and RAILWAY_ENVIRONMENT_ID must be configured"
            raise RuntimeError(msg)

        await self._graphql(
            client,
            _SET_VARIABLES_MUTATION,
            {
                "input": {
                    "projectId": settings.RAILWAY_PROJECT_ID,
                    "environmentId": settings.RAILWAY_ENVIRONMENT_ID,
                    "serviceId": service_id,
                    "variables": variables,
                    "replace": False,
                }
            },
        )

    async def _delete_service(self, client: httpx.AsyncClient, service_id: str) -> None:
        """Delete a Railway service."""
        await self._graphql(
            client,
            _DELETE_SERVICE_MUTATION,
            {"serviceId": service_id},
        )

    async def deploy(self, agent_id: str, db: AsyncSession) -> AgentDeployment:
        """Create a Railway service for the given agent."""
        log = logger.bind(agent_id=agent_id)
        log.info("railway_deploy_start")

        service_name = self._service_name(agent_id)
        internal_url = self._internal_url(service_name)

        # Upsert AgentDeployment row → pending
        result = await db.execute(
            select(AgentDeployment).where(AgentDeployment.agent_id == _uuid.UUID(agent_id))
        )
        deployment = result.scalar_one_or_none()
        if deployment is None:
            deployment = AgentDeployment(
                agent_id=_uuid.UUID(agent_id),
                status="pending",
                backend="railway",
                container_name=service_name,
                container_url=internal_url,
            )
            db.add(deployment)
        else:
            deployment.status = "pending"
            deployment.backend = "railway"
            deployment.container_name = service_name
            deployment.container_url = internal_url
            deployment.error_message = None
        await db.commit()
        await db.refresh(deployment)

        async with httpx.AsyncClient() as client:
            try:
                service_id = await self._create_service(client, service_name)
                deployment.container_id = service_id
                await db.commit()

                env_vars = {
                    "AGENT_ID": agent_id,
                    "DATABASE_URL": str(settings.DATABASE_URL),
                    "REDIS_URL": str(settings.REDIS_URL),
                    "OPENAI_API_KEY": settings.OPENAI_API_KEY or "",
                    "DEEPGRAM_API_KEY": settings.DEEPGRAM_API_KEY or "",
                    "ELEVENLABS_API_KEY": settings.ELEVENLABS_API_KEY or "",
                    "PORT": "8001",
                }
                await self._set_variables(client, service_id, env_vars)

            except Exception as exc:
                log.exception("railway_deploy_failed", error=str(exc))
                deployment.status = "failed"
                deployment.error_message = str(exc)
                await db.commit()
                raise

        # Register URL in Redis immediately (Railway services take time to provision)
        redis = await get_redis()
        await redis.set(_REDIS_KEY_PREFIX + agent_id, internal_url)

        # Poll health endpoint (background: Railway takes 60-120s)
        try:
            await _wait_for_health(internal_url, agent_id, _HEALTH_POLL_TIMEOUT)
        except TimeoutError as exc:
            deployment.status = "failed"
            deployment.error_message = str(exc)
            await db.commit()
            raise

        deployment.status = "running"
        await db.commit()
        await db.refresh(deployment)
        log.info("railway_deploy_complete", url=internal_url)
        return deployment

    async def teardown(self, agent_id: str, db: AsyncSession) -> None:
        """Delete the Railway service for the given agent."""
        log = logger.bind(agent_id=agent_id)
        log.info("railway_teardown_start")

        # Remove Redis routing key first
        redis = await get_redis()
        await redis.delete(_REDIS_KEY_PREFIX + agent_id)

        result = await db.execute(
            select(AgentDeployment).where(AgentDeployment.agent_id == _uuid.UUID(agent_id))
        )
        deployment = result.scalar_one_or_none()

        if deployment and deployment.container_id:
            async with httpx.AsyncClient() as client:
                try:
                    await self._delete_service(client, deployment.container_id)
                except Exception:
                    log.exception(
                        "railway_service_delete_failed",
                        service_id=deployment.container_id,
                    )

        if deployment:
            deployment.status = "stopped"
            await db.commit()

        log.info("railway_teardown_complete")

    async def get_agent_url(self, agent_id: str) -> str | None:
        """Return the internal Railway URL from Redis, or None."""
        redis = await get_redis()
        url: str | None = await redis.get(_REDIS_KEY_PREFIX + agent_id)
        return url


async def _wait_for_health(url: str, agent_id: str, timeout_secs: float) -> None:
    """Poll GET {url}/health until 200 or timeout_secs elapsed."""
    health_url = f"{url}/health"
    log = logger.bind(agent_id=agent_id, health_url=health_url)

    try:
        async with asyncio.timeout(timeout_secs):
            async with httpx.AsyncClient() as client:
                while True:
                    try:
                        resp = await client.get(health_url, timeout=5.0)
                        if resp.status_code == 200:  # noqa: PLR2004
                            log.info("railway_service_healthy")
                            return
                    except (httpx.RequestError, httpx.HTTPStatusError):
                        pass
                    await asyncio.sleep(_HEALTH_POLL_INTERVAL)
    except TimeoutError:
        msg = f"Railway service for agent {agent_id} did not become healthy within {timeout_secs}s"
        raise TimeoutError(msg) from None
