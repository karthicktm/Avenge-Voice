"""fix_user_settings_unique_constraint

Revision ID: ee167a9a2635
Revises: 2aeb78a98185
Create Date: 2025-12-22 12:27:09.648341

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ee167a9a2635'
down_revision: Union[str, Sequence[str], None] = '2aeb78a98185'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the unique index on user_id and replace with non-unique index.

    The unique constraint on user_id prevents having multiple settings per user
    (one per workspace). We need to drop it and keep only the composite unique
    constraint on (user_id, workspace_id).
    """
    # Drop the unique index on user_id
    op.drop_index('ix_user_settings_user_id', table_name='user_settings')

    # Recreate as non-unique index for query performance
    op.create_index('ix_user_settings_user_id', 'user_settings', ['user_id'], unique=False)


def downgrade() -> None:
    """Recreate the unique index on user_id."""
    # Drop the non-unique index
    op.drop_index('ix_user_settings_user_id', table_name='user_settings')

    # Recreate as unique index
    op.create_index('ix_user_settings_user_id', 'user_settings', ['user_id'], unique=True)
