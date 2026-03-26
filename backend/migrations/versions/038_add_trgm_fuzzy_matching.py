"""Enable pg_trgm extension and add GiST trigram indexes for fuzzy ASR matching.

Revision ID: 038_add_trgm_fuzzy_matching
Revises: 037_add_category_node_metadata
Create Date: 2026-03-26

Adds pg_trgm extension and GiST trigram indexes on:
  - lookup_records.title       (for ASR 1-char edit distance recovery)
  - category_trees.label       (for spelling variation in category labels)

GiST is chosen over GIN because it supports ORDER BY similarity() DESC
which is required for ranking fallback results. GIN only supports the
% threshold operator and cannot be used for ordered distance queries.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "038_add_trgm_fuzzy_matching"
down_revision: str = "037_add_category_node_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable extension — idempotent, safe to run repeatedly
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # GiST index on lookup_records.title for similarity() queries + ORDER BY
    op.execute(
        """
        CREATE INDEX ix_lookup_records_title_trgm
        ON lookup_records
        USING gist (title gist_trgm_ops)
        """
    )

    # GiST index on category_trees.label for similarity() queries + ORDER BY
    op.execute(
        """
        CREATE INDEX ix_category_trees_label_trgm
        ON category_trees
        USING gist (label gist_trgm_ops)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_category_trees_label_trgm")
    op.execute("DROP INDEX IF EXISTS ix_lookup_records_title_trgm")
    # Note: do not drop pg_trgm — other queries may depend on it
