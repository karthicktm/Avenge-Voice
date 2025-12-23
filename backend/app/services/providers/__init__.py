"""Provider abstractions for RAG system.

This package contains abstract base classes and implementations for:
- Embedding providers (OpenAI, sentence-transformers, etc.)
- Vector store providers (pgvector, Pinecone, Weaviate, etc.)
- File storage providers (PostgreSQL BYTEA, S3, Supabase, etc.)
"""

from app.services.providers.embedding_provider import EmbeddingProvider
from app.services.providers.file_storage_provider import FileStorageProvider
from app.services.providers.vector_store_provider import SearchResult, VectorRecord, VectorStoreProvider

__all__ = [
    "EmbeddingProvider",
    "FileStorageProvider",
    "VectorStoreProvider",
    "VectorRecord",
    "SearchResult",
]
