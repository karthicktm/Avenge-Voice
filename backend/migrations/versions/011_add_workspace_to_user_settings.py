"""Add workspace_id to user_settings table for per-workspace API keys.

Revision ID: 011_workspace_user_settings
Revises: e0fb7b56d9b4
Create Date: 2024-11-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_workspace_user_settings"
down_revision: str | None = "e0fb7b56d9b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add workspace_id to user_settings table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "user_settings" in existing_tables:
        existing_columns = [c["name"] for c in inspector.get_columns("user_settings")]

        # Drop the unique constraint on user_id first (we'll add a new composite one)
        if "workspace_id" not in existing_columns:
            # Drop existing unique constraint on user_id
            try:
                op.drop_constraint("user_settings_user_id_key", "user_settings", type_="unique")
            except Exception:
                pass  # Constraint may not exist

            # Add workspace_id column
            op.add_column(
                "user_settings",
                sa.Column(
                    "workspace_id",
                    sa.Uuid(as_uuid=True),
                    nullable=True,
                    comment="Workspace this setting belongs to (null = user-level default)",
                ),
            )
            op.create_index("ix_user_settings_workspace_id", "user_settings", ["workspace_id"])
            op.create_foreign_key(
                "fk_user_settings_workspace_id",
                "user_settings",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )

            # Add unique constraint on (user_id, workspace_id)
            # This allows one settings record per user per workspace
            op.create_unique_constraint(
                "uq_user_settings_user_workspace",
                "user_settings",
                ["user_id", "workspace_id"],
            )


def downgrade() -> None:
    """Remove workspace_id from user_settings table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "user_settings" in existing_tables:
        existing_columns = [c["name"] for c in inspector.get_columns("user_settings")]
        if "workspace_id" in existing_columns:
            # Drop unique constraint
            op.drop_constraint("uq_user_settings_user_workspace", "user_settings", type_="unique")

            # Drop foreign key and index
            op.drop_constraint("fk_user_settings_workspace_id", "user_settings", type_="foreignkey")
            op.drop_index("ix_user_settings_workspace_id", "user_settings")
            op.drop_column("user_settings", "workspace_id")

            # Re-add the original unique constraint on user_id only
            op.create_unique_constraint("user_settings_user_id_key", "user_settings", ["user_id"])
