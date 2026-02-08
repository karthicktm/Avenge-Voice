"""Audit log model for tracking user actions.

Provides a comprehensive audit trail for:
- User authentication events
- User management actions
- Organization and workspace changes
- Agent configuration changes
"""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditAction(str, PyEnum):
    """Enumeration of audited actions."""

    # Authentication
    USER_LOGIN = "user.login"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGOUT = "user.logout"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_EMAIL_VERIFIED = "user.email_verified"

    # User management
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"
    USER_ROLE_CHANGED = "user.role_changed"
    USER_INVITED = "user.invited"
    USER_ACTIVATED = "user.activated"
    USER_DEACTIVATED = "user.deactivated"

    # Organization
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_UPDATED = "organization.updated"
    ORGANIZATION_SETTINGS_CHANGED = "organization.settings_changed"

    # Workspace
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_UPDATED = "workspace.updated"
    WORKSPACE_DELETED = "workspace.deleted"
    WORKSPACE_MEMBER_ADDED = "workspace.member_added"
    WORKSPACE_MEMBER_REMOVED = "workspace.member_removed"

    # Agent
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    AGENT_PUBLISHED = "agent.published"
    AGENT_UNPUBLISHED = "agent.unpublished"

    # System
    SYSTEM_SETTINGS_CHANGED = "system.settings_changed"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"


class AuditLog(Base):
    """Audit log entry.

    Records actions performed by users for security and compliance.
    """

    __tablename__ = "audit_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Actor information
    actor_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        comment="User who performed the action (null for system actions)",
    )
    actor_email: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Actor email at time of action (for deleted users)",
    )
    actor_role: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Actor role at time of action",
    )

    # Action details
    action: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Action type from AuditAction enum",
    )
    resource_type: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        comment="Type of resource affected (user, agent, workspace, etc.)",
    )
    resource_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="ID of the affected resource",
    )

    # Organization/workspace context
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Additional details
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable description of the action",
    )
    details: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
        comment="Additional structured details about the action",
    )

    # Request context
    ip_address: Mapped[str | None] = mapped_column(
        String(45),
        nullable=True,
        comment="Client IP address",
    )
    user_agent: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="Client user agent",
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("ix_audit_logs_actor_id_created_at", "actor_id", "created_at"),
        Index("ix_audit_logs_org_created_at", "organization_id", "created_at"),
        Index("ix_audit_logs_resource", "resource_type", "resource_id"),
    )
