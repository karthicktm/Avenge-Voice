"""Workspace member model for role-based access control."""

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


class WorkspaceRole(str, Enum):
    """Workspace member roles."""

    ADMIN = "admin"  # Can manage workspace, members, and agents
    MEMBER = "member"  # Can use assigned agents
    VIEWER = "viewer"  # Read-only access


class WorkspaceMember(Base, TimestampMixin):
    """Junction table for workspace membership with roles.

    Tracks which users belong to which workspaces and their roles.
    """

    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uq_workspace_user"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Role in this workspace
    role: Mapped[WorkspaceRole] = mapped_column(
        String(50), nullable=False, default=WorkspaceRole.MEMBER, comment="User's role in workspace"
    )

    # Invitation tracking
    invited_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who invited",
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="When user joined workspace",
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="members")
    user: Mapped["User"] = relationship(
        "User", foreign_keys=[user_id], back_populates="workspace_memberships"
    )
    inviter: Mapped["User | None"] = relationship("User", foreign_keys=[invited_by])

    def __repr__(self) -> str:
        """String representation."""
        return (
            f"<WorkspaceMember workspace={self.workspace_id} user={self.user_id} role={self.role}>"
        )
