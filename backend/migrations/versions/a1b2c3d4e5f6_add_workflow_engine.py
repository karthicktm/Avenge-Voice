"""Add workflow engine (workflows table + agent.workflow_id)

Revision ID: a1b2c3d4e5f6
Revises: fca9f1b81524
Create Date: 2026-05-21 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "040_fix_lookup_fts_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflows",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("workspace_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("nodes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("edges", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_workflows_workspace_id", "workflows", ["workspace_id"])

    op.add_column(
        "agents",
        sa.Column("workflow_id", sa.Uuid(as_uuid=True), sa.ForeignKey("workflows.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_agents_workflow_id", "agents", ["workflow_id"])


def downgrade() -> None:
    op.drop_index("ix_agents_workflow_id", table_name="agents")
    op.drop_column("agents", "workflow_id")
    op.drop_index("ix_workflows_workspace_id", table_name="workflows")
    op.drop_table("workflows")
