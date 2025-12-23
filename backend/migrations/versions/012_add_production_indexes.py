"""Add production performance indexes for call_records and workspaces.

Revision ID: 012_add_production_indexes
Revises: 011_workspace_user_settings
Create Date: 2025-11-29

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "012_add_production_indexes"
down_revision: Union[str, None] = "011_workspace_user_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite indexes for production query patterns."""
    # Call records - common query patterns
    # List calls by user with ordering
    op.create_index(
        "ix_call_records_user_id_started_at",
        "call_records",
        ["user_id", "started_at"],
        unique=False,
        postgresql_using="btree",
    )

    # List calls by workspace with ordering
    op.create_index(
        "ix_call_records_workspace_id_started_at",
        "call_records",
        ["workspace_id", "started_at"],
        unique=False,
        postgresql_using="btree",
    )

    # Filter calls by user and status
    op.create_index(
        "ix_call_records_user_id_status",
        "call_records",
        ["user_id", "status"],
        unique=False,
    )

    # Agents - list by user with ordering
    op.create_index(
        "ix_agents_user_id_created_at",
        "agents",
        ["user_id", "created_at"],
        unique=False,
    )

    # Contacts - filter by workspace with ordering
    op.create_index(
        "ix_contacts_workspace_id_created_at",
        "contacts",
        ["workspace_id", "created_at"],
        unique=False,
    )

    # Phone numbers - list by user with ordering
    op.create_index(
        "ix_phone_numbers_user_id_created_at",
        "phone_numbers",
        ["user_id", "created_at"],
        unique=False,
    )

    # User settings - lookup by user and workspace
    op.create_index(
        "ix_user_settings_user_id_workspace_id",
        "user_settings",
        ["user_id", "workspace_id"],
        unique=False,
    )


def downgrade() -> None:
    """Remove production indexes."""
    op.drop_index("ix_user_settings_user_id_workspace_id", table_name="user_settings")
    op.drop_index("ix_phone_numbers_user_id_created_at", table_name="phone_numbers")
    op.drop_index("ix_contacts_workspace_id_created_at", table_name="contacts")
    op.drop_index("ix_agents_user_id_created_at", table_name="agents")
    op.drop_index("ix_call_records_user_id_status", table_name="call_records")
    op.drop_index("ix_call_records_workspace_id_started_at", table_name="call_records")
    op.drop_index("ix_call_records_user_id_started_at", table_name="call_records")
