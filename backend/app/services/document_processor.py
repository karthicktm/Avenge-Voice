"""Document processing service for text extraction and chunking."""

import io
from dataclasses import dataclass
from typing import Any

import tiktoken
from docx import Document as DocxDocument
from openpyxl import load_workbook
from pypdf import PdfReader


@dataclass
class DocumentChunkData:
    """Chunk data before database persistence.

    Attributes:
        chunk_index: 0-based index of this chunk within the document
        content_text: The text content of this chunk
        metadata: Additional metadata (page numbers, sheet names, etc.)
    """

    chunk_index: int
    content_text: str
    metadata: dict[str, Any]


class DocumentProcessor:
    """Process documents: extract text, chunk, and prepare for embedding.

    Supports:
    - PDF files (pypdf)
    - DOCX files (python-docx)
    - Excel files (openpyxl)
    - Text files (TXT, MD)
    """

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        encoding_model: str = "cl100k_base",
    ):
        """Initialize document processor.

        Args:
            chunk_size: Target chunk size in tokens (default 500)
            chunk_overlap: Overlap between chunks in tokens (default 50)
            encoding_model: Tiktoken encoding to use (default cl100k_base for GPT-4)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.encoder = tiktoken.get_encoding(encoding_model)

    async def extract_text(self, file_content: bytes, file_type: str) -> str:
        """Extract text from file based on type.

        Args:
            file_content: Raw file bytes
            file_type: File extension (pdf, docx, txt, md, xlsx, etc.)

        Returns:
            Extracted text content

        Raises:
            ValueError: If file type is not supported
            Exception: If extraction fails
        """
        file_type = file_type.lower()

        if file_type == "pdf":
            return await self._extract_pdf(file_content)
        elif file_type in ("docx", "doc"):
            return await self._extract_docx(file_content)
        elif file_type in ("txt", "md"):
            return file_content.decode("utf-8", errors="ignore")
        elif file_type in ("xlsx", "xls"):
            return await self._extract_excel(file_content)
        else:
            raise ValueError(f"Unsupported file type: {file_type}")

    async def _extract_pdf(self, content: bytes) -> str:
        """Extract text from PDF file.

        Args:
            content: PDF file bytes

        Returns:
            Extracted text with page markers

        Raises:
            Exception: If PDF parsing fails
        """
        try:
            pdf = PdfReader(io.BytesIO(content))
            text_parts = []

            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text()
                if text.strip():
                    text_parts.append(f"[Page {page_num}]\n{text}")

            return "\n\n".join(text_parts) if text_parts else ""
        except Exception as e:
            raise Exception(f"Failed to extract text from PDF: {e}") from e

    async def _extract_docx(self, content: bytes) -> str:
        """Extract text from DOCX file.

        Args:
            content: DOCX file bytes

        Returns:
            Extracted text from paragraphs

        Raises:
            Exception: If DOCX parsing fails
        """
        try:
            doc = DocxDocument(io.BytesIO(content))
            paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
            return "\n\n".join(paragraphs) if paragraphs else ""
        except Exception as e:
            raise Exception(f"Failed to extract text from DOCX: {e}") from e

    async def _extract_excel(self, content: bytes) -> str:
        """Extract text from Excel file.

        Args:
            content: Excel file bytes

        Returns:
            Extracted text with sheet markers

        Raises:
            Exception: If Excel parsing fails
        """
        try:
            wb = load_workbook(io.BytesIO(content), data_only=True)
            text_parts = []

            for sheet_name in wb.sheetnames:
                ws = wb[sheet_name]
                text_parts.append(f"[Sheet: {sheet_name}]")

                for row in ws.iter_rows(values_only=True):
                    row_text = " | ".join(str(cell) for cell in row if cell is not None)
                    if row_text.strip():
                        text_parts.append(row_text)

            return "\n".join(text_parts) if text_parts else ""
        except Exception as e:
            raise Exception(f"Failed to extract text from Excel: {e}") from e

    def chunk_text(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> list[DocumentChunkData]:
        """Split text into overlapping chunks based on token count.

        Args:
            text: Text to chunk
            metadata: Optional base metadata to include in each chunk

        Returns:
            List of DocumentChunkData objects

        Raises:
            Exception: If tokenization fails
        """
        if not text.strip():
            return []

        if metadata is None:
            metadata = {}

        try:
            # Tokenize the full text
            tokens = self.encoder.encode(text)
            chunks = []
            chunk_idx = 0
            start = 0

            while start < len(tokens):
                # Get chunk tokens
                end = min(start + self.chunk_size, len(tokens))
                chunk_tokens = tokens[start:end]

                # Decode back to text
                chunk_text = self.encoder.decode(chunk_tokens)

                # Create chunk data
                chunks.append(
                    DocumentChunkData(
                        chunk_index=chunk_idx,
                        content_text=chunk_text,
                        metadata=metadata.copy(),
                    )
                )

                # Move forward with overlap
                start += self.chunk_size - self.chunk_overlap
                chunk_idx += 1

            return chunks

        except Exception as e:
            raise Exception(f"Failed to chunk text: {e}") from e

    def count_tokens(self, text: str) -> int:
        """Count tokens in text.

        Args:
            text: Text to count tokens for

        Returns:
            Number of tokens
        """
        return len(self.encoder.encode(text))
