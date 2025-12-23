"""PostgreSQL pgvector provider implementation."""

import uuid
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import DocumentChunk
from app.services.providers.vector_store_provider import SearchResult, VectorRecord, VectorStoreProvider


class PgVectorProvider(VectorStoreProvider):
    """PostgreSQL pgvector implementation for vector storage and search.

    Uses the pgvector extension with cosine similarity for semantic search.
    Stores vectors in the document_chunks table.
    """

    def __init__(self, db: AsyncSession):
        """Initialize pgvector provider.

        Args:
            db: Async database session
        """
        self.db = db

    async def store_vectors(self, vectors: list[VectorRecord]) -> None:
        """Store vectors in PostgreSQL using DocumentChunk model.

        Args:
            vectors: List of VectorRecord objects to store

        Raises:
            Exception: If database operation fails
        """
        if not vectors:
            return

        chunks = [
            DocumentChunk(
                id=uuid.UUID(record.id),
                document_id=uuid.UUID(record.metadata["document_id"]),
                chunk_index=record.metadata["chunk_index"],
                content_text=record.text,
                embedding=record.vector,
                chunk_metadata=record.metadata,
            )
            for record in vectors
        ]

        self.db.add_all(chunks)
        await self.db.flush()

    async def search_similar(
        self,
        query_vector: list[float],
        top_k: int,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors using cosine similarity.

        Uses pgvector's <=> operator for cosine distance (lower = more similar).
        Converts distance to similarity score (1 - distance).

        Args:
            query_vector: The embedding vector to search for
            top_k: Maximum number of results
            filter_metadata: Optional filters (e.g., {"agent_id": "xxx"})

        Returns:
            List of SearchResult objects ordered by similarity (highest first)

        Raises:
            Exception: If search fails
        """
        if filter_metadata is None:
            filter_metadata = {}

        # Convert vector to string format for pgvector
        vector_str = "[" + ",".join(str(x) for x in query_vector) + "]"

        # Build query with vector similarity
        # <=> is cosine distance operator (0 = identical, 2 = opposite)
        # We convert to similarity: 1 - (distance / 2) for 0-1 range
        query_text = """
            SELECT
                dc.id,
                dc.content_text,
                dc.metadata,
                1 - (dc.embedding <=> :query_vector) as similarity
            FROM document_chunks dc
            INNER JOIN documents d ON dc.document_id = d.id
            WHERE d.agent_id = :agent_id
                AND d.status = 'ready'
            ORDER BY dc.embedding <=> :query_vector
            LIMIT :top_k
        """

        params = {
            "query_vector": vector_str,
            "agent_id": str(filter_metadata.get("agent_id", "")),
            "top_k": top_k,
        }

        result = await self.db.execute(text(query_text), params)
        rows = result.fetchall()

        return [
            SearchResult(
                id=str(row.id),
                text=row.content_text,
                metadata=row.metadata,
                score=float(row.similarity),
            )
            for row in rows
        ]

    async def delete_by_document(self, document_id: str) -> None:
        """Delete all chunks for a document.

        Args:
            document_id: UUID of the document

        Raises:
            Exception: If deletion fails
        """
        await self.db.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == uuid.UUID(document_id))
        )
        await self.db.flush()
