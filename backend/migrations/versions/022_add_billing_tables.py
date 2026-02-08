"""Add billing tables for Stripe integration

Revision ID: 022_add_billing_tables
Revises: 021_add_audit_logs
Create Date: 2026-02-07 10:00:00.000000

This migration adds:
- billing_events: Track Stripe webhook events (idempotency)
- invoices: Store invoice history from Stripe
- payment_methods: Store payment methods
- usage_alerts: Track threshold alerts (50%, 80%, 90%, 100%)
- Organization billing fields: stripe_price_id, billing_email, overage settings
- AgentQuota safety limits: max_tokens_per_request, max_cost_per_call_cents, etc.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "022_add_billing_tables"
down_revision: Union[str, Sequence[str], None] = "021_add_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create billing tables and extend existing models."""
    # Add new columns to organizations table
    op.add_column(
        "organizations",
        sa.Column("stripe_price_id", sa.String(100), nullable=True, comment="Current Stripe price ID"),
    )
    op.add_column(
        "organizations",
        sa.Column("billing_email", sa.String(255), nullable=True, comment="Billing contact email"),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "overage_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Allow usage-based overages",
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "overage_rates",
            postgresql.JSON(),
            nullable=False,
            server_default="{}",
            comment="Per-resource overage pricing in cents",
        ),
    )

    # Add indexes to existing Stripe columns on organizations
    op.create_index("ix_organizations_stripe_customer_id", "organizations", ["stripe_customer_id"])
    op.create_index("ix_organizations_stripe_subscription_id", "organizations", ["stripe_subscription_id"])

    # Add new columns to agent_quotas table for safety limits
    op.add_column(
        "agent_quotas",
        sa.Column(
            "max_tokens_per_request",
            sa.Integer(),
            nullable=False,
            server_default="4096",
            comment="Max tokens per LLM request",
        ),
    )
    op.add_column(
        "agent_quotas",
        sa.Column(
            "max_images_per_request",
            sa.Integer(),
            nullable=False,
            server_default="5",
            comment="Max images per request",
        ),
    )
    op.add_column(
        "agent_quotas",
        sa.Column(
            "max_cost_per_call_cents",
            sa.Integer(),
            nullable=False,
            server_default="500",
            comment="Max cost per call in cents ($5 default)",
        ),
    )
    op.add_column(
        "agent_quotas",
        sa.Column(
            "max_cost_per_day_cents",
            sa.Integer(),
            nullable=False,
            server_default="10000",
            comment="Max cost per day in cents ($100 default)",
        ),
    )

    # Create billing_events table
    op.create_table(
        "billing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "stripe_event_id",
            sa.String(100),
            nullable=False,
            comment="Stripe event ID for idempotency",
        ),
        sa.Column("event_type", sa.String(100), nullable=False, comment="Stripe event type"),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
            comment="Processing status",
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="Full Stripe event payload",
        ),
        sa.Column("error_message", sa.Text(), nullable=True, comment="Error message if processing failed"),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_event_id"),
    )
    op.create_index("ix_billing_events_stripe_event_id", "billing_events", ["stripe_event_id"])
    op.create_index("ix_billing_events_event_type", "billing_events", ["event_type"])
    op.create_index("ix_billing_events_organization_id", "billing_events", ["organization_id"])
    op.create_index("ix_billing_events_org_type", "billing_events", ["organization_id", "event_type"])
    op.create_index("ix_billing_events_created_at", "billing_events", ["created_at"])

    # Create invoices table
    op.create_table(
        "invoices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "stripe_invoice_id",
            sa.String(100),
            nullable=False,
            comment="Stripe invoice ID",
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="usd"),
        sa.Column("amount_due", sa.Integer(), nullable=False, server_default="0", comment="Amount due in cents"),
        sa.Column("amount_paid", sa.Integer(), nullable=False, server_default="0", comment="Amount paid in cents"),
        sa.Column("subtotal", sa.Integer(), nullable=False, server_default="0", comment="Subtotal in cents"),
        sa.Column("tax", sa.Integer(), nullable=False, server_default="0", comment="Tax amount in cents"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0", comment="Total in cents"),
        sa.Column("invoice_pdf_url", sa.String(500), nullable=True, comment="URL to download invoice PDF"),
        sa.Column("hosted_invoice_url", sa.String(500), nullable=True, comment="URL to view invoice online"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=True, comment="Billing period start"),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True, comment="Billing period end"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "line_items",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
            comment="Invoice line items",
        ),
        sa.Column("metadata", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_invoice_id"),
    )
    op.create_index("ix_invoices_stripe_invoice_id", "invoices", ["stripe_invoice_id"])
    op.create_index("ix_invoices_organization_id", "invoices", ["organization_id"])
    op.create_index("ix_invoices_org_status", "invoices", ["organization_id", "status"])
    op.create_index("ix_invoices_created_at", "invoices", ["created_at"])

    # Create payment_methods table
    op.create_table(
        "payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "stripe_payment_method_id",
            sa.String(100),
            nullable=False,
            comment="Stripe payment method ID",
        ),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(50), nullable=False, server_default="card"),
        sa.Column(
            "is_default",
            sa.Boolean(),
            nullable=False,
            server_default="false",
            comment="Whether this is the default payment method",
        ),
        sa.Column("card_brand", sa.String(20), nullable=True, comment="Card brand (visa, mastercard, etc.)"),
        sa.Column("card_last4", sa.String(4), nullable=True, comment="Last 4 digits of card"),
        sa.Column("card_exp_month", sa.Integer(), nullable=True, comment="Card expiration month"),
        sa.Column("card_exp_year", sa.Integer(), nullable=True, comment="Card expiration year"),
        sa.Column("bank_name", sa.String(100), nullable=True),
        sa.Column("bank_last4", sa.String(4), nullable=True, comment="Last 4 digits of account"),
        sa.Column(
            "billing_details",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
            comment="Billing details (name, address, etc.)",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_payment_method_id"),
    )
    op.create_index("ix_payment_methods_stripe_payment_method_id", "payment_methods", ["stripe_payment_method_id"])
    op.create_index("ix_payment_methods_organization_id", "payment_methods", ["organization_id"])
    op.create_index("ix_payment_methods_org_default", "payment_methods", ["organization_id", "is_default"])

    # Create usage_alerts table
    op.create_table(
        "usage_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "resource_type",
            sa.String(50),
            nullable=False,
            comment="Type of resource (voice_minutes, llm_tokens, etc.)",
        ),
        sa.Column("threshold", sa.String(10), nullable=False, comment="Threshold percentage (50, 80, 90, 100)"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("current_usage", sa.Float(), nullable=False, server_default="0", comment="Usage at time of alert"),
        sa.Column("limit", sa.Float(), nullable=False, server_default="0", comment="Limit at time of alert"),
        sa.Column(
            "percentage",
            sa.Float(),
            nullable=False,
            server_default="0",
            comment="Usage percentage at time of alert",
        ),
        sa.Column("email_sent", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_id", sa.Integer(), nullable=True),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False, comment="Billing period start"),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["acknowledged_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_alerts_organization_id", "usage_alerts", ["organization_id"])
    op.create_index(
        "ix_usage_alerts_org_resource_threshold_period",
        "usage_alerts",
        ["organization_id", "resource_type", "threshold", "period_start"],
        unique=True,
    )
    op.create_index("ix_usage_alerts_status", "usage_alerts", ["status"])
    op.create_index("ix_usage_alerts_created_at", "usage_alerts", ["created_at"])


def downgrade() -> None:
    """Drop billing tables and remove added columns."""
    # Drop tables
    op.drop_table("usage_alerts")
    op.drop_table("payment_methods")
    op.drop_table("invoices")
    op.drop_table("billing_events")

    # Remove indexes from organizations
    op.drop_index("ix_organizations_stripe_subscription_id", table_name="organizations")
    op.drop_index("ix_organizations_stripe_customer_id", table_name="organizations")

    # Remove columns from organizations
    op.drop_column("organizations", "overage_rates")
    op.drop_column("organizations", "overage_enabled")
    op.drop_column("organizations", "billing_email")
    op.drop_column("organizations", "stripe_price_id")

    # Remove columns from agent_quotas
    op.drop_column("agent_quotas", "max_cost_per_day_cents")
    op.drop_column("agent_quotas", "max_cost_per_call_cents")
    op.drop_column("agent_quotas", "max_images_per_request")
    op.drop_column("agent_quotas", "max_tokens_per_request")
