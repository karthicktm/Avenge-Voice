"""Add agent_deployments table for per-agent container tracking.

Revision ID: 032_add_agent_deployments
Revises: 031_campaign_script_greeting
Create Date: 2026-03-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "032_add_agent_deployments"
down_revision: str = "031_campaign_script_greeting"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_deployments",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "agent_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("agents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("container_id", sa.String(200), nullable=True),
        sa.Column("container_name", sa.String(200), nullable=True),
        sa.Column("container_url", sa.String(500), nullable=True),
        sa.Column(
            "status",
            sa.String(50),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("backend", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_agent_deployments_agent_id", "agent_deployments", ["agent_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_deployments_agent_id", table_name="agent_deployments")
    op.drop_table("agent_deployments")
