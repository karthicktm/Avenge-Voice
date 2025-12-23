"""Embedding service with provider abstraction."""

from typing import Any

from app.core.config import settings
from app.services.providers.embedding_provider import EmbeddingProvider
from app.services.providers.openai_embedding_provider import OpenAIEmbeddingProvider


class EmbeddingService:
    """Service for generating embeddings with provider abstraction.

    Provides a unified interface for embedding generation while supporting
    multiple providers (OpenAI, sentence-transformers, etc.).
    """

    def __init__(self, provider: EmbeddingProvider | None = None, api_key: str | None = None):
        """Initialize embedding service.

        Args:
            provider: Embedding provider to use (default: OpenAI)
            api_key: API key for the provider (default: from settings)
        """
        if provider is None:
            # Default to OpenAI with settings
            embedding_model = getattr(settings, "RAG_EMBEDDING_MODEL", "text-embedding-3-small")
            openai_key = api_key or settings.OPENAI_API_KEY
            provider = OpenAIEmbeddingProvider(api_key=openai_key, model=embedding_model)

        self.provider = provider

    async def embed_chunks(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for document chunks.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors (one per input text)

        Raises:
            Exception: If embedding generation fails
        """
        return await self.provider.generate_embeddings(texts)

    async def embed_query(self, query: str) -> list[float]:
        """Generate embedding for a single query.

        Args:
            query: Query text to embed

        Returns:
            Single embedding vector

        Raises:
            Exception: If embedding generation fails
        """
        embeddings = await self.provider.generate_embeddings([query])
        return embeddings[0]

    def get_embedding_metadata(self) -> dict[str, Any]:
        """Get metadata about the embedding model.

        Returns:
            Dictionary with model and dimensions information
        """
        return {
            "model": self.provider.get_model_name(),
            "dimensions": self.provider.get_dimensions(),
        }
