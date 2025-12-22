"""add user_integrations table

Revision ID: e665adac48b0
Revises: 91acf3ffe096
Create Date: 2025-11-28 03:52:03.966199

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e665adac48b0'
down_revision: Union[str, Sequence[str], None] = '91acf3ffe096'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - No-op migration (workspace_id already added by migration 009)."""
    # This migration is a no-op because migration 009_add_workspace_to_calls_integrations_phones
    # already adds workspace_id to user_integrations table
    pass


def downgrade() -> None:
    """Downgrade schema - No-op migration."""
    # This migration is a no-op
    pass
