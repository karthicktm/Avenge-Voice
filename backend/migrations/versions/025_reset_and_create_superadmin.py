"""Reset all users and create fresh super admin.

This migration clears all existing users, workspaces, and organizations,
then creates a single super admin user.

Revision ID: 025_reset_and_create_superadmin
Revises: 024_verify_all_admin_users
Create Date: 2024-02-08
"""

from alembic import op
import sqlalchemy as sa
from passlib.context import CryptContext

# revision identifiers, used by Alembic.
revision = "025_reset_and_create_superadmin"
down_revision = "024_verify_all_admin_users"
branch_labels = None
depends_on = None

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def upgrade() -> None:
    """Clear all data and create fresh super admin."""

    # Delete in order respecting foreign key constraints
    # 1. Delete agent assignments first (references agents and workspaces)
    op.execute("DELETE FROM agent_workspace")

    # 2. Delete workspace members (references users and workspaces)
    op.execute("DELETE FROM workspace_members")

    # 3. Delete workspace invitations (references workspaces)
    op.execute("DELETE FROM workspace_invitations")

    # 4. Delete agents (references workspaces)
    op.execute("DELETE FROM agents")

    # 5. Delete workspaces (references organizations)
    op.execute("DELETE FROM workspaces")

    # 6. Delete user profiles (references users)
    op.execute("DELETE FROM user_profiles")

    # 7. Delete quota-related tables
    op.execute("DELETE FROM usage_records")
    op.execute("DELETE FROM agent_quotas")
    op.execute("DELETE FROM user_quotas")
    op.execute("DELETE FROM workspace_quotas")

    # 8. Delete billing-related tables
    op.execute("DELETE FROM usage_alerts")
    op.execute("DELETE FROM invoices")
    op.execute("DELETE FROM payment_methods")
    op.execute("DELETE FROM billing_events")

    # 9. Delete audit logs
    op.execute("DELETE FROM audit_logs")

    # 10. Delete users (references organizations)
    op.execute("DELETE FROM users")

    # 11. Delete organizations
    op.execute("DELETE FROM organizations")

    # Create super admin user
    # Password: Admin@123456 (hashed)
    hashed_password = pwd_context.hash("Admin@123456")

    op.execute(
        f"""
        INSERT INTO users (email, hashed_password, full_name, role, email_verified, is_active, created_at, updated_at)
        VALUES (
            'admin@avenge.com',
            '{hashed_password}',
            'Super Admin',
            'super_admin',
            TRUE,
            TRUE,
            NOW(),
            NOW()
        )
        """
    )

    print("=" * 50)
    print("Super Admin Created!")
    print("=" * 50)
    print("Email: admin@avenge.com")
    print("Password: Admin@123456")
    print("=" * 50)


def downgrade() -> None:
    """No downgrade - this is a destructive migration."""
    pass
