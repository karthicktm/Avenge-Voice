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
    from sqlalchemy import text

    conn = op.get_bind()

    # Helper to safely delete from table if it exists
    def safe_delete(table_name: str) -> None:
        try:
            conn.execute(text(f"DELETE FROM {table_name}"))
        except Exception:
            pass  # Table doesn't exist, skip

    # Delete in order respecting foreign key constraints
    # 1. Delete agent assignments first (references agents and workspaces)
    safe_delete("agent_workspace")

    # 2. Delete workspace members (references users and workspaces)
    safe_delete("workspace_members")

    # 3. Delete workspace invitations (references workspaces)
    safe_delete("workspace_invitations")

    # 4. Delete agents (references workspaces)
    safe_delete("agents")

    # 5. Delete workspaces (references organizations)
    safe_delete("workspaces")

    # 6. Delete user profiles (references users)
    safe_delete("user_profiles")

    # 7. Delete quota-related tables (may not exist)
    safe_delete("usage_records")
    safe_delete("agent_quotas")
    safe_delete("user_quotas")
    safe_delete("workspace_quotas")

    # 8. Delete billing-related tables (may not exist)
    safe_delete("usage_alerts")
    safe_delete("invoices")
    safe_delete("payment_methods")
    safe_delete("billing_events")

    # 9. Delete audit logs (may not exist)
    safe_delete("audit_logs")

    # 10. Delete users (references organizations)
    safe_delete("users")

    # 11. Delete organizations
    safe_delete("organizations")

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
