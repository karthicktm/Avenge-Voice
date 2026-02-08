"""Add quota tables for hierarchical resource management

Revision ID: 020_add_quota_tables
Revises: 019_rename_org_owner
Create Date: 2026-02-06 12:30:00.000000

This migration adds the quota system tables:
- workspace_quotas: Limits for workspaces
- user_quotas: Per-user limits within workspaces
- agent_quotas: Per-agent limits for call handling
- usage_records: Track resource consumption
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "020_add_quota_tables"
down_revision: Union[str, Sequence[str], None] = "019_rename_org_owner"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create quota tables."""
    # Workspace quotas
    op.create_table(
        "workspace_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_members", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("max_agents", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_documents", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("resource_allocations", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id"),
    )
    op.create_index("ix_workspace_quotas_workspace_id", "workspace_quotas", ["workspace_id"])

    # User quotas
    op.create_table(
        "user_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_allocations", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_user_quotas_user_workspace",
        "user_quotas",
        ["user_id", "workspace_id"],
        unique=True,
    )

    # Agent quotas
    op.create_table(
        "agent_quotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("max_concurrent_calls", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_call_duration_seconds", sa.Integer(), nullable=False, server_default="3600"),
        sa.Column("max_calls_per_day", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("resource_allocations", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_id"),
    )
    op.create_index("ix_agent_quotas_agent_id", "agent_quotas", ["agent_id"])

    # Usage records
    op.create_table(
        "usage_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_usage_records_org_resource_period",
        "usage_records",
        ["organization_id", "resource_type", "period_start"],
    )
    op.create_index(
        "ix_usage_records_workspace_resource_period",
        "usage_records",
        ["workspace_id", "resource_type", "period_start"],
    )
    op.create_index(
        "ix_usage_records_user_resource_period",
        "usage_records",
        ["user_id", "resource_type", "period_start"],
    )
    op.create_index(
        "ix_usage_records_agent_resource_period",
        "usage_records",
        ["agent_id", "resource_type", "period_start"],
    )
    op.create_index("ix_usage_records_created_at", "usage_records", ["created_at"])


def downgrade() -> None:
    """Drop quota tables."""
    op.drop_table("usage_records")
    op.drop_table("agent_quotas")
    op.drop_table("user_quotas")
    op.drop_table("workspace_quotas")
