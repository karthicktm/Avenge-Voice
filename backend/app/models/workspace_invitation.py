"""Workspace invitation model for inviting users to workspaces."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.workspace_member import WorkspaceRole

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


class InvitationStatus(str, Enum):
    """Invitation status."""

    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class WorkspaceInvitation(Base, TimestampMixin):
    """Workspace invitation model.

    Tracks invitations sent to users to join workspaces.
    """

    __tablename__ = "workspace_invitations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Invitee information
    email: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Email of invited user"
    )

    # Role to assign when accepted
    role: Mapped[WorkspaceRole] = mapped_column(
        String(50),
        nullable=False,
        default=WorkspaceRole.MEMBER,
        comment="Role to assign when invitation is accepted",
    )

    # Invitation token (for secure acceptance)
    token: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        default=lambda: secrets.token_urlsafe(32),
        comment="Unique invitation token",
    )

    # Invitation metadata
    invited_by: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        comment="User who sent invitation",
    )
    status: Mapped[InvitationStatus] = mapped_column(
        String(50),
        nullable=False,
        default=InvitationStatus.PENDING,
        index=True,
        comment="Current invitation status",
    )

    # Expiration (default 7 days)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC) + timedelta(days=7),
        comment="Invitation expiration date",
    )

    # Acceptance tracking
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="When invitation was accepted"
    )
    accepted_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who accepted",
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", back_populates="invitations")
    inviter: Mapped["User"] = relationship("User", foreign_keys=[invited_by])
    accepted_by: Mapped["User | None"] = relationship("User", foreign_keys=[accepted_by_user_id])

    def __repr__(self) -> str:
        """String representation."""
        return f"<WorkspaceInvitation {self.id} - {self.email} ({self.status})>"

    def is_expired(self) -> bool:
        """Check if invitation has expired."""
        return datetime.now(UTC) > self.expires_at

    def can_be_accepted(self) -> bool:
        """Check if invitation can be accepted."""
        return self.status == InvitationStatus.PENDING and not self.is_expired()
