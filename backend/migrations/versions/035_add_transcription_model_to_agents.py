"""Add transcription_model to agents table.

Revision ID: 035_add_transcription_model_to_agents
Revises: 034_add_category_trees
Create Date: 2026-03-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "035_add_transcription_model"
down_revision: str | Sequence[str] | None = "034_add_category_trees"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add transcription_model column to agents table."""
    op.add_column(
        "agents",
        sa.Column(
            "transcription_model",
            sa.String(50),
            nullable=False,
            server_default="whisper-1",
            comment="STT transcription model for OpenAI Realtime (whisper-1, gpt-4o-transcribe, gpt-4o-mini-transcribe)",
        ),
    )


def downgrade() -> None:
    """Remove transcription_model column from agents table."""
    op.drop_column("agents", "transcription_model")
