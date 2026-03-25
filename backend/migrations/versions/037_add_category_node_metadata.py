"""Add metadata JSONB column to category_trees and update search vector trigger.

Revision ID: 037_add_category_node_metadata
Revises: 036_fix_lookup_fts_language
Create Date: 2026-03-25

Adds a nullable JSONB `metadata` column to category_trees for per-leaf metadata
(urgency_level, self_resolution, can_report_fault, info_to_collect, example_query, etc.).

Also updates the search_vector trigger to include metadata->>'example_query' so
FTS matching benefits from stored example caller phrasings.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "037_add_category_node_metadata"
down_revision: str = "036_fix_lookup_fts_language"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "category_trees",
        sa.Column(
            "metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            comment="Arbitrary per-leaf metadata from import (urgency_level, example_query, etc.)",
        ),
    )

    # Update the trigger function to also index metadata->>'example_query' so
    # FTS lookups benefit from stored example caller phrasings.
    op.execute("""
        CREATE OR REPLACE FUNCTION update_category_tree_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('simple',
                    coalesce(NEW.label, '') || ' ' ||
                    coalesce(NEW.code, '') || ' ' ||
                    coalesce(NEW.metadata->>'example_query', '')
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Backfill existing rows — the trigger only fires on future writes.
    op.execute("""
        UPDATE category_trees
        SET search_vector =
            to_tsvector('simple',
                coalesce(label, '') || ' ' ||
                coalesce(code, '') || ' ' ||
                coalesce(metadata->>'example_query', '')
            );
    """)


def downgrade() -> None:
    # Restore trigger without example_query
    op.execute("""
        CREATE OR REPLACE FUNCTION update_category_tree_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('simple',
                    coalesce(NEW.label, '') || ' ' || coalesce(NEW.code, '')
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.drop_column("category_trees", "metadata")
