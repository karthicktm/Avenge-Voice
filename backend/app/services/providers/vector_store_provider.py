"""Abstract base class for vector store providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class VectorRecord:
    """Record for storing in vector database.

    Attributes:
        id: Unique identifier for this vector (typically chunk UUID)
        vector: Embedding vector as list of floats
        metadata: Additional metadata (document_id, chunk_index, filename, etc.)
        text: The actual text content this vector represents
    """

    id: str
    vector: list[float]
    metadata: dict[str, Any]
    text: str


@dataclass
class SearchResult:
    """Result from vector similarity search.

    Attributes:
        id: ID of the matching vector/chunk
        text: Text content of the matching chunk
        metadata: Metadata associated with this chunk
        score: Similarity score (0-1, higher = more similar for cosine similarity)
    """

    id: str
    text: str
    metadata: dict[str, Any]
    score: float


class VectorStoreProvider(ABC):
    """Abstract base class for vector storage providers.

    Provides a common interface for storing and searching vectors using different
    backends (pgvector, Pinecone, Weaviate, Qdrant, etc.).
    """

    @abstractmethod
    async def store_vectors(self, vectors: list[VectorRecord]) -> None:
        """Store a batch of vectors in the vector database.

        Args:
            vectors: List of VectorRecord objects to store

        Raises:
            Exception: If storage fails
        """
        pass

    @abstractmethod
    async def search_similar(
        self,
        query_vector: list[float],
        top_k: int,
        filter_metadata: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        """Search for vectors similar to the query vector.

        Args:
            query_vector: The embedding vector to search for
            top_k: Maximum number of results to return
            filter_metadata: Optional metadata filters (e.g., {"agent_id": "xxx"})

        Returns:
            List of SearchResult objects, ordered by similarity (most similar first)

        Raises:
            Exception: If search fails
        """
        pass

    @abstractmethod
    async def delete_by_document(self, document_id: str) -> None:
        """Delete all vectors associated with a document.

        Args:
            document_id: UUID of the document whose vectors should be deleted

        Raises:
            Exception: If deletion fails
        """
        pass
