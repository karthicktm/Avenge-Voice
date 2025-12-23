"""Add privacy and compliance tables for GDPR/CCPA.

Revision ID: 010_privacy_compliance
Revises: 009_workspace_to_tables
Create Date: 2024-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "010_privacy_compliance"
down_revision: str | None = "009_workspace_to_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create privacy_settings and consent_records tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create privacy_settings table
    if "privacy_settings" not in existing_tables:
        op.create_table(
            "privacy_settings",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                nullable=False,
                unique=True,
                index=True,
            ),
            # GDPR Settings
            sa.Column("privacy_policy_url", sa.Text(), nullable=True),
            sa.Column("privacy_policy_accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "data_retention_days",
                sa.Integer(),
                nullable=False,
                server_default="365",
            ),
            # DPA tracking
            sa.Column(
                "openai_dpa_signed",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column("openai_dpa_signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "telnyx_dpa_signed",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column("telnyx_dpa_signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "deepgram_dpa_signed",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column("deepgram_dpa_signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "elevenlabs_dpa_signed",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column("elevenlabs_dpa_signed_at", sa.DateTime(timezone=True), nullable=True),
            # CCPA Settings
            sa.Column(
                "ccpa_opt_out",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column("ccpa_opt_out_at", sa.DateTime(timezone=True), nullable=True),
            # Data export tracking
            sa.Column("last_data_export_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_data_export_requested_at", sa.DateTime(timezone=True), nullable=True),
            # Timestamps
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
                ["user_id"],
                ["users.id"],
                name="fk_privacy_settings_user_id",
                ondelete="CASCADE",
            ),
        )

    # Create consent_records table
    if "consent_records" not in existing_tables:
        op.create_table(
            "consent_records",
            sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
            sa.Column(
                "user_id",
                sa.Integer(),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "consent_type",
                sa.String(50),
                nullable=False,
                index=True,
            ),
            sa.Column("granted", sa.Boolean(), nullable=False),
            sa.Column("ip_address", sa.String(45), nullable=True),
            sa.Column("user_agent", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.ForeignKeyConstraint(
                ["user_id"],
                ["users.id"],
                name="fk_consent_records_user_id",
                ondelete="CASCADE",
            ),
        )


def downgrade() -> None:
    """Remove privacy_settings and consent_records tables."""
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing_tables = inspector.get_table_names()

    if "consent_records" in existing_tables:
        op.drop_table("consent_records")

    if "privacy_settings" in existing_tables:
        op.drop_table("privacy_settings")
