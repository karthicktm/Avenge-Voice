"""Add workspace_id to call_records, user_integrations, and create phone_numbers table.

Revision ID: 009_workspace_to_tables
Revises: 008_add_turn_detection_settings
Create Date: 2024-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "009_workspace_to_tables"
down_revision: str | None = "008_add_turn_detection_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add workspace_id to call_records and user_integrations, create phone_numbers table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Add workspace_id to call_records if table exists
    if "call_records" in existing_tables:
        existing_columns = [c["name"] for c in inspector.get_columns("call_records")]
        if "workspace_id" not in existing_columns:
            op.add_column(
                "call_records",
                sa.Column(
                    "workspace_id",
                    sa.Uuid(as_uuid=True),
                    nullable=True,
                    comment="Workspace this call belongs to",
                ),
            )
            op.create_index("ix_call_records_workspace_id", "call_records", ["workspace_id"])
            op.create_foreign_key(
                "fk_call_records_workspace_id",
                "call_records",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # Add workspace_id to user_integrations if table exists
    if "user_integrations" in existing_tables:
        existing_columns = [c["name"] for c in inspector.get_columns("user_integrations")]
        if "workspace_id" not in existing_columns:
            op.add_column(
                "user_integrations",
                sa.Column(
                    "workspace_id",
                    sa.Uuid(as_uuid=True),
                    nullable=True,
                    comment="Workspace this integration belongs to (null = user-level)",
                ),
            )
            op.create_index("ix_user_integrations_workspace_id", "user_integrations", ["workspace_id"])
            op.create_foreign_key(
                "fk_user_integrations_workspace_id",
                "user_integrations",
                "workspaces",
                ["workspace_id"],
                ["id"],
                ondelete="CASCADE",
            )

    # Create phone_numbers table if it doesn't exist
    if "phone_numbers" not in existing_tables:
        op.create_table(
            "phone_numbers",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=False, index=True, comment="Owner user ID"),
            sa.Column(
                "workspace_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
                index=True,
                comment="Workspace this phone number belongs to",
            ),
            sa.Column(
                "phone_number",
                sa.String(50),
                nullable=False,
                index=True,
                comment="E.164 formatted phone number",
            ),
            sa.Column(
                "friendly_name",
                sa.String(200),
                nullable=True,
                comment="Human-friendly name for the number",
            ),
            sa.Column(
                "provider",
                sa.String(50),
                nullable=False,
                server_default="telnyx",
                comment="Telephony provider: telnyx or twilio",
            ),
            sa.Column(
                "provider_id",
                sa.String(255),
                nullable=False,
                index=True,
                comment="Provider's ID for this phone number",
            ),
            sa.Column(
                "can_receive_calls",
                sa.Boolean(),
                nullable=False,
                server_default="true",
                comment="Can receive inbound calls",
            ),
            sa.Column(
                "can_make_calls",
                sa.Boolean(),
                nullable=False,
                server_default="true",
                comment="Can make outbound calls",
            ),
            sa.Column(
                "can_receive_sms",
                sa.Boolean(),
                nullable=False,
                server_default="false",
                comment="Can receive SMS",
            ),
            sa.Column(
                "can_send_sms",
                sa.Boolean(),
                nullable=False,
                server_default="false",
                comment="Can send SMS",
            ),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="active",
                comment="Phone number status",
            ),
            sa.Column(
                "assigned_agent_id",
                sa.Uuid(as_uuid=True),
                nullable=True,
                index=True,
                comment="Agent currently assigned to this number",
            ),
            sa.Column("notes", sa.Text(), nullable=True, comment="Additional notes about this phone number"),
            sa.Column(
                "purchased_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="When the number was purchased",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
                onupdate=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["workspace_id"],
                ["workspaces.id"],
                name="fk_phone_numbers_workspace_id",
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["assigned_agent_id"],
                ["agents.id"],
                name="fk_phone_numbers_assigned_agent_id",
                ondelete="SET NULL",
            ),
            sa.UniqueConstraint("user_id", "phone_number", name="uq_user_phone_number"),
        )

    # Migrate existing call_records to set workspace_id from contact's workspace
    # This ensures existing calls are associated with the correct workspace
    if "call_records" in existing_tables and "contacts" in existing_tables:
        op.execute("""
            UPDATE call_records cr
            SET workspace_id = c.workspace_id
            FROM contacts c
            WHERE cr.contact_id = c.id
            AND c.workspace_id IS NOT NULL
            AND cr.workspace_id IS NULL
        """)


def downgrade() -> None:
    """Remove workspace associations and phone_numbers table."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Drop phone_numbers table if exists
    if "phone_numbers" in existing_tables:
        op.drop_table("phone_numbers")

    # Remove workspace_id from user_integrations if table exists
    if "user_integrations" in existing_tables:
        existing_columns = [c["name"] for c in inspector.get_columns("user_integrations")]
        if "workspace_id" in existing_columns:
            op.drop_constraint("fk_user_integrations_workspace_id", "user_integrations", type_="foreignkey")
            op.drop_index("ix_user_integrations_workspace_id", "user_integrations")
            op.drop_column("user_integrations", "workspace_id")

    # Remove workspace_id from call_records if table exists
    if "call_records" in existing_tables:
        existing_columns = [c["name"] for c in inspector.get_columns("call_records")]
        if "workspace_id" in existing_columns:
            op.drop_constraint("fk_call_records_workspace_id", "call_records", type_="foreignkey")
            op.drop_index("ix_call_records_workspace_id", "call_records")
            op.drop_column("call_records", "workspace_id")
