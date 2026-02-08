"""Verify all admin-level users email addresses.

This migration ensures that all existing admin-level users (owner, admin)
have their email_verified flag set to True, as they were created before
the email verification feature was implemented.

Revision ID: 024_verify_all_admin_users
Revises: 023_verify_existing_superadmins
Create Date: 2024-02-08
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "024_verify_all_admin_users"
down_revision = "023_verify_existing_superadmins"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Verify email for all existing admin-level users."""
    # Update all admin-level users to have email_verified = True
    # This includes super_admin, admin, and owner roles
    op.execute(
        """
        UPDATE users
        SET email_verified = TRUE
        WHERE role IN ('super_admin', 'admin', 'owner') AND email_verified = FALSE
        """
    )


def downgrade() -> None:
    """No downgrade - we don't want to un-verify admins."""
    pass
