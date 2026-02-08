"""Set admin@avenge.com to super_admin role.

Revision ID: 027_set_admin_superadmin_role
Revises: 026_simple_verify_admin
Create Date: 2024-02-08
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "027_set_admin_superadmin_role"
down_revision = "026_simple_verify_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Set admin@avenge.com to super_admin role."""
    op.execute(
        """
        UPDATE users
        SET role = 'super_admin', organization_id = NULL
        WHERE email = 'admin@avenge.com'
        """
    )


def downgrade() -> None:
    """No downgrade."""
    pass
