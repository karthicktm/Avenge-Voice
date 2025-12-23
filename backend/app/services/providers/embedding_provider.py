"""Abstract base class for embedding providers."""

from abc import ABC, abstractmethod


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers.

    Provides a common interface for generating text embeddings using different
    models and services (OpenAI, sentence-transformers, etc.).
    """

    @abstractmethod
    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of text strings.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors, where each vector is a list of floats.
            The length of the outer list equals len(texts).
            The length of each inner list equals get_dimensions().

        Raises:
            Exception: If embedding generation fails
        """
        pass

    @abstractmethod
    def get_dimensions(self) -> int:
        """Get the dimensionality of embeddings produced by this provider.

        Returns:
            Number of dimensions in each embedding vector
        """
        pass

    @abstractmethod
    def get_model_name(self) -> str:
        """Get the identifier/name of the embedding model.

        Returns:
            Model identifier (e.g., "text-embedding-3-small")
        """
        pass
