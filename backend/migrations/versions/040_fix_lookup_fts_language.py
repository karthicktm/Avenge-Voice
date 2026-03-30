"""Fix lookup FTS trigger to use 'simple' dictionary for multi-language support.

Revision ID: 040_fix_lookup_fts_language
Revises: 039_add_google_api_key
Create Date: 2026-03-30

The previous trigger used 'english' dictionary which mangles non-English content
(Swedish property names, etc.) via stemming. The search queries use 'simple'
(lowercase only), so the dictionaries must match for FTS to work correctly.
This migration rebuilds the trigger and all search vectors.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "040_fix_lookup_fts_language"
down_revision: str | Sequence[str] | None = "039_add_google_api_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Replace trigger function to use 'simple' (no stemming, just lowercase)
    op.execute("""
        CREATE OR REPLACE FUNCTION update_lookup_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('simple',
                    coalesce(NEW.title, '') || ' ' || coalesce(NEW.data::text, '')
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Rebuild all existing search vectors with the new 'simple' dictionary
    op.execute("""
        UPDATE lookup_records
        SET search_vector = to_tsvector('simple',
            coalesce(title, '') || ' ' || coalesce(data::text, '')
        );
    """)


def downgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION update_lookup_search_vector()
        RETURNS trigger AS $$
        BEGIN
            NEW.search_vector :=
                to_tsvector('english',
                    coalesce(NEW.title, '') || ' ' || coalesce(NEW.data::text, '')
                );
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        UPDATE lookup_records
        SET search_vector = to_tsvector('english',
            coalesce(title, '') || ' ' || coalesce(data::text, '')
        );
    """)
