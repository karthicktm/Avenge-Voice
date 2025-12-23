"""OpenAI embedding provider implementation."""

import asyncio
from typing import Any

from openai import AsyncOpenAI

from app.services.providers.embedding_provider import EmbeddingProvider


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI embedding provider using text-embedding-3 models.

    Supports:
    - text-embedding-3-small (1536 dimensions, $0.02/1M tokens)
    - text-embedding-3-large (3072 dimensions, $0.13/1M tokens)
    """

    # Model dimension mapping
    DIMENSIONS_MAP = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
    }

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        """Initialize OpenAI embedding provider.

        Args:
            api_key: OpenAI API key
            model: Model to use (default: text-embedding-3-small)

        Raises:
            ValueError: If model is not supported
        """
        if model not in self.DIMENSIONS_MAP:
            raise ValueError(
                f"Unsupported model: {model}. "
                f"Supported models: {list(self.DIMENSIONS_MAP.keys())}"
            )

        self.model = model
        self.client = AsyncOpenAI(api_key=api_key)

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API.

        Processes texts in batches to respect API limits (max 2048 texts per request).
        Uses asyncio.gather for parallel processing of batches.

        Args:
            texts: List of text strings to embed

        Returns:
            List of embedding vectors

        Raises:
            Exception: If API call fails
        """
        if not texts:
            return []

        # OpenAI supports up to 2048 texts per request
        batch_size = 2048
        all_embeddings: list[list[float]] = []

        # Process in batches
        tasks = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            tasks.append(self._embed_batch(batch))

        # Execute batches in parallel
        batch_results = await asyncio.gather(*tasks)

        # Flatten results
        for batch_embeddings in batch_results:
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed a single batch of texts.

        Args:
            texts: Batch of texts (max 2048)

        Returns:
            List of embeddings for this batch

        Raises:
            Exception: If API call fails
        """
        response = await self.client.embeddings.create(model=self.model, input=texts)

        # Extract embeddings in order
        embeddings = [item.embedding for item in response.data]
        return embeddings

    def get_dimensions(self) -> int:
        """Get embedding dimensions for the current model.

        Returns:
            Number of dimensions (1536 for small, 3072 for large)
        """
        return self.DIMENSIONS_MAP[self.model]

    def get_model_name(self) -> str:
        """Get the model identifier.

        Returns:
            Model name (e.g., "text-embedding-3-small")
        """
        return self.model
