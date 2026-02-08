"""Rename organization_owner role to admin

Revision ID: 019_rename_org_owner
Revises: 65261acc53e6
Create Date: 2026-02-06 12:00:00.000000

This migration updates the UserRole enum value from 'organization_owner' to 'admin'
as part of the simplified 3-tier role system (SUPER_ADMIN -> ADMIN -> USER).
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "019_rename_org_owner"
down_revision: Union[str, Sequence[str], None] = "65261acc53e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Rename organization_owner role to admin."""
    # Update existing users with organization_owner role to admin
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'organization_owner'")


def downgrade() -> None:
    """Revert admin role back to organization_owner."""
    op.execute("UPDATE users SET role = 'organization_owner' WHERE role = 'admin'")
