"""Documents API for Knowledge Base / RAG functionality."""

import uuid
from datetime import datetime
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations import get_workspace_integrations
from app.core.auth import get_current_user, user_id_to_uuid
from app.core.config import settings
from app.db.session import get_db
from app.models.agent import Agent
from app.models.document import Document
from app.models.user import User
from app.models.workspace import AgentWorkspace
from app.services.document_processor import DocumentProcessor
from app.services.rag_service import RAGService

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/agents", tags=["documents"])


# Response models
class DocumentResponse(BaseModel):
    """Document response model."""

    id: str
    agent_id: str
    filename: str
    file_type: str
    file_size: int
    status: str
    error_message: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None

    class Config:
        from_attributes = True


class DocumentListResponse(BaseModel):
    """Document list response."""

    documents: list[DocumentResponse]
    total: int


# Helper functions
async def verify_agent_ownership(
    db: AsyncSession,
    agent_id: uuid.UUID,
    user_id: int,
) -> Agent:
    """Verify agent exists and belongs to user."""
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.user_id == user_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Agent not found",
        )
    return agent


async def process_document_background(
    document_id: uuid.UUID,
    content: bytes,
    embedding_config: dict[str, Any] | None = None,
) -> None:
    """Background task to process document."""
    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        try:
            rag_service = RAGService(db, embedding_config=embedding_config)
            await rag_service.process_document(document_id, content)
        except Exception:
            logger.exception("background_document_processing_failed", document_id=str(document_id))


# API Endpoints
@router.post(
    "/{agent_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    agent_id: uuid.UUID,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DocumentResponse:
    """Upload a document to an agent's knowledge base.

    Supported file types: PDF, DOCX, TXT, MD
    Max file size: 10MB
    """
    # Verify agent ownership
    await verify_agent_ownership(db, agent_id, current_user.id)

    # Validate file
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename required",
        )

    processor = DocumentProcessor()
    file_type = processor.get_file_type(file.filename)
    if not file_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Supported: {', '.join(processor.SUPPORTED_TYPES)}",
        )

    # Read file content
    content = await file.read()

    if len(content) > settings.RAG_MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Max size: {settings.RAG_MAX_FILE_SIZE // 1024 // 1024}MB",
        )

    # Get agent to access tool_configs
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()

    # Get embedding config from agent's tool_configs first
    kb_config = agent.tool_configs.get("knowledge_base", {}) if agent else {}

    # If not configured at agent level, check workspace-level integrations
    if not kb_config.get("api_key") and agent:
        # Get agent's workspace
        ws_result = await db.execute(
            select(AgentWorkspace).where(AgentWorkspace.agent_id == agent_id).limit(1)
        )
        agent_workspace = ws_result.scalar_one_or_none()

        if agent_workspace:
            user_uuid = user_id_to_uuid(current_user.id)
            workspace_integrations = await get_workspace_integrations(
                user_uuid, agent_workspace.workspace_id, db
            )
            kb_config = workspace_integrations.get("knowledge_base", {})

    if not kb_config.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge Base not configured. Please configure the embedding API key in the agent's tool settings or connect the Knowledge Base integration for the workspace.",
        )

    # Build embedding config
    embedding_config = {
        "api_key": kb_config.get("api_key"),
        "embedding_model": kb_config.get("embedding_model", "text-embedding-3-small"),
        "embedding_provider": kb_config.get("embedding_provider", "openai"),
    }

    # Create document record
    rag_service = RAGService(db, embedding_config=embedding_config)
    try:
        document = await rag_service.upload_document(
            agent_id=agent_id,
            filename=file.filename,
            content=content,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e

    # Process document in background
    background_tasks.add_task(process_document_background, document.id, content, embedding_config)

    return DocumentResponse(
        id=str(document.id),
        agent_id=str(document.agent_id),
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        status=document.status,
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
        processed_at=document.processed_at,
    )


@router.get(
    "/{agent_id}/documents",
    response_model=DocumentListResponse,
)
async def list_documents(
    agent_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DocumentListResponse:
    """List all documents in an agent's knowledge base."""
    # Verify agent ownership
    await verify_agent_ownership(db, agent_id, current_user.id)

    rag_service = RAGService(db)
    documents = await rag_service.get_documents(agent_id)

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=str(doc.id),
                agent_id=str(doc.agent_id),
                filename=doc.filename,
                file_type=doc.file_type,
                file_size=doc.file_size,
                status=doc.status,
                error_message=doc.error_message,
                chunk_count=doc.chunk_count,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
                processed_at=doc.processed_at,
            )
            for doc in documents
        ],
        total=len(documents),
    )


