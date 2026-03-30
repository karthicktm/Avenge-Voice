"""Add google_api_key to user_settings table.

Revision ID: 039_add_google_api_key
Revises: 038_add_trgm_fuzzy_matching
Create Date: 2026-03-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "039_add_google_api_key"
down_revision: str | Sequence[str] | None = "038_add_trgm_fuzzy_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_settings",
        sa.Column("google_api_key", sa.Text, nullable=True, comment="Google API key for Gemini Live"),
    )


def downgrade() -> None:
    op.drop_column("user_settings", "google_api_key")
