"""Add RAG support with pgvector

Revision ID: 015_add_rag_support
Revises: ee167a9a2635
Create Date: 2025-12-23

This migration adds RAG (Retrieval Augmented Generation) support:
- Enables pgvector extension for vector similarity search
- documents table: Store uploaded knowledge base files
- document_chunks table: Store text chunks with embeddings
- Supports multiple file formats (PDF, DOCX, TXT, MD, XLSX)
- Agent-specific knowledge bases with workspace isolation
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, BYTEA, TIMESTAMP
from pgvector.sqlalchemy import Vector


# revision identifiers, used by Alembic.
revision: str = "015_add_rag_support"
down_revision: Union[str, Sequence[str], None] = "ee167a9a2635"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgvector extension for vector similarity search
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')

    # Create documents table
    op.create_table(
        'documents',
        # Primary key and foreign keys
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            'agent_id',
            UUID(as_uuid=True),
            sa.ForeignKey('agents.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='Agent this document belongs to'
        ),
        sa.Column(
            'workspace_id',
            UUID(as_uuid=True),
            sa.ForeignKey('workspaces.id', ondelete='CASCADE'),
            nullable=True,  # Nullable for migration, will be required after workspace rollout
            index=True,
            comment='Workspace this document belongs to'
        ),

        # File metadata
        sa.Column(
            'filename',
            sa.String(255),
            nullable=False,
            comment='Original filename'
        ),
        sa.Column(
            'file_type',
            sa.String(10),
            nullable=False,
            comment='File extension: pdf, docx, txt, md, xlsx, etc.'
        ),
        sa.Column(
            'file_size',
            sa.Integer,
            nullable=False,
            comment='File size in bytes'
        ),

        # File storage
        sa.Column(
            'content',
            BYTEA,
            nullable=True,
            comment='File content (BYTEA for PostgreSQL storage, nullable for future S3/cloud storage)'
        ),
        sa.Column(
            'storage_provider',
            sa.String(50),
            nullable=False,
            server_default='postgres',
            comment='Storage backend: postgres, s3, supabase, etc.'
        ),
        sa.Column(
            'storage_url',
            sa.String(500),
            nullable=True,
            comment='External storage URL (for S3/cloud providers)'
        ),

        # Processing status
        sa.Column(
            'status',
            sa.String(20),
            nullable=False,
            server_default='uploading',
            index=True,
            comment='Processing status: uploading, processing, ready, error'
        ),
        sa.Column(
            'error_message',
            sa.Text,
            nullable=True,
            comment='Error message if processing failed'
        ),
        sa.Column(
            'chunk_count',
            sa.Integer,
            nullable=False,
            server_default='0',
            comment='Number of chunks created from this document'
        ),

        # Embedding metadata
        sa.Column(
            'embedding_model',
            sa.String(100),
            nullable=False,
            server_default='text-embedding-3-small',
            comment='Embedding model used (e.g., text-embedding-3-small)'
        ),
        sa.Column(
            'embedding_dimensions',
            sa.Integer,
            nullable=False,
            server_default='1536',
            comment='Embedding vector dimensions (1536 for text-embedding-3-small)'
        ),

        # Timestamps
        sa.Column(
            'created_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='When document was uploaded'
        ),
        sa.Column(
            'updated_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            onupdate=sa.text('now()'),
            comment='When document was last updated'
        ),
    )

    # Create indexes for documents table
    op.create_index('idx_documents_agent_id', 'documents', ['agent_id'])
    op.create_index('idx_documents_workspace_id', 'documents', ['workspace_id'])
    op.create_index('idx_documents_status', 'documents', ['status'])
    op.create_index('idx_documents_created_at', 'documents', ['created_at'])

    # Create document_chunks table
    op.create_table(
        'document_chunks',
        # Primary key and foreign keys
        sa.Column('id', UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            'document_id',
            UUID(as_uuid=True),
            sa.ForeignKey('documents.id', ondelete='CASCADE'),
            nullable=False,
            index=True,
            comment='Document this chunk belongs to'
        ),

        # Chunk data
        sa.Column(
            'chunk_index',
            sa.Integer,
            nullable=False,
            comment='0-based index of chunk within document'
        ),
        sa.Column(
            'content_text',
            sa.Text,
            nullable=False,
            comment='The actual text content of this chunk'
        ),

        # Vector embedding (pgvector type)
        sa.Column(
            'embedding',
            Vector(1536),  # 1536 dimensions for text-embedding-3-small
            nullable=False,
            comment='Vector embedding for semantic search'
        ),

        # Metadata
        sa.Column(
            'metadata',
            sa.JSON,
            nullable=False,
            server_default='{}',
            comment='Additional metadata (page number, section, etc.)'
        ),

        # Timestamp
        sa.Column(
            'created_at',
            TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text('now()'),
            comment='When chunk was created'
        ),
    )

    # Create indexes for document_chunks table
    op.create_index('idx_chunks_document_id', 'document_chunks', ['document_id'])
    op.create_index(
        'idx_chunks_document_chunk',
        'document_chunks',
        ['document_id', 'chunk_index'],
        unique=True
    )

    # Create IVFFlat index for vector similarity search
    # Note: IVFFlat is good for datasets with 1000+ vectors
    # For smaller datasets, brute force (no index) is actually faster
    # We create the index structure but it will auto-optimize based on data size
    op.execute("""
        CREATE INDEX idx_chunks_embedding_cosine
        ON document_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    # Drop indexes first
    op.drop_index('idx_chunks_embedding_cosine', table_name='document_chunks')
    op.drop_index('idx_chunks_document_chunk', table_name='document_chunks')
    op.drop_index('idx_chunks_document_id', table_name='document_chunks')

    # Drop document_chunks table
    op.drop_table('document_chunks')

    # Drop documents indexes
    op.drop_index('idx_documents_created_at', table_name='documents')
    op.drop_index('idx_documents_status', table_name='documents')
    op.drop_index('idx_documents_workspace_id', table_name='documents')
    op.drop_index('idx_documents_agent_id', table_name='documents')

    # Drop documents table
    op.drop_table('documents')

    # Note: We don't drop the pgvector extension as other parts of the system might use it
    # If you really want to drop it: op.execute('DROP EXTENSION IF EXISTS vector')
