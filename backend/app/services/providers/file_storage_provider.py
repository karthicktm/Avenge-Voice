"""Abstract base class for file storage providers."""

from abc import ABC, abstractmethod


class FileStorageProvider(ABC):
    """Abstract base class for file storage providers.

    Provides a common interface for storing and retrieving files using different
    backends (PostgreSQL BYTEA, S3, Supabase Storage, etc.).
    """

    @abstractmethod
    async def store_file(self, file_content: bytes, path: str) -> str:
        """Store file content and return a storage identifier/URL.

        Args:
            file_content: The file content as bytes
            path: Storage path/key (e.g., document UUID)

        Returns:
            Storage identifier or URL where the file can be retrieved

        Raises:
            Exception: If storage fails
        """
        pass

    @abstractmethod
    async def retrieve_file(self, path: str) -> bytes:
        """Retrieve file content from storage.

        Args:
            path: Storage path/key to retrieve

        Returns:
            File content as bytes

        Raises:
            Exception: If retrieval fails or file not found
        """
        pass

    @abstractmethod
    async def delete_file(self, path: str) -> None:
        """Delete file from storage.

        Args:
            path: Storage path/key to delete

        Raises:
            Exception: If deletion fails
        """
        pass
