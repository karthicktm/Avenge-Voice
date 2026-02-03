"""Agent assignment model for user-to-agent access control."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from app.models.workspace import Workspace


class AgentAssignment(Base, TimestampMixin):
    """Agent assignment model.

    Tracks which users are assigned to which agents within a workspace.
    Only assigned users can access and use specific agents.
    """

    __tablename__ = "agent_assignments"
    __table_args__ = (
        UniqueConstraint("agent_id", "user_id", "workspace_id", name="uq_agent_user_workspace"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Assignment metadata
    assigned_by: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="User who made assignment"
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="When assignment was made",
    )

    # Relationships
    agent: Mapped["Agent"] = relationship("Agent", back_populates="user_assignments")
    user: Mapped["User"] = relationship("User", foreign_keys=[user_id], back_populates="agent_assignments")
    workspace: Mapped["Workspace"] = relationship("Workspace")
    assigner: Mapped["User"] = relationship("User", foreign_keys=[assigned_by])

    def __repr__(self) -> str:
        """String representation."""
        return f"<AgentAssignment agent={self.agent_id} user={self.user_id} workspace={self.workspace_id}>"
