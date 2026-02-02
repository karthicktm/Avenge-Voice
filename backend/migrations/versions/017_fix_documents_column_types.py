"""Fix documents table column types to match model

Revision ID: 017_fix_documents_column_types
Revises: 016_add_processed_at
Create Date: 2026-02-02

Fixes column type mismatches between Document model and database:
- filename: VARCHAR(255) -> VARCHAR(500)
- file_type: VARCHAR(10) -> VARCHAR(50)
- status: VARCHAR(20) -> VARCHAR(50)
- content: BYTEA -> TEXT
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "017_fix_documents_column_types"
down_revision: Union[str, Sequence[str], None] = "016_add_processed_at"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alter filename column from VARCHAR(255) to VARCHAR(500)
    op.alter_column(
        'documents',
        'filename',
        existing_type=sa.String(255),
        type_=sa.String(500),
        existing_nullable=False,
    )

    # Alter file_type column from VARCHAR(10) to VARCHAR(50)
    op.alter_column(
        'documents',
        'file_type',
        existing_type=sa.String(10),
        type_=sa.String(50),
        existing_nullable=False,
    )

    # Alter status column from VARCHAR(20) to VARCHAR(50)
    op.alter_column(
        'documents',
        'status',
        existing_type=sa.String(20),
        type_=sa.String(50),
        existing_nullable=False,
    )

    # Alter content column from BYTEA to TEXT
    # Using USING clause to convert existing binary data to text
    op.execute(
        "ALTER TABLE documents ALTER COLUMN content TYPE TEXT USING content::text"
    )


def downgrade() -> None:
    # Revert content to BYTEA
    op.execute(
        "ALTER TABLE documents ALTER COLUMN content TYPE BYTEA USING content::bytea"
    )

    # Revert status column
    op.alter_column(
        'documents',
        'status',
        existing_type=sa.String(50),
        type_=sa.String(20),
        existing_nullable=False,
    )

    # Revert file_type column
    op.alter_column(
        'documents',
        'file_type',
        existing_type=sa.String(50),
        type_=sa.String(10),
        existing_nullable=False,
    )

    # Revert filename column
    op.alter_column(
        'documents',
        'filename',
        existing_type=sa.String(500),
        type_=sa.String(255),
        existing_nullable=False,
    )
