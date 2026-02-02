"""add_tool_configs_to_agents

Revision ID: d3d5a98635d5
Revises: 0d6a5b92ea4d
Create Date: 2026-02-01 17:30:38.690697

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd3d5a98635d5'
down_revision: Union[str, Sequence[str], None] = '0d6a5b92ea4d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tool_configs column to agents table."""
    op.add_column(
        'agents',
        sa.Column(
            'tool_configs',
            sa.JSON(),
            nullable=False,
            server_default='{}',
            comment='Per-tool configuration: {tool_id: {config_key: value}}'
        )
    )


def downgrade() -> None:
    """Remove tool_configs column from agents table."""
    op.drop_column('agents', 'tool_configs')
