"""Fix lookup records FTS to use 'simple' dictionary for multilingual support.

The previous trigger used to_tsvector('english', ...) which mangles non-English
content (Swedish, etc.) through English stemming rules. 'simple' just lowercases
without stemming, making FTS work correctly for any language.

Revision ID: 036_fix_lookup_fts_language
Revises: 035_add_transcription_model
Create Date: 2026-03-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "036_fix_lookup_fts_language"
down_revision: str | Sequence[str] | None = "035_add_transcription_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace English FTS trigger with language-agnostic 'simple' config and rebuild vectors."""
    # Drop old English trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_lookup_records_search_vector ON lookup_records")
    op.execute("DROP FUNCTION IF EXISTS update_lookup_search_vector()")

    # Create new trigger using 'simple' (language-agnostic: lowercase only, no stemming)
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

    op.execute("""
        CREATE TRIGGER trg_lookup_records_search_vector
        BEFORE INSERT OR UPDATE ON lookup_records
        FOR EACH ROW EXECUTE FUNCTION update_lookup_search_vector();
    """)

    # Rebuild all existing search vectors with the new 'simple' config
    op.execute("""
        UPDATE lookup_records
        SET search_vector = to_tsvector('simple',
            coalesce(title, '') || ' ' || coalesce(data::text, '')
        );
    """)


def downgrade() -> None:
    """Restore English FTS trigger."""
    op.execute("DROP TRIGGER IF EXISTS trg_lookup_records_search_vector ON lookup_records")
    op.execute("DROP FUNCTION IF EXISTS update_lookup_search_vector()")

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
        CREATE TRIGGER trg_lookup_records_search_vector
        BEFORE INSERT OR UPDATE ON lookup_records
        FOR EACH ROW EXECUTE FUNCTION update_lookup_search_vector();
    """)

    op.execute("""
        UPDATE lookup_records
        SET search_vector = to_tsvector('english',
            coalesce(title, '') || ' ' || coalesce(data::text, '')
        );
    """)
