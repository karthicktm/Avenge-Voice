"""RAG orchestration service for document processing and search."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document import Document
from app.services.document_processor import DocumentProcessor
from app.services.embedding_service import EmbeddingService
from app.services.providers.pgvector_provider import PgVectorProvider
from app.services.providers.vector_store_provider import VectorRecord


class RAGService:
    """Orchestrates document processing, embedding, and retrieval.

    Coordinates the full RAG pipeline:
    1. Extract text from documents
    2. Chunk text into manageable pieces
    3. Generate embeddings for chunks
    4. Store vectors in vector database
    5. Search knowledge base using semantic similarity
    """

    def __init__(
        self,
        db: AsyncSession,
        embedding_service: EmbeddingService | None = None,
        api_key: str | None = None,
    ):
        """Initialize RAG service.

        Args:
            db: Async database session
            embedding_service: Optional embedding service (default: creates new with OpenAI)
            api_key: Optional API key for embeddings (default: from settings)
        """
        self.db = db

        # Initialize services
        self.processor = DocumentProcessor(
            chunk_size=getattr(settings, "RAG_CHUNK_SIZE", 500),
            chunk_overlap=getattr(settings, "RAG_CHUNK_OVERLAP", 50),
        )
        self.embedding_service = embedding_service or EmbeddingService(api_key=api_key)
        self.vector_store = PgVectorProvider(db)

    async def process_document(self, document_id: uuid.UUID) -> None:
        """Process a document: extract text, chunk, embed, and store.

        Updates document status throughout the process.

        Args:
            document_id: UUID of the document to process

        Raises:
            ValueError: If document not found or has no content
            Exception: If processing fails at any step
        """
        # Fetch document
        result = await self.db.execute(select(Document).where(Document.id == document_id))
        doc = result.scalar_one_or_none()

        if not doc:
            raise ValueError(f"Document {document_id} not found")

        if not doc.content:
            raise ValueError(f"Document {document_id} has no content")

        try:
            # Update status to processing
            doc.status = "processing"
            await self.db.commit()

            # Step 1: Extract text from document
            text = await self.processor.extract_text(doc.content, doc.file_type)

            if not text.strip():
                raise ValueError(f"No text extracted from document {doc.filename}")

            # Step 2: Chunk text
            chunks = self.processor.chunk_text(
                text, metadata={"filename": doc.filename, "file_type": doc.file_type}
            )

            if not chunks:
                raise ValueError(f"No chunks created from document {doc.filename}")

            # Step 3: Generate embeddings
            chunk_texts = [chunk.content_text for chunk in chunks]
            embeddings = await self.embedding_service.embed_chunks(chunk_texts)

            # Step 4: Prepare vector records
            vector_records = [
                VectorRecord(
                    id=str(uuid.uuid4()),
                    vector=embeddings[i],
                    text=chunks[i].content_text,
                    metadata={
                        "document_id": str(doc.id),
                        "chunk_index": chunks[i].chunk_index,
                        "filename": doc.filename,
                        "file_type": doc.file_type,
                        **chunks[i].metadata,
                    },
                )
                for i in range(len(chunks))
            ]

            # Step 5: Store in vector database
            await self.vector_store.store_vectors(vector_records)

            # Step 6: Update document metadata
            doc.status = "ready"
            doc.chunk_count = len(chunks)

            embedding_meta = self.embedding_service.get_embedding_metadata()
            doc.embedding_model = embedding_meta["model"]
            doc.embedding_dimensions = embedding_meta["dimensions"]

            await self.db.commit()

        except Exception as e:
            # Update status to error
            doc.status = "error"
            doc.error_message = str(e)
            await self.db.commit()
            raise

    async def search_knowledge_base(
        self, agent_id: uuid.UUID, query: str, top_k: int = 3
    ) -> list[dict[str, Any]]:
        """Search agent's knowledge base using semantic similarity.

        Args:
            agent_id: UUID of the agent whose knowledge base to search
            query: Natural language search query
            top_k: Number of results to return (default 3)

        Returns:
            List of search results with text, source, score, and metadata

        Raises:
            Exception: If search fails
        """
        # Generate query embedding
        query_embedding = await self.embedding_service.embed_query(query)

        # Search vector store with agent filtering
        results = await self.vector_store.search_similar(
            query_vector=query_embedding,
            top_k=top_k,
            filter_metadata={"agent_id": str(agent_id)},
        )

        # Format results for consumption
        return [
            {
                "text": result.text,
                "source": result.metadata.get("filename", "Unknown"),
                "score": result.score,
                "metadata": result.metadata,
            }
            for result in results
        ]

    async def reindex_document(self, document_id: uuid.UUID) -> None:
        """Reprocess a document (delete old chunks and re-embed).

        Args:
            document_id: UUID of the document to reindex

        Raises:
            Exception: If reindexing fails
        """
        # Delete existing chunks
        await self.vector_store.delete_by_document(str(document_id))

        # Reprocess document
        await self.process_document(document_id)
