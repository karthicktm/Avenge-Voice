"""Agent deployment model - tracks container/service status per agent."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class AgentDeployment(Base, TimestampMixin):
    """Tracks deployment status for an agent's dedicated container/service."""

    __tablename__ = "agent_deployments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    container_id: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="Docker container ID or Railway service ID"
    )
    container_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="e.g. 'agent-abc123def456'"
    )
    container_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="e.g. 'http://agent-abc123def456:8001'"
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending | running | stopped | failed",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    backend: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="'docker' | 'railway'"
    )

    # Relationship back to agent
    agent: Mapped["Agent"] = relationship("Agent", back_populates="deployment")

    def __repr__(self) -> str:
        return (
            f"<AgentDeployment(id={self.id}, agent_id={self.agent_id}, "
            f"status={self.status}, backend={self.backend})>"
        )
