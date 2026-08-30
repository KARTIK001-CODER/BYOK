import enum
from typing import Any

from app.core.exceptions import AppException


class IngestionErrorCode(enum.StrEnum):
    """Standardized error codes for document extraction, normalization, and chunking."""

    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    STORAGE_READ_FAILED = "STORAGE_READ_FAILED"
    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    PDF_EXTRACTION_FAILED = "PDF_EXTRACTION_FAILED"
    DOCX_EXTRACTION_FAILED = "DOCX_EXTRACTION_FAILED"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    CHUNKING_FAILED = "CHUNKING_FAILED"
    RESOURCE_LIMIT_EXCEEDED = "RESOURCE_LIMIT_EXCEEDED"
    PERSISTENCE_FAILED = "PERSISTENCE_FAILED"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class IngestionException(AppException):
    """Custom domain exception raised during document processing pipeline."""

    def __init__(
        self,
        message: str,
        code: IngestionErrorCode | str = IngestionErrorCode.INTERNAL_ERROR,
        status_code: int = 422,
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code.value if isinstance(code, IngestionErrorCode) else code,
            status_code=status_code,
            details=details,
        )
