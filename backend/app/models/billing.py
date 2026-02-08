"""Billing models for Stripe integration and usage tracking.

This module defines:
- BillingEvent: Track all Stripe webhook events (idempotency)
- Invoice: Store invoice history from Stripe
- PaymentMethod: Store payment methods
- UsageAlert: Track threshold alerts (50%, 80%, 90%, 100%)
"""

import uuid
from datetime import UTC, datetime
from enum import Enum as PyEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.organization import Organization


class BillingEventType(str, PyEnum):
    """Types of Stripe billing events."""

    # Subscription events
    SUBSCRIPTION_CREATED = "customer.subscription.created"
    SUBSCRIPTION_UPDATED = "customer.subscription.updated"
    SUBSCRIPTION_DELETED = "customer.subscription.deleted"

    # Invoice events
    INVOICE_CREATED = "invoice.created"
    INVOICE_PAID = "invoice.paid"
    INVOICE_PAYMENT_FAILED = "invoice.payment_failed"
    INVOICE_UPCOMING = "invoice.upcoming"

    # Payment method events
    PAYMENT_METHOD_ATTACHED = "payment_method.attached"
    PAYMENT_METHOD_DETACHED = "payment_method.detached"
    PAYMENT_METHOD_UPDATED = "payment_method.updated"

    # Checkout events
    CHECKOUT_COMPLETED = "checkout.session.completed"
    CHECKOUT_EXPIRED = "checkout.session.expired"

    # Customer events
    CUSTOMER_CREATED = "customer.created"
    CUSTOMER_UPDATED = "customer.updated"


class BillingEventStatus(str, PyEnum):
    """Status of billing event processing."""

    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    SKIPPED = "skipped"


class InvoiceStatus(str, PyEnum):
    """Status of an invoice."""

    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


class PaymentMethodType(str, PyEnum):
    """Types of payment methods."""

    CARD = "card"
    BANK_ACCOUNT = "bank_account"
    SEPA_DEBIT = "sepa_debit"
    US_BANK_ACCOUNT = "us_bank_account"


class AlertThreshold(str, PyEnum):
    """Usage alert thresholds."""

    THRESHOLD_50 = "50"
    THRESHOLD_80 = "80"
    THRESHOLD_90 = "90"
    THRESHOLD_100 = "100"


class AlertStatus(str, PyEnum):
    """Status of a usage alert."""

    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"


class BillingEvent(Base):
    """Track all Stripe webhook events for idempotency.

    Each Stripe event is stored to prevent duplicate processing.
    """

    __tablename__ = "billing_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    stripe_event_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Stripe event ID for idempotency",
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Stripe event type",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=BillingEventStatus.PENDING.value,
        comment="Processing status",
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Full Stripe event payload",
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Error message if processing failed",
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="When the event was processed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization | None"] = relationship(back_populates="billing_events")

    __table_args__ = (
        Index("ix_billing_events_org_type", "organization_id", "event_type"),
        Index("ix_billing_events_created_at", "created_at"),
    )


class Invoice(Base):
    """Store invoice history from Stripe."""

    __tablename__ = "invoices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    stripe_invoice_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Stripe invoice ID",
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=InvoiceStatus.DRAFT.value,
    )
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="usd",
    )
    amount_due: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Amount due in cents",
    )
    amount_paid: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Amount paid in cents",
    )
    subtotal: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Subtotal in cents",
    )
    tax: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Tax amount in cents",
    )
    total: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Total in cents",
    )
    invoice_pdf_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="URL to download invoice PDF",
    )
    hosted_invoice_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="URL to view invoice online",
    )
    period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Billing period start",
    )
    period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="Billing period end",
    )
    due_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    line_items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Invoice line items",
    )
    invoice_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="invoices")

    __table_args__ = (
        Index("ix_invoices_org_status", "organization_id", "status"),
        Index("ix_invoices_created_at", "created_at"),
    )


class PaymentMethod(Base):
    """Store payment methods from Stripe."""

    __tablename__ = "payment_methods"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    stripe_payment_method_id: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,
        comment="Stripe payment method ID",
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=PaymentMethodType.CARD.value,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="Whether this is the default payment method",
    )
    # Card details (masked)
    card_brand: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Card brand (visa, mastercard, etc.)",
    )
    card_last4: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
        comment="Last 4 digits of card",
    )
    card_exp_month: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Card expiration month",
    )
    card_exp_year: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        comment="Card expiration year",
    )
    # Bank account details (masked)
    bank_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )
    bank_last4: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
        comment="Last 4 digits of account",
    )
    billing_details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Billing details (name, address, etc.)",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="payment_methods")

    __table_args__ = (Index("ix_payment_methods_org_default", "organization_id", "is_default"),)


class UsageAlert(Base):
    """Track usage threshold alerts."""

    __tablename__ = "usage_alerts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    resource_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Type of resource (voice_minutes, llm_tokens, etc.)",
    )
    threshold: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        comment="Threshold percentage (50, 80, 90, 100)",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default=AlertStatus.PENDING.value,
    )
    current_usage: Mapped[float] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Usage at time of alert",
    )
    limit: Mapped[float] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Limit at time of alert",
    )
    percentage: Mapped[float] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Usage percentage at time of alert",
    )
    email_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    email_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    acknowledged_by_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        comment="Billing period this alert belongs to",
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )

    # Relationships
    organization: Mapped["Organization"] = relationship(back_populates="usage_alerts")

    __table_args__ = (
        Index(
            "ix_usage_alerts_org_resource_threshold_period",
            "organization_id",
            "resource_type",
            "threshold",
            "period_start",
            unique=True,
        ),
        Index("ix_usage_alerts_status", "status"),
        Index("ix_usage_alerts_created_at", "created_at"),
    )
