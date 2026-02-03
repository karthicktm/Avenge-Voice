"""Organization model for multi-tenant SaaS architecture."""

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.workspace import Workspace


class PlanType(str, Enum):
    """Subscription plan types."""

    FREE = "free"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    """Subscription status."""

    TRIAL = "trial"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class Organization(Base, TimestampMixin):
    """Organization model for multi-tenant architecture.

    Each organization represents a billing entity with its own:
    - Subscription plan and limits
    - Users and workspaces
    - Usage tracking and metering
    - Feature flags
    """

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Basic info
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="Organization name")
    slug: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, index=True, comment="URL-friendly identifier"
    )

    # Owner relationship
    owner_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True, comment="Organization owner user ID"
    )

    # Subscription & Billing
    plan_type: Mapped[PlanType] = mapped_column(
        String(50),
        nullable=False,
        default=PlanType.FREE,
        index=True,
        comment="Current subscription plan",
    )
    subscription_status: Mapped[SubscriptionStatus] = mapped_column(
        String(50),
        nullable=False,
        default=SubscriptionStatus.TRIAL,
        comment="Current subscription status",
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Trial period end date"
    )
    subscription_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Subscription start date"
    )
    subscription_ends_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Subscription end date"
    )

    # Plan Limits (based on plan_type)
    max_users: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Maximum users allowed"
    )
    max_agents: Mapped[int] = mapped_column(
        Integer, nullable=False, default=2, comment="Maximum agents allowed"
    )
    max_workspaces: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Maximum workspaces allowed"
    )
    max_call_minutes_per_month: Mapped[int] = mapped_column(
        Integer, nullable=False, default=100, comment="Maximum call minutes per month"
    )
    max_storage_gb: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="Maximum storage in GB"
    )

    # Usage Tracking (reset monthly)
    current_users_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Current number of users"
    )
    current_agents_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Current number of agents"
    )
    current_workspaces_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Current number of workspaces"
    )
    current_month_call_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="Call minutes used this month"
    )
    current_month_storage_gb: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, comment="Storage used in GB"
    )
    usage_reset_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        comment="Last monthly usage reset",
    )

    # Feature Flags (plan-based features)
    features_enabled: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
        comment="List of enabled feature flags for this organization",
    )

    # Payment Integration (for future Stripe integration)
    stripe_customer_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Stripe customer ID"
    )
    stripe_subscription_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="Stripe subscription ID"
    )
    payment_method_last4: Mapped[str | None] = mapped_column(
        String(4), nullable=True, comment="Last 4 digits of payment method"
    )
    next_billing_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="Next billing date"
    )

    # Organization Status
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, comment="Whether organization is active"
    )

    # Metadata
    signup_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="Metadata collected during signup (purpose, estimated users, etc.)",
    )

    # Relationships
    owner: Mapped["User"] = relationship(
        "User", foreign_keys="Organization.owner_id", back_populates="owned_organization"
    )
    users: Mapped[list["User"]] = relationship(
        "User", foreign_keys="User.organization_id", back_populates="organization"
    )
    workspaces: Mapped[list["Workspace"]] = relationship(
        "Workspace", back_populates="organization", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        """String representation."""
        return f"<Organization {self.id} - {self.name} ({self.plan_type})>"

    def is_within_limits(self, resource_type: str) -> bool:
        """Check if organization is within limits for a resource type.

        Args:
            resource_type: Type of resource (users, agents, workspaces, call_minutes, storage)

        Returns:
            True if within limits, False otherwise
        """
        limits_map = {
            "users": (self.current_users_count, self.max_users),
            "agents": (self.current_agents_count, self.max_agents),
            "workspaces": (self.current_workspaces_count, self.max_workspaces),
            "call_minutes": (self.current_month_call_minutes, self.max_call_minutes_per_month),
            "storage": (self.current_month_storage_gb, self.max_storage_gb),
        }

        if resource_type not in limits_map:
            return True

        current, maximum = limits_map[resource_type]
        return current < maximum

    def get_usage_percentage(self, resource_type: str) -> float:
        """Get usage percentage for a resource type.

        Args:
            resource_type: Type of resource

        Returns:
            Usage percentage (0-100)
        """
        limits_map = {
            "users": (self.current_users_count, self.max_users),
            "agents": (self.current_agents_count, self.max_agents),
            "workspaces": (self.current_workspaces_count, self.max_workspaces),
            "call_minutes": (self.current_month_call_minutes, self.max_call_minutes_per_month),
            "storage": (self.current_month_storage_gb, self.max_storage_gb),
        }

        if resource_type not in limits_map:
            return 0.0

        current, maximum = limits_map[resource_type]
        if maximum == 0:
            return 0.0

        return (current / maximum) * 100
