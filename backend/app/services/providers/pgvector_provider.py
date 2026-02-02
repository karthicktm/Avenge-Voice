"""PostgreSQL pgvector provider for vector storage and similarity search."""

import uuid
from typing import Any

import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk

logger = structlog.get_logger()


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

    async def similarity_search(
        self,
        agent_id: uuid.UUID,
        query_embedding: list[float],
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Search for similar chunks using cosine similarity.

        Args:
            agent_id: Agent UUID to scope the search
            query_embedding: Query embedding vector
            top_k: Number of results to return

        Returns:
            List of matching chunks with similarity scores
        """
        try:
            # Use raw SQL for pgvector similarity search with cosine distance
            # <=> is the cosine distance operator (1 - cosine_similarity)
            query = text(
                """
                SELECT
                    dc.id,
                    dc.document_id,
                    dc.chunk_index,
                    dc.content_text,
                    d.filename,
                    1 - (dc.embedding <=> :query_embedding) as similarity
                FROM document_chunks dc
                JOIN documents d ON dc.document_id = d.id
                WHERE d.agent_id = :agent_id
                  AND d.status = 'ready'
                ORDER BY dc.embedding <=> :query_embedding
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
                    "content": row.content_text,
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
            )
            return results
        except Exception:
            self.logger.exception(
                "similarity_search_failed",
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
