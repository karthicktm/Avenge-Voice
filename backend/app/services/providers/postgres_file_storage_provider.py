"""PostgreSQL BYTEA file storage provider implementation."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.providers.file_storage_provider import FileStorageProvider


class PostgresFileStorageProvider(FileStorageProvider):
    """PostgreSQL BYTEA file storage implementation.

    Stores files directly in the Document.content column using PostgreSQL BYTEA type.
    Simple and requires no external services, but may impact database size for large files.
    """

    def __init__(self, db: AsyncSession):
        """Initialize PostgreSQL file storage provider.

        Args:
            db: Async database session
        """
        self.db = db

    async def store_file(self, file_content: bytes, path: str) -> str:
        """Store file in PostgreSQL BYTEA column.

        Note: The actual storage happens in the Document model's content field.
        This provider is mostly for interface compliance.

        Args:
            file_content: File bytes to store
            path: Document ID (used as identifier)

        Returns:
            The path (document ID) as storage identifier
        """
        # File content is stored directly in Document.content column
        # No separate storage operation needed
        return path

    async def retrieve_file(self, path: str) -> bytes:
        """Retrieve file from PostgreSQL.

        Note: File retrieval happens via Document model query.
        This method is mostly for interface compliance.

        Args:
            path: Document ID

        Returns:
            File content bytes

        Raises:
            NotImplementedError: Use Document model directly for retrieval
        """
        # Files are retrieved via Document model query
        # This method is not typically called directly
        raise NotImplementedError(
            "File retrieval should be done via Document model query. "
            "Use db.execute(select(Document).where(Document.id == document_id))"
        )

    async def delete_file(self, path: str) -> None:
        """Delete file from PostgreSQL.

        Note: File deletion happens via Document deletion (CASCADE).
        No separate operation needed.

        Args:
            path: Document ID
        """
        # File deletion is handled by Document model deletion (CASCADE)
        # No separate operation needed
        pass
