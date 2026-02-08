"""Embedding provider for RAG functionality with multi-provider support."""

import httpx
import structlog
from openai import AsyncOpenAI

logger = structlog.get_logger()

# Model dimensions mapping
MODEL_DIMENSIONS = {
    # OpenAI models
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    # Voyage AI models
    "voyage-3": 1024,
    "voyage-3-lite": 512,
}


class EmbeddingProvider:
    """Provider for generating text embeddings.

    Supports multiple providers:
    - OpenAI: text-embedding-3-small, text-embedding-3-large, text-embedding-ada-002
    - Voyage AI: voyage-3, voyage-3-lite
    """

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        provider: str = "openai",
    ) -> None:
        """Initialize embedding provider.

        Args:
            api_key: API key for the provider
            model: Embedding model name
            provider: Provider name (openai or voyage)
        """
        self.api_key = api_key
        self.model = model
        self.provider = provider
        self.dimensions = MODEL_DIMENSIONS.get(model, 1536)
        self.logger = logger.bind(
            component="embedding_provider",
            model=self.model,
            provider=self.provider,
        )

        if provider == "openai":
            self.client = AsyncOpenAI(api_key=api_key)
        else:
            self.client = None  # Voyage uses HTTP API

    async def generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for a single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        embeddings = await self.generate_embeddings([text])
        return embeddings[0] if embeddings else []

    async def generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts in batch.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            if self.provider == "openai":
                return await self._generate_openai_embeddings(texts)
            if self.provider == "voyage":
                return await self._generate_voyage_embeddings(texts)
            msg = f"Unknown provider: {self.provider}"
            raise ValueError(msg)
        except Exception:
            self.logger.exception(
                "embedding_generation_failed",
                provider=self.provider,
                text_count=len(texts),
            )
            raise

    async def _generate_openai_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using OpenAI API."""
        response = await self.client.embeddings.create(
            input=texts,
            model=self.model,
        )
        embeddings = [d.embedding for d in response.data]
        self.logger.info(
            "openai_embeddings_generated",
            text_count=len(texts),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
        )
        return embeddings

    async def _generate_voyage_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings using Voyage AI API."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.voyageai.com/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "input": texts,
                    "model": self.model,
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()

        embeddings = [item["embedding"] for item in data["data"]]
        self.logger.info(
            "voyage_embeddings_generated",
            text_count=len(texts),
            embedding_dim=len(embeddings[0]) if embeddings else 0,
        )
        return embeddings
