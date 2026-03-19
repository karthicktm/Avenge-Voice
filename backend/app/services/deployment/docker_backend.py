"""Docker deployment backend for per-agent container management."""

import asyncio
import contextlib
import uuid as _uuid
from pathlib import Path
from typing import Any

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.redis import get_redis
from app.models.agent_deployment import AgentDeployment

logger = structlog.get_logger()

# Cap concurrent Docker operations to avoid overwhelming the daemon
_deploy_semaphore = asyncio.Semaphore(5)

_REDIS_KEY_PREFIX = "agent:container:"
_HEALTH_POLL_INTERVAL = 2.0  # seconds
_HEALTH_POLL_TIMEOUT = 60.0  # seconds

# When running inside Docker, containers are reachable by hostname on the shared network.
# On macOS/Windows hosts, Docker containers live in a VM and are NOT reachable by hostname,
# so we bind a random host port and route through localhost instead.
_IN_DOCKER = Path("/.dockerenv").exists()


def _require_host_port(bindings: list[dict[str, str]]) -> int:
    if not bindings:
        msg = "Docker did not bind a host port for 8001/tcp"
        raise RuntimeError(msg)
    return int(bindings[0]["HostPort"])


class DockerBackend:
    """Manages per-agent Docker containers via the Docker SDK."""

    def _container_name(self, agent_id: str) -> str:
        return f"agent-{agent_id.replace('-', '')[:12]}"

    def _container_url(self, name: str, host_port: int | None = None) -> str:
        if _IN_DOCKER:
            return f"http://{name}:8001"
        # Running on host — use the mapped localhost port
        return f"http://localhost:{host_port}"

    async def deploy(self, agent_id: str, db: AsyncSession) -> AgentDeployment:  # noqa: PLR0915
        """Create and start a Docker container for the given agent."""
        import docker  # type: ignore[import-untyped]

        name = self._container_name(agent_id)
        # url is placeholder until we resolve the actual host port (if on macOS/Windows host)
        url = self._container_url(name, host_port=0)
        log = logger.bind(agent_id=agent_id, container_name=name)

        async with _deploy_semaphore:
            log.info("docker_deploy_start")

            # Upsert AgentDeployment row → pending
            result = await db.execute(
                select(AgentDeployment).where(AgentDeployment.agent_id == _uuid.UUID(agent_id))
            )
            deployment = result.scalar_one_or_none()
            # container_url is unknown until we resolve the host port (on macOS/Windows host);
            # in Docker, we know it upfront from the hostname.
            pending_url: str | None = url if _IN_DOCKER else None
            if deployment is None:
                deployment = AgentDeployment(
                    agent_id=_uuid.UUID(agent_id),
                    status="pending",
                    backend="docker",
                    container_name=name,
                    container_url=pending_url,
                )
                db.add(deployment)
            else:
                deployment.status = "pending"
                deployment.backend = "docker"
                deployment.container_name = name
                deployment.container_url = pending_url
                deployment.error_message = None
            await db.commit()
            await db.refresh(deployment)

            loop = asyncio.get_running_loop()
            try:
                client = await loop.run_in_executor(None, docker.from_env)

                env_vars = {
                    "AGENT_ID": agent_id,
                    "DATABASE_URL": str(settings.DATABASE_URL),
                    "REDIS_URL": str(settings.REDIS_URL),
                    "OPENAI_API_KEY": settings.OPENAI_API_KEY or "",
                    "DEEPGRAM_API_KEY": settings.DEEPGRAM_API_KEY or "",
                    "ELEVENLABS_API_KEY": settings.ELEVENLABS_API_KEY or "",
                    "PORT": "8001",
                }

                mem_limit = settings.AGENT_CONTAINER_MEMORY_LIMIT
                cpu_period = 100_000
                cpu_quota = int(settings.AGENT_CONTAINER_CPU_LIMIT * cpu_period)

                # Remove existing container with same name (if any)
                def _cleanup_old() -> None:
                    with contextlib.suppress(Exception):
                        old = client.containers.get(name)
                        old.stop(timeout=5)
                        old.remove(force=True)

                await loop.run_in_executor(None, _cleanup_old)

                def _run_container() -> Any:
                    # On the host (macOS/Windows), bind a random port so we can
                    # reach the container via localhost. Inside Docker, no binding
                    # needed — hostname routing works on the shared network.
                    port_bindings: dict[str, object] | None = (
                        None if _IN_DOCKER else {"8001/tcp": None}
                    )
                    return client.containers.run(
                        settings.AGENT_RUNTIME_IMAGE,
                        name=name,
                        detach=True,
                        environment=env_vars,
                        network=settings.DOCKER_NETWORK_NAME,
                        mem_limit=mem_limit,
                        cpu_period=cpu_period,
                        cpu_quota=cpu_quota,
                        restart_policy={"Name": "unless-stopped"},
                        ports=port_bindings,
                    )

                container: Any = await loop.run_in_executor(None, _run_container)

                container_id: str = getattr(container, "id", "")
                deployment.container_id = container_id

                # Resolve the actual URL (host-mapped port when not in Docker)
                if not _IN_DOCKER:

                    def _get_host_port() -> int:
                        container.reload()
                        bindings = container.ports.get("8001/tcp") or []
                        return _require_host_port(bindings)

                    host_port = await loop.run_in_executor(None, _get_host_port)
                    url = self._container_url(name, host_port)
                    deployment.container_url = url
                    log.info("docker_host_port_bound", host_port=host_port)

                await db.commit()

            except Exception as exc:
                log.exception("docker_deploy_failed", error=str(exc))
                deployment.status = "failed"
                deployment.error_message = str(exc)
                await db.commit()
                raise

        # Register URL in Redis immediately (outside semaphore)
        redis = await get_redis()
        await redis.set(_REDIS_KEY_PREFIX + agent_id, url)

        # Poll health endpoint
        try:
            await _wait_for_health(url, agent_id, _HEALTH_POLL_TIMEOUT)
        except TimeoutError as exc:
            deployment.status = "failed"
            deployment.error_message = str(exc)
            await db.commit()
            raise

        deployment.status = "running"
        await db.commit()
        await db.refresh(deployment)
        log.info("docker_deploy_complete", url=url)
        return deployment

    async def teardown(self, agent_id: str, db: AsyncSession) -> None:
        """Stop and remove the Docker container for the given agent."""
        import docker

        log = logger.bind(agent_id=agent_id)
        log.info("docker_teardown_start")

        # Remove Redis routing key first (stops new traffic immediately)
        redis = await get_redis()
        await redis.delete(_REDIS_KEY_PREFIX + agent_id)

        result = await db.execute(
            select(AgentDeployment).where(AgentDeployment.agent_id == _uuid.UUID(agent_id))
        )
        deployment = result.scalar_one_or_none()

        if deployment and deployment.container_name:
            name = deployment.container_name
            loop = asyncio.get_running_loop()

            def _stop_and_remove() -> None:
                with contextlib.suppress(Exception):
                    client = docker.from_env()
                    container = client.containers.get(name)
                    container.stop(timeout=10)
                    container.remove(force=True)

            await loop.run_in_executor(None, _stop_and_remove)

        if deployment:
            deployment.status = "stopped"
            await db.commit()

        log.info("docker_teardown_complete")

    async def get_agent_url(self, agent_id: str) -> str | None:
        """Return the internal container URL from Redis, or None."""
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
                            log.info("container_healthy")
                            return
                    except (httpx.RequestError, httpx.HTTPStatusError):
                        pass
                    await asyncio.sleep(_HEALTH_POLL_INTERVAL)
    except TimeoutError:
        msg = f"Agent container {agent_id} did not become healthy within {timeout_secs}s"
        raise TimeoutError(msg) from None
