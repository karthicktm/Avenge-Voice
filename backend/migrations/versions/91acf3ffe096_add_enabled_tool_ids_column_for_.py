"""Add enabled_tool_ids column for granular tool selection

Revision ID: 91acf3ffe096
Revises: 010_privacy_compliance
Create Date: 2025-11-28 01:36:32.904136

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '91acf3ffe096'
down_revision: Union[str, Sequence[str], None] = '010_privacy_compliance'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add enabled_tool_ids column for granular tool selection per agent."""
    op.add_column(
        'agents',
        sa.Column(
            'enabled_tool_ids',
            sa.JSON(),
            nullable=False,
            server_default='{}',
            comment='Granular tool selection: {integration_id: [tool_id1, tool_id2]}'
        )
    )


def downgrade() -> None:
    """Remove enabled_tool_ids column."""
    op.drop_column('agents', 'enabled_tool_ids')
