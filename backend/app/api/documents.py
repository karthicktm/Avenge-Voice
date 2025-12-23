"""Document management API for RAG knowledge base."""

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import get_current_user
from app.db.session import get_db
from app.models.agent import Agent
from app.models.document import Document
from app.models.user import User
from app.services.rag_service import RAGService

router = APIRouter()

# File size limit: 10MB per file
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB in bytes

# Allowed file types and MIME types
ALLOWED_FILE_TYPES = {
    "pdf": ["application/pdf"],
    "docx": [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ],
    "doc": ["application/msword"],
    "txt": ["text/plain"],
    "md": ["text/markdown", "text/plain"],
    "xlsx": ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"],
    "xls": ["application/vnd.ms-excel"],
}


def get_file_extension(filename: str) -> str:
    """Extract file extension from filename."""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_file(file: UploadFile) -> tuple[bool, str | None]:
    """Validate file type and size.

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check file extension
    ext = get_file_extension(file.filename or "")
    if ext not in ALLOWED_FILE_TYPES:
        allowed = ", ".join(ALLOWED_FILE_TYPES.keys())
        return False, f"File type '{ext}' not allowed. Allowed types: {allowed}"

    # Check MIME type
    content_type = file.content_type or ""
    if content_type not in ALLOWED_FILE_TYPES.get(ext, []):
        return False, f"Invalid MIME type '{content_type}' for file type '{ext}'"

    return True, None


@router.post(
    "/agents/{agent_id}/documents",
    status_code=status.HTTP_201_CREATED,
)
async def upload_documents(
    agent_id: uuid.UUID,
    files: list[UploadFile] = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Upload multiple documents to an agent's knowledge base.

    Args:
        agent_id: UUID of the agent
        files: List of files to upload
        background_tasks: FastAPI background tasks
        db: Database session
        current_user: Authenticated user

    Returns:
        Dictionary with created documents and any errors

    Raises:
        HTTPException: If agent not found or user doesn't have access
    """
    # Verify agent exists and user has access
    # Use selectinload to eagerly load agent_workspaces relationship
    from sqlalchemy.orm import selectinload

    result = await db.execute(
        select(Agent)
        .where(Agent.id == agent_id)
        .where(Agent.user_id == current_user.id)
        .options(selectinload(Agent.agent_workspaces))
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Get workspace_id from agent's workspaces (use first workspace if multiple)
    workspace_id = None
    if agent.agent_workspaces:
        workspace_id = agent.agent_workspaces[0].workspace_id

    created_documents = []
    errors = []

    for file in files:
        try:
            # Validate file
            is_valid, error_msg = validate_file(file)
            if not is_valid:
                errors.append({"filename": file.filename, "error": error_msg})
                continue

            # Read file content
            content = await file.read()
            file_size = len(content)

            # Check file size
            if file_size > MAX_FILE_SIZE:
                size_mb = file_size / (1024 * 1024)
                errors.append({
                    "filename": file.filename,
                    "error": f"File too large: {size_mb:.1f}MB (max 10MB)",
                })
                continue

            # Create document record
            doc = Document(
                id=uuid.uuid4(),
                agent_id=agent_id,
                workspace_id=workspace_id,  # Use agent's workspace
                filename=file.filename or "untitled",
                file_type=get_file_extension(file.filename or ""),
                file_size=file_size,
                content=content,
                storage_provider="postgres",
                status="uploading",
            )

            db.add(doc)
            await db.commit()
            await db.refresh(doc)

            # Schedule background processing
            background_tasks.add_task(process_document_background, doc.id, db)

            created_documents.append({
                "id": str(doc.id),
                "filename": doc.filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "status": doc.status,
                "created_at": doc.created_at.isoformat(),
            })

        except Exception as e:
            errors.append({
                "filename": file.filename,
                "error": f"Unexpected error: {str(e)}",
            })

    return {
        "documents": created_documents,
        "errors": errors,
        "total_uploaded": len(created_documents),
        "total_failed": len(errors),
    }


async def process_document_background(document_id: uuid.UUID, db: AsyncSession) -> None:
    """Background task to process document.

    Args:
        document_id: UUID of the document to process
        db: Database session
    """
    try:
        rag_service = RAGService(db)
        await rag_service.process_document(document_id)
    except Exception as e:
        # Error is already logged in RAGService
        print(f"Background processing failed for document {document_id}: {e}")


@router.get("/agents/{agent_id}/documents")
async def list_documents(
    agent_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """List all documents for an agent.

    Args:
        agent_id: UUID of the agent
        db: Database session
        current_user: Authenticated user

    Returns:
        Dictionary with list of documents

    Raises:
        HTTPException: If agent not found or user doesn't have access
    """
    # Verify agent exists and user has access
    result = await db.execute(
        select(Agent)
        .where(Agent.id == agent_id)
        .where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Fetch all documents for this agent
    result = await db.execute(
        select(Document)
        .where(Document.agent_id == agent_id)
        .order_by(Document.created_at.desc())
    )
    documents = result.scalars().all()

    return {
        "documents": [
            {
                "id": str(doc.id),
                "filename": doc.filename,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "status": doc.status,
                "chunk_count": doc.chunk_count,
                "error_message": doc.error_message,
                "created_at": doc.created_at.isoformat(),
                "updated_at": doc.updated_at.isoformat(),
            }
            for doc in documents
        ],
        "total": len(documents),
    }


@router.delete(
    "/agents/{agent_id}/documents/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    agent_id: uuid.UUID,
    document_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> None:
    """Delete a document from an agent's knowledge base.

    Args:
        agent_id: UUID of the agent
        document_id: UUID of the document to delete
        db: Database session
        current_user: Authenticated user

    Raises:
        HTTPException: If agent or document not found, or user doesn't have access
    """
    # Verify agent exists and user has access
    result = await db.execute(
        select(Agent)
        .where(Agent.id == agent_id)
        .where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Fetch document and verify ownership
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .where(Document.agent_id == agent_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )

    # Delete document (cascade will delete chunks)
    await db.delete(doc)
    await db.commit()


@router.post("/agents/{agent_id}/documents/{document_id}/reindex")
async def reindex_document(
    agent_id: uuid.UUID,
    document_id: uuid.UUID,
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Reprocess a document (delete old chunks and re-embed).

    Args:
        agent_id: UUID of the agent
        document_id: UUID of the document to reindex
        background_tasks: FastAPI background tasks
        db: Database session
        current_user: Authenticated user

    Returns:
        Dictionary with reindex status

    Raises:
        HTTPException: If agent or document not found, or user doesn't have access
    """
    # Verify agent exists and user has access
    result = await db.execute(
        select(Agent)
        .where(Agent.id == agent_id)
        .where(Agent.user_id == current_user.id)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    # Fetch document and verify ownership
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id)
        .where(Document.agent_id == agent_id)
    )
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document {document_id} not found",
        )

    # Reset status to processing
    doc.status = "processing"
    doc.error_message = None
    await db.commit()

    # Schedule reindexing in background
    background_tasks.add_task(reindex_document_background, document_id, db)

    return {
        "message": f"Document {doc.filename} is being reprocessed",
        "document_id": str(document_id),
        "status": "processing",
    }


async def reindex_document_background(document_id: uuid.UUID, db: AsyncSession) -> None:
    """Background task to reindex document.

    Args:
        document_id: UUID of the document to reindex
        db: Database session
    """
    try:
        rag_service = RAGService(db)
        await rag_service.reindex_document(document_id)
    except Exception as e:
        print(f"Background reindexing failed for document {document_id}: {e}")
