"""Deployment backend factory."""

from app.core.config import settings
from app.services.deployment.base import AgentDeploymentBackend


def get_deployment_backend() -> AgentDeploymentBackend:
    """Return the configured deployment backend.

    Returns:
        AgentDeploymentBackend implementation based on DEPLOYMENT_BACKEND setting.
    """
    if settings.DEPLOYMENT_BACKEND == "railway":
        from app.services.deployment.railway_backend import RailwayBackend

        return RailwayBackend()
    from app.services.deployment.docker_backend import DockerBackend

    return DockerBackend()


__all__ = ["AgentDeploymentBackend", "get_deployment_backend"]
