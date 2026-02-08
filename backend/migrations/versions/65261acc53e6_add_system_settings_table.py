"""Add system_settings table

Revision ID: 65261acc53e6
Revises: 018_fix_integrations_unique
Create Date: 2026-02-06 11:18:42.050043

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "65261acc53e6"
down_revision: Union[str, Sequence[str], None] = "018_fix_integrations_unique"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create system_settings table."""
    op.create_table(
        "system_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    """Drop system_settings table."""
    op.drop_table("system_settings")
