import enum
from typing import Any

from app.core.exceptions import AppException


class EmbeddingErrorCode(enum.StrEnum):
    """Standardized error codes for embedding generation and vector operations."""

    MODEL_LOAD_FAILED = "MODEL_LOAD_FAILED"
    EMBEDDING_PROVIDER_FAILED = "EMBEDDING_PROVIDER_FAILED"
    EMBEDDING_DIMENSION_MISMATCH = "EMBEDDING_DIMENSION_MISMATCH"
    EMPTY_CHUNK = "EMPTY_CHUNK"
    TOO_MANY_CHUNKS = "TOO_MANY_CHUNKS"
    DATABASE_WRITE_FAILED = "DATABASE_WRITE_FAILED"
    DOCUMENT_NOT_READY = "DOCUMENT_NOT_READY"
    NO_CHUNKS_FOUND = "NO_CHUNKS_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EmbeddingException(AppException):
    """Custom domain exception raised during embedding generation pipeline."""

    def __init__(
        self,
        message: str,
        code: EmbeddingErrorCode | str = EmbeddingErrorCode.INTERNAL_ERROR,
        status_code: int = 422,
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code.value if isinstance(code, EmbeddingErrorCode) else code,
            status_code=status_code,
            details=details,
        )
