"""Simple verify admin@avenge.com.

Just set email_verified = TRUE for admin@avenge.com user.

Revision ID: 026_simple_verify_admin
Revises: 025_reset_and_create_superadmin
Create Date: 2024-02-08
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "026_simple_verify_admin"
down_revision = "024_verify_all_admin_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Verify admin@avenge.com email."""
    op.execute(
        """
        UPDATE users
        SET email_verified = TRUE
        WHERE email = 'admin@avenge.com'
        """
    )


def downgrade() -> None:
    """No downgrade."""
    pass
