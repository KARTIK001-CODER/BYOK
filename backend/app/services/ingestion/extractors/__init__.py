from pathlib import Path

from app.services.ingestion.errors import IngestionErrorCode, IngestionException
from app.services.ingestion.extractors.base import BaseExtractor, ExtractedSection
from app.services.ingestion.extractors.docx import DOCXExtractor
from app.services.ingestion.extractors.markdown import MarkdownExtractor
from app.services.ingestion.extractors.pdf import PDFExtractor
from app.services.ingestion.extractors.text import TextExtractor


def get_extractor_for_file(filename: str, content_type: str | None = None) -> BaseExtractor:
    """Factory retrieving format-specific extractor based on filename extension and content type."""
    ext = Path(filename).suffix.lower()

    if ext == ".pdf" or content_type == "application/pdf":
        return PDFExtractor()
    elif ext in [".docx"] or (
        content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ):
        return DOCXExtractor()
    elif ext in [".md", ".markdown"] or content_type == "text/markdown":
        return MarkdownExtractor()
    elif ext in [".txt", ".text"] or content_type == "text/plain":
        return TextExtractor()
    else:
        raise IngestionException(
            message=f"Unsupported file format '{ext}'. Supported: .pdf, .docx, .md, .txt",
            code=IngestionErrorCode.UNSUPPORTED_FILE_TYPE,
        )


__all__ = [
    "BaseExtractor",
    "DOCXExtractor",
    "ExtractedSection",
    "MarkdownExtractor",
    "PDFExtractor",
    "TextExtractor",
    "get_extractor_for_file",
]
