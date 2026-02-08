"""Verify existing super admin email addresses.

This migration ensures that all existing super admin users have their
email_verified flag set to True, as they were created before the email
verification feature was implemented.

Revision ID: 023_verify_existing_superadmins
Revises: 022_add_billing_tables
Create Date: 2024-02-08
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "023_verify_existing_superadmins"
down_revision = "022_add_billing_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Verify email for all existing super admin users."""
    # Update all super admin users to have email_verified = True
    op.execute(
        """
        UPDATE users
        SET email_verified = TRUE
        WHERE role = 'super_admin' AND email_verified = FALSE
        """
    )


def downgrade() -> None:
    """No downgrade - we don't want to un-verify super admins."""
    pass
