"""PostgreSQL pgvector provider for vector storage and similarity search."""

# ruff: noqa: S608 - embedding_col is controlled internally, not user input

import uuid
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk

logger = structlog.get_logger()

# Dimension for large embedding models (text-embedding-3-large)
LARGE_EMBEDDING_DIMENSIONS = 3072


class PgVectorProvider:
    """Provider for vector storage and similarity search using pgvector.

    Handles:
    - Storing document chunk embeddings
    - Similarity search using cosine distance
    - Retrieving relevant chunks for RAG queries
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize with database session.

        Args:
            db: Async database session
        """
        self.db = db
        self.logger = logger.bind(component="pgvector_provider")

    async def store_chunks(
        self,
        document_id: uuid.UUID,
        chunks: list[tuple[int, str, list[float]]],
    ) -> int:
        """Store document chunks with embeddings.

        Args:
            document_id: UUID of the parent document
            chunks: List of (chunk_index, content_text, embedding) tuples

        Returns:
            Number of chunks stored
        """
        if not chunks:
            return 0

        try:
            for chunk_index, content_text, embedding in chunks:
                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_index,
                    content_text=content_text,
                    embedding=embedding,
                )
                self.db.add(chunk)

            await self.db.flush()

            self.logger.info(
                "chunks_stored",
                document_id=str(document_id),
                chunk_count=len(chunks),
            )
            return len(chunks)
        except Exception:
            self.logger.exception(
                "chunk_storage_failed",
                document_id=str(document_id),
                chunk_count=len(chunks),
            )
            raise

    async def store_chunks_v2(
        self,
        document_id: uuid.UUID,
        chunks: list[dict[str, Any]],
    ) -> int:
        """Store document chunks with translation and dual embedding support.

        Args:
            document_id: UUID of the parent document
            chunks: List of chunk dictionaries with keys:
                - index: Chunk position in document
                - original_text: Original text content
                - translated_text: English translation (or None if same as original)
                - embedding: Embedding vector
                - source_language: Source language code
                - translation_status: Status of translation
                - use_large: Whether to use embedding_large column

        Returns:
            Number of chunks stored
        """
        if not chunks:
            return 0

        try:
            for chunk_data in chunks:
                use_large = chunk_data.get("use_large", False)

                chunk = DocumentChunk(
                    document_id=document_id,
                    chunk_index=chunk_data["index"],
                    content_text=chunk_data["original_text"],
                    translated_text=chunk_data.get("translated_text"),
                    source_language=chunk_data.get("source_language"),
                    translation_status=chunk_data.get("translation_status", "not_needed"),
                    # Use appropriate embedding column based on model dimensions
                    embedding=chunk_data["embedding"] if not use_large else None,
                    embedding_large=chunk_data["embedding"] if use_large else None,
                )
                self.db.add(chunk)

            await self.db.flush()

            self.logger.info(
                "chunks_stored_v2",
                document_id=str(document_id),
                chunk_count=len(chunks),
                use_large=chunks[0].get("use_large", False) if chunks else False,
            )
            return len(chunks)
        except Exception:
            self.logger.exception(
                "chunk_storage_v2_failed",
                document_id=str(document_id),
                chunk_count=len(chunks),
            )
            raise

    async def similarity_search(
        self,
        agent_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Search for similar chunks using cosine similarity.

        Supports both embedding columns (1536 and 3072 dimensions).
        Automatically selects the appropriate column based on query dimension.
        Always returns original content_text (not translated) in results.

        Args:
            agent_id: Agent UUID to scope the search
            query_embedding: Query embedding vector
            top_k: Number of results to return

        Returns:
            List of matching chunks with similarity scores
        """
        try:
            # Determine which embedding column to use based on query dimension
            embedding_dim = len(query_embedding)
            use_large = embedding_dim == LARGE_EMBEDDING_DIMENSIONS
            embedding_col = "embedding_large" if use_large else "embedding"

            # Use raw SQL for pgvector similarity search with cosine distance
            # <=> is the cosine distance operator (1 - cosine_similarity)
            # Always return content_text (original) not translated_text
            query = text(
                f"""
                SELECT
                    dc.id,
                    dc.document_id,
                    dc.chunk_index,
                    dc.content_text,
                    dc.source_language,
                    d.filename,
                    1 - (dc.{embedding_col} <=> :query_embedding) as similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.agent_id = :agent_id
                  AND d.status = 'ready'
                  AND dc.{embedding_col} IS NOT NULL
                ORDER BY dc.{embedding_col} <=> :query_embedding
                LIMIT :top_k
                """
            )

            result = await self.db.execute(
                query,
                {
                    "agent_id": agent_id,
                    "query_embedding": str(query_embedding),
                    "top_k": top_k,
                },
            )
            rows = result.fetchall()

            results = [
                {
                    "chunk_id": str(row.id),
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "content": row.content_text,  # Always return original content
                    "source_language": row.source_language,
                    "filename": row.filename,
                    "similarity": float(row.similarity),
                }
                for row in rows
            ]

            self.logger.info(
                "similarity_search_completed",
                agent_id=str(agent_id),
                top_k=top_k,
                results_found=len(results),
                embedding_dimensions=embedding_dim,
            )
            return results
        except Exception:
            self.logger.exception(
                "similarity_search_failed",
                agent_id=str(agent_id),
                top_k=top_k,
            )
            raise

    @staticmethod
    def _build_or_tsquery(query: str) -> str:
        """Build an OR-based tsquery string from a raw query.

        Splits on whitespace, keeps only alphanumeric tokens, and joins
        with ' | ' so any individual term can match. This is critical
        because voice agents often rephrase queries (e.g. "produkt 4802")
        and AND semantics would require every word to appear in the chunk.

        Args:
            query: Raw search query text

        Returns:
            OR-joined tsquery string (e.g. "produkt | 4802")
        """
        import re

        tokens = re.findall(r"\w+", query, re.UNICODE)
        if not tokens:
            return query
        return " | ".join(tokens)

    async def keyword_search(
        self,
        agent_id: uuid.UUID,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Search for chunks using PostgreSQL full-text keyword search.

        Uses 'simple' dictionary for language-agnostic matching that works
        well for product codes, SKUs, and multilingual content.
        Terms are joined with OR so any word in the query can match.

        Args:
            agent_id: Agent UUID to scope the search
            query: Raw search query text
            top_k: Number of results to return

        Returns:
            List of matching chunks with ts_rank scores
        """
        try:
            or_query = self._build_or_tsquery(query)

            sql = text(
                """
                SELECT
                    dc.id,
                    dc.document_id,
                    dc.chunk_index,
                    dc.content_text,
                    dc.source_language,
                    d.filename,
                    ts_rank(dc.content_tsv, to_tsquery('simple', :query)) as similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.agent_id = :agent_id
                  AND d.status = 'ready'
                  AND dc.content_tsv @@ to_tsquery('simple', :query)
                ORDER BY similarity DESC
                LIMIT :top_k
                """
            )

            result = await self.db.execute(
                sql,
                {"agent_id": agent_id, "query": or_query, "top_k": top_k},
            )
            rows = result.fetchall()

            results = [
                {
                    "chunk_id": str(row.id),
                    "document_id": str(row.document_id),
                    "chunk_index": row.chunk_index,
                    "content": row.content_text,
                    "source_language": row.source_language,
                    "filename": row.filename,
                    "similarity": float(row.similarity),
                }
                for row in rows
            ]

            self.logger.info(
                "keyword_search_completed",
                agent_id=str(agent_id),
                query=query,
                top_k=top_k,
                results_found=len(results),
            )
            return results
        except Exception:
            self.logger.exception(
                "keyword_search_failed",
                agent_id=str(agent_id),
                top_k=top_k,
            )
            raise

    async def delete_document_chunks(self, document_id: uuid.UUID) -> int:
        """Delete all chunks for a document.

        Args:
            document_id: Document UUID

        Returns:
            Number of chunks deleted
        """
        try:
            result = await self.db.execute(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            )
            chunks = list(result.scalars().all())
            count = len(chunks)

            for chunk in chunks:
                await self.db.delete(chunk)

            await self.db.flush()

            self.logger.info(
                "chunks_deleted",
                document_id=str(document_id),
                chunk_count=count,
            )
            return count
        except Exception:
            self.logger.exception(
                "chunk_deletion_failed",
                document_id=str(document_id),
            )
            raise

    async def get_document_chunk_count(self, agent_id: uuid.UUID) -> int:
        """Get total chunk count for an agent.

        Args:
            agent_id: Agent UUID

        Returns:
            Total number of chunks across all agent's documents
        """
        query = text(
            """
            SELECT COUNT(*) as count
            FROM document_chunks dc
            JOIN documents d ON dc.document_id = d.id
            WHERE d.agent_id = :agent_id
            """
        )
        result = await self.db.execute(query, {"agent_id": agent_id})
        row = result.fetchone()
        if row is None:
            return 0
        count_val = row[0]  # Access by index to avoid Callable type issue
        return int(count_val) if count_val is not None else 0
