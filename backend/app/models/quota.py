"""Quota and usage tracking models.

This module defines the hierarchical quota system:
- Workspace quotas (limits for a workspace)
- User quotas (limits for a user within a workspace)
- Agent quotas (limits for a specific agent)
- Usage records (track consumption against quotas)

Hierarchy: Organization → Workspace → User → Agent
Stricter limits at any level override more permissive limits above.
"""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.agent import Agent
    from app.models.user import User
    from app.models.workspace import Workspace


class ResourceType(str, PyEnum):
    """Types of resources that can be metered and limited."""

    # Voice/Call resources
    VOICE_MINUTES = "voice_minutes"
    CONCURRENT_CALLS = "concurrent_calls"
    CALLS_PER_DAY = "calls_per_day"

    # AI/Generation resources - LLM (granular tracking)
    LLM_TOKENS = "llm_tokens"  # Legacy: total tokens
    LLM_INPUT_TOKENS = "llm_input_tokens"
    LLM_OUTPUT_TOKENS = "llm_output_tokens"
    LLM_REQUESTS = "llm_requests"

    # AI/Generation resources - Realtime/Audio
    REALTIME_SESSION_MINUTES = "realtime_session_minutes"
    AUDIO_PROCESSING_MINUTES = "audio_processing_minutes"

    # AI/Generation resources - Visual
    IMAGE_GENERATIONS = "image_generations"
    VIDEO_MINUTES = "video_minutes"

    # Communication resources
    SMS_MESSAGES = "sms_messages"
    EMAIL_SENDS = "email_sends"

    # Storage resources
    STORAGE_GB = "storage_gb"
    DOCUMENTS = "documents"

    # Entity limits
    AGENTS = "agents"
    WORKSPACES = "workspaces"
    MEMBERS = "members"
    CONTACTS = "contacts"


class QuotaPeriod(str, PyEnum):
    """Time periods for quota enforcement."""

    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"
    LIFETIME = "lifetime"  # Never resets


class WorkspaceQuota(Base):
    """Quota limits for a workspace.

    Defines resource limits that apply to all users and agents within the workspace.
    """

    __tablename__ = "workspace_quotas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Entity limits
    max_members: Mapped[int] = mapped_column(Integer, default=10)
    max_agents: Mapped[int] = mapped_column(Integer, default=5)
    max_documents: Mapped[int] = mapped_column(Integer, default=100)

    # Resource allocations as JSON for flexibility
    # Format: {"resource_type": {"limit": X, "period": "monthly"}}
    resource_allocations: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=lambda: {
            "voice_minutes": {"limit": 1000, "period": "monthly"},
            "storage_gb": {"limit": 5, "period": "lifetime"},
            "llm_tokens": {"limit": 1000000, "period": "monthly"},
        },
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship(back_populates="quota")

    __table_args__ = (Index("ix_workspace_quotas_workspace_id", "workspace_id"),)


class UserQuota(Base):
    """Quota limits for a specific user within a workspace.

    Allows setting per-user limits that are stricter than workspace limits.
    """

    __tablename__ = "user_quotas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )

    # Resource allocations (same format as workspace quotas)
    resource_allocations: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="quotas")
    workspace: Mapped["Workspace"] = relationship()

    __table_args__ = (
        Index("ix_user_quotas_user_workspace", "user_id", "workspace_id", unique=True),
    )


class AgentQuota(Base):
    """Quota limits for a specific agent.

    Allows setting per-agent limits for call handling and cost control.
    """

    __tablename__ = "agent_quotas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # Call limits
    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=1)
    max_call_duration_seconds: Mapped[int] = mapped_column(Integer, default=3600)  # 1 hour
    max_calls_per_day: Mapped[int] = mapped_column(Integer, default=100)

    # Per-call safety limits (prevent runaway costs)
    max_tokens_per_request: Mapped[int] = mapped_column(
        Integer, default=4096, comment="Max tokens per LLM request"
    )
    max_images_per_request: Mapped[int] = mapped_column(
        Integer, default=5, comment="Max images per request"
    )
    max_cost_per_call_cents: Mapped[int] = mapped_column(
        Integer, default=500, comment="Max cost per call in cents ($5 default)"
    )
    max_cost_per_day_cents: Mapped[int] = mapped_column(
        Integer, default=10000, comment="Max cost per day in cents ($100 default)"
    )

    # Additional resource limits
    resource_allocations: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # Relationships
    agent: Mapped["Agent"] = relationship(back_populates="quota")

    __table_args__ = (Index("ix_agent_quotas_agent_id", "agent_id"),)


class UsageRecord(Base):
    """Track resource usage for quota enforcement and billing.

    Records consumption of resources at various hierarchy levels.
    """

    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # Hierarchy identifiers (at least one must be set)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=True,
    )
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=True,
    )
    user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Usage details
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[float] = mapped_column(Integer, nullable=False)  # Use cents/units for precision

    # Period tracking
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Extra data
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_data: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index(
            "ix_usage_records_org_resource_period",
            "organization_id",
            "resource_type",
            "period_start",
        ),
        Index(
            "ix_usage_records_workspace_resource_period",
            "workspace_id",
            "resource_type",
            "period_start",
        ),
        Index("ix_usage_records_user_resource_period", "user_id", "resource_type", "period_start"),
        Index(
            "ix_usage_records_agent_resource_period", "agent_id", "resource_type", "period_start"
        ),
        Index("ix_usage_records_created_at", "created_at"),
    )
