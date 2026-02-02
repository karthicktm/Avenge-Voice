"""Add processed_at column to documents table

Revision ID: 016_add_processed_at
Revises: 015_add_rag_support
Create Date: 2026-02-02

Adds processed_at timestamp column to track when document processing completed.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TIMESTAMP


# revision identifiers, used by Alembic.
revision: str = "016_add_processed_at"
down_revision: Union[str, Sequence[str], None] = "d3d5a98635d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'documents',
        sa.Column(
            'processed_at',
            TIMESTAMP(timezone=True),
            nullable=True,
            comment='When document processing completed'
        )
    )


def downgrade() -> None:
    op.drop_column('documents', 'processed_at')