@router.get(
    "/{agent_id}/documents/{document_id}",
    response_model=DocumentResponse,
)
async def get_document(
    agent_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DocumentResponse:
    """Get a specific document."""
    # Verify agent ownership
    await verify_agent_ownership(db, agent_id, current_user.id)

    rag_service = RAGService(db)
    document = await rag_service.get_document(document_id)

    if not document or document.agent_id != agent_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    return DocumentResponse(
        id=str(document.id),
        agent_id=str(document.agent_id),
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        status=document.status,
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
        processed_at=document.processed_at,
    )


@router.delete(
    "/{agent_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    agent_id: uuid.UUID,
    document_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    """Delete a document from the knowledge base."""
    # Verify agent ownership
    await verify_agent_ownership(db, agent_id, current_user.id)

    # Verify document belongs to agent
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.agent_id == agent_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    rag_service = RAGService(db)
    await rag_service.delete_document(document_id)


@router.post(
    "/{agent_id}/documents/{document_id}/reindex",
    response_model=DocumentResponse,
)
async def reindex_document(
    agent_id: uuid.UUID,
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> DocumentResponse:
    """Reindex a document (reprocess with updated settings).

    Note: This endpoint requires the document to still have stored content.
    For documents without stored content, re-upload is required.
    """
    # Verify agent ownership
    await verify_agent_ownership(db, agent_id, current_user.id)

    # Get document
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.agent_id == agent_id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found",
        )

    if not document.content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Document content not available. Please re-upload the file.",
        )

    # Get agent to access tool_configs
    agent_result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = agent_result.scalar_one_or_none()

    # Get embedding config from agent's tool_configs first
    kb_config = agent.tool_configs.get("knowledge_base", {}) if agent else {}

    # If not configured at agent level, check workspace-level integrations
    if not kb_config.get("api_key") and agent:
        ws_result = await db.execute(
            select(AgentWorkspace).where(AgentWorkspace.agent_id == agent_id).limit(1)
        )
        agent_workspace = ws_result.scalar_one_or_none()

        if agent_workspace:
            user_uuid = user_id_to_uuid(current_user.id)
            workspace_integrations = await get_workspace_integrations(
                user_uuid, agent_workspace.workspace_id, db
            )
            kb_config = workspace_integrations.get("knowledge_base", {})

    if not kb_config.get("api_key"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Knowledge Base not configured. Please configure the embedding API key in the agent's tool settings or connect the Knowledge Base integration for the workspace.",
        )

    # Build embedding config
    embedding_config = {
        "api_key": kb_config.get("api_key"),
        "embedding_model": kb_config.get("embedding_model", "text-embedding-3-small"),
        "embedding_provider": kb_config.get("embedding_provider", "openai"),
    }

    # Reset status
    document.status = "pending"
    document.chunk_count = 0
    await db.commit()
    await db.refresh(document)

    # Reprocess in background
    # Convert stored text content back to bytes for reprocessing
    content_bytes = document.content.encode("utf-8")
    background_tasks.add_task(
        process_document_background, document.id, content_bytes, embedding_config
    )

    return DocumentResponse(
        id=str(document.id),
        agent_id=str(document.agent_id),
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        status=document.status,
        error_message=document.error_message,
        chunk_count=document.chunk_count,
        created_at=document.created_at,
        updated_at=document.updated_at,
        processed_at=document.processed_at,
    )
