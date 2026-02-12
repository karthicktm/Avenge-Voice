"""RAG (Retrieval-Augmented Generation) service for knowledge base functionality."""

import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.services.document_processor import DocumentProcessor
from app.services.providers.embedding_provider import EmbeddingProvider
from app.services.providers.pgvector_provider import PgVectorProvider
from app.services.translation_service import TranslationService

logger = structlog.get_logger()


class RAGService:
    """Service for RAG operations: document processing, embedding, and search.

    Orchestrates:
    - Document upload and processing
    - Text extraction and chunking
    - Embedding generation
    - Semantic search
    """

    def __init__(
        self,
        db: AsyncSession,
        embedding_config: dict[str, str] | None = None,
    ) -> None:
        """Initialize RAG service.

        Args:
            db: Async database session
            embedding_config: Embedding configuration with keys:
                - api_key: API key for embedding provider
                - embedding_model: Model name (e.g., text-embedding-3-small)
                - embedding_provider: Provider name (openai or voyage)
        """
        self.db = db
        self.document_processor = DocumentProcessor()
        self._embedding_config = embedding_config
        self._embedding_provider: EmbeddingProvider | None = None
        self.vector_provider = PgVectorProvider(db)
        self.logger = logger.bind(component="rag_service")

    @property
    def embedding_provider(self) -> EmbeddingProvider:
        """Lazy-load embedding provider using configured credentials."""
        if self._embedding_provider is None:
            if not self._embedding_config:
                msg = "Knowledge Base integration not configured. Please add your API credentials in the Integrations page."
                raise ValueError(msg)

            api_key = self._embedding_config.get("api_key")
            if not api_key:
                msg = "API key not configured for Knowledge Base. Please add it in the Integrations page."
                raise ValueError(msg)

            model = self._embedding_config.get("embedding_model", "text-embedding-3-small")
            provider = self._embedding_config.get("embedding_provider", "openai")

            self._embedding_provider = EmbeddingProvider(
                api_key=api_key,
                model=model,
                provider=provider,
            )
        return self._embedding_provider

    async def upload_document(
        self,
        agent_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> Document:
        """Upload and create a document record.

        Args:
            agent_id: Agent UUID
            filename: Original filename
            content: File content bytes

        Returns:
            Created Document record (status: pending)
        """
        # Validate file type
        file_type = self.document_processor.get_file_type(filename)
        if not file_type:
            msg = f"Unsupported file type: {filename}"
            raise ValueError(msg)

        # Check file size
        if len(content) > settings.RAG_MAX_FILE_SIZE:
            msg = f"File too large: {len(content)} bytes (max {settings.RAG_MAX_FILE_SIZE})"
            raise ValueError(msg)

        # Check document count limit
        count_result = await self.db.execute(
            select(func.count(Document.id)).where(Document.agent_id == agent_id)
        )
        doc_count = count_result.scalar() or 0
        if doc_count >= settings.RAG_MAX_DOCUMENTS_PER_AGENT:
            msg = f"Document limit reached ({settings.RAG_MAX_DOCUMENTS_PER_AGENT})"
            raise ValueError(msg)

        # Create document record
        document = Document(
            agent_id=agent_id,
            filename=filename,
            file_type=file_type,
            file_size=len(content),
            status="pending",
        )
        self.db.add(document)
        await self.db.commit()
        await self.db.refresh(document)

        self.logger.info(
            "document_uploaded",
            document_id=str(document.id),
            agent_id=str(agent_id),
            filename=filename,
            file_type=file_type,
            file_size=len(content),
        )

        return document

    async def process_document(
        self,
        document_id: uuid.UUID,
        content: bytes,
    ) -> Document:
        """Process a document: extract text, chunk, translate, and generate embeddings.

        Supports cross-lingual search by:
        1. Detecting document language
        2. Translating non-English content to English (if enabled)
        3. Embedding the translated content for search
        4. Preserving original content for display

        Args:
            document_id: Document UUID
            content: File content bytes

        Returns:
            Updated Document record (status: ready or failed)
        """
        # Get document
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            msg = f"Document not found: {document_id}"
            raise ValueError(msg)

        # Update status to processing
        document.status = "processing"
        await self.db.commit()

        try:
            # Check if translation is enabled
            config = self._embedding_config or {}
            enable_translation_config = config.get("enable_translation", "false")
            translation_enabled = enable_translation_config in (True, "true", "True", "1")
            translation_model = config.get("translation_model", "gpt-4o-mini")

            # Initialize translation service if enabled
            translation_service: TranslationService | None = None
            api_key = config.get("api_key")
            if translation_enabled and api_key:
                translation_service = TranslationService(
                    api_key=api_key,
                    model=translation_model,
                )

            # Process with translation
            (
                full_text,
                original_chunks,
                translated_chunks,
                source_language,
                translation_status,
            ) = await self.document_processor.process_with_translation(
                content, document.filename, translation_service
            )

            # Generate embeddings for translated chunks (for cross-lingual search)
            # The translated chunks are used for embedding so English queries match
            embeddings = await self.embedding_provider.generate_embeddings(translated_chunks)

            # Determine which embedding column to use
            use_large = self.embedding_provider.is_large_model

            # Store chunks with embeddings and translation data
            chunk_data = [
                {
                    "index": i,
                    "original_text": orig,
                    "translated_text": trans if trans != orig else None,
                    "embedding": emb,
                    "source_language": source_language,
                    "translation_status": translation_status,
                    "use_large": use_large,
                }
                for i, (orig, trans, emb) in enumerate(
                    zip(original_chunks, translated_chunks, embeddings, strict=True)
                )
            ]
            await self.vector_provider.store_chunks_v2(document_id, chunk_data)

            # Update document status
            document.content = full_text
            document.chunk_count = len(original_chunks)
            document.status = "ready"
            document.processed_at = datetime.now(UTC)
            document.error_message = None
            document.source_language = source_language
            document.translation_enabled = translation_enabled
            document.embedding_dimensions = self.embedding_provider.dimensions

            await self.db.commit()
            await self.db.refresh(document)

            self.logger.info(
                "document_processed",
                document_id=str(document_id),
                text_length=len(full_text),
                chunk_count=len(original_chunks),
                source_language=source_language,
                translation_status=translation_status,
                embedding_dimensions=self.embedding_provider.dimensions,
            )

            return document

        except Exception as e:
            # Rollback any failed transaction before updating status
            await self.db.rollback()

            # Re-fetch document since the session was rolled back
            result = await self.db.execute(select(Document).where(Document.id == document_id))
            document = result.scalar_one_or_none()

            if document:
                # Update status to failed
                document.status = "failed"
                document.error_message = str(e)[:500]  # Truncate long error messages
                await self.db.commit()

            self.logger.exception(
                "document_processing_failed",
                document_id=str(document_id),
                error=str(e),
            )
            raise

    async def search(
        self,
        agent_id: uuid.UUID,
        query: str,
        top_k: int = 3,
    ) -> list[dict[str, Any]]:
        """Search knowledge base for relevant content.

        Automatically matches the embedding model to the document's indexed
        dimensions to prevent mismatches (e.g. documents indexed with
        text-embedding-3-large but search configured with text-embedding-3-small).

        Args:
            agent_id: Agent UUID
            query: Search query
            top_k: Number of results to return

        Returns:
            List of relevant chunks with similarity scores
        """
        self.logger.warning(
            "knowledge_base_search_started",
            agent_id=str(agent_id),
            query=query,
            top_k=top_k,
        )

        # Check what embedding dimensions the agent's documents actually use
        doc_result = await self.db.execute(
            select(Document.embedding_dimensions)
            .where(Document.agent_id == agent_id, Document.status == "ready")
            .limit(1)
        )
        doc_row = doc_result.scalar_one_or_none()

        provider = self.embedding_provider
        if doc_row and doc_row != provider.dimensions:
            # Document was indexed with a different model than currently configured.
            # Create a provider matching the document's dimensions to avoid mismatch.
            from app.services.providers.embedding_provider import MODEL_DIMENSIONS

            matching_model = next(
                (m for m, d in MODEL_DIMENSIONS.items() if d == doc_row),
                None,
            )
            if matching_model:
                self.logger.warning(
                    "embedding_dimension_mismatch_corrected",
                    configured_model=provider.model,
                    configured_dims=provider.dimensions,
                    document_dims=doc_row,
                    corrected_model=matching_model,
                )
                provider = EmbeddingProvider(
                    api_key=provider.api_key,
                    model=matching_model,
                    provider=provider.provider,
                )

        # Generate query embedding
        query_embedding = await provider.generate_embedding(query)

        # Run vector search and keyword search sequentially
        # (AsyncSession cannot safely run concurrent queries on the same connection)
        vector_results = await self.vector_provider.similarity_search(
            agent_id=agent_id,
            query_embedding=query_embedding,
            top_k=top_k,
        )

        # Keyword search with graceful fallback — if it fails, vector-only results are used
        keyword_results: list[dict[str, Any]] = []
        try:
            keyword_results = await self.vector_provider.keyword_search(
                agent_id=agent_id,
                query=query,
                top_k=top_k,
            )
        except Exception:
            self.logger.exception("keyword_search_fallback", agent_id=str(agent_id), query=query)

        self.logger.warning(
            "hybrid_search_results",
            agent_id=str(agent_id),
            query=query,
            vector_count=len(vector_results),
            keyword_count=len(keyword_results),
        )

        # Fuse results using Reciprocal Rank Fusion (RRF)
        results = self._fuse_results(vector_results, keyword_results, top_k)

        return results

    @staticmethod
    def _fuse_results(
        vector_results: list[dict[str, Any]],
        keyword_results: list[dict[str, Any]],
        top_k: int,
        k: int = 60,
    ) -> list[dict[str, Any]]:
        """Fuse vector and keyword search results using Reciprocal Rank Fusion.

        RRF score = sum(1 / (k + rank)) across result lists.
        Falls back gracefully when one list is empty.

        Args:
            vector_results: Results from vector similarity search
            keyword_results: Results from keyword full-text search
            top_k: Number of results to return
            k: RRF constant (default 60)

        Returns:
            Fused and deduplicated results sorted by RRF score
        """
        # If only one source has results, return it directly
        if not keyword_results:
            return vector_results[:top_k]
        if not vector_results:
            return keyword_results[:top_k]

        # Build score map keyed by chunk_id
        scores: dict[str, float] = {}
        chunks: dict[str, dict[str, Any]] = {}

        for rank, result in enumerate(vector_results):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            chunks[cid] = result

        for rank, result in enumerate(keyword_results):
            cid = result["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank + 1)
            if cid not in chunks:
                chunks[cid] = result

        # Sort by fused score descending
        ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)

        # Return top_k results with fused score
        fused: list[dict[str, Any]] = []
        for cid in ranked_ids[:top_k]:
            entry = {**chunks[cid], "similarity": scores[cid]}
            fused.append(entry)

        return fused

    async def delete_document(self, document_id: uuid.UUID) -> bool:
        """Delete a document and its chunks.

        Args:
            document_id: Document UUID

        Returns:
            True if deleted successfully
        """
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            return False

        # Delete chunks first (cascades via FK but explicit is clearer)
        await self.vector_provider.delete_document_chunks(document_id)

        # Delete document
        await self.db.delete(document)
        await self.db.commit()

        self.logger.info(
            "document_deleted",
            document_id=str(document_id),
        )

        return True

    async def reindex_document(
        self,
        document_id: uuid.UUID,
        content: bytes,
    ) -> Document:
        """Reindex a document: delete old chunks and reprocess.

        Args:
            document_id: Document UUID
            content: File content bytes

        Returns:
            Updated Document record
        """
        # Delete existing chunks
        await self.vector_provider.delete_document_chunks(document_id)

        # Reset document status
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        document = result.scalar_one_or_none()
        if not document:
            msg = f"Document not found: {document_id}"
            raise ValueError(msg)

        document.status = "pending"
        document.chunk_count = 0
        document.content = None
        document.error_message = None
        await self.db.commit()

        # Reprocess
        return await self.process_document(document_id, content)

    async def get_documents(self, agent_id: uuid.UUID) -> list[Document]:
        """Get all documents for an agent.

        Args:
            agent_id: Agent UUID

        Returns:
            List of Document records
        """
        result = await self.db.execute(
            select(Document)
            .where(Document.agent_id == agent_id)
            .order_by(Document.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_document(self, document_id: uuid.UUID) -> Document | None:
        """Get a document by ID.

        Args:
            document_id: Document UUID

        Returns:
            Document record or None
        """
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        return result.scalar_one_or_none()
