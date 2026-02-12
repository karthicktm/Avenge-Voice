"""Add script and campaign_greeting to campaigns.

Revision ID: 031_add_script_and_greeting_to_campaigns
Revises: 030_add_fulltext_search
Create Date: 2026-02-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "031_add_script_and_greeting_to_campaigns"
down_revision: str = "030_add_fulltext_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column(
            "script",
            sa.Text(),
            nullable=True,
            comment="Campaign objective / talking points for the AI agent",
        ),
    )
    op.add_column(
        "campaigns",
        sa.Column(
            "campaign_greeting",
            sa.Text(),
            nullable=True,
            comment="Outbound greeting (overrides agent default greeting)",
        ),
    )


def downgrade() -> None:
    op.drop_column("campaigns", "campaign_greeting")
    op.drop_column("campaigns", "script")
