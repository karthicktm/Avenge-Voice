"""Add audit logs table for tracking user actions

Revision ID: 021_add_audit_logs
Revises: 020_add_quota_tables
Create Date: 2026-02-06 14:00:00.000000

This migration adds the audit_logs table for security and compliance tracking.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "021_add_audit_logs"
down_revision: Union[str, Sequence[str], None] = "020_add_quota_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create audit_logs table."""
    op.create_table(
        "audit_logs",
        # Primary key
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # Actor information
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("actor_email", sa.String(255), nullable=True),
        sa.Column("actor_role", sa.String(50), nullable=True),
        # Action details
        sa.Column("action", sa.String(50), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        # Organization/workspace context
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Additional details
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("details", postgresql.JSONB(), nullable=True),
        # Request context
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        # Timestamp
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # Constraints
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Indexes for common query patterns
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_actor_id_created_at", "audit_logs", ["actor_id", "created_at"])
    op.create_index("ix_audit_logs_org_created_at", "audit_logs", ["organization_id", "created_at"])
    op.create_index("ix_audit_logs_resource", "audit_logs", ["resource_type", "resource_id"])


def downgrade() -> None:
    """Drop audit_logs table."""
    op.drop_table("audit_logs")
