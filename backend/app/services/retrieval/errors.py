import enum
from typing import Any

from app.core.exceptions import AppException


class RetrievalErrorCode(enum.StrEnum):
    """Standardized error codes for retrieval engine and hybrid search operations."""

    RETRIEVAL_QUERY_EMPTY = "RETRIEVAL_QUERY_EMPTY"
    RETRIEVAL_QUERY_TOO_LONG = "RETRIEVAL_QUERY_TOO_LONG"
    EMBEDDING_DIMENSION_MISMATCH = "EMBEDDING_DIMENSION_MISMATCH"
    RETRIEVAL_DATABASE_ERROR = "RETRIEVAL_DATABASE_ERROR"
    VECTOR_SEARCH_FAILED = "VECTOR_SEARCH_FAILED"
    KEYWORD_SEARCH_FAILED = "KEYWORD_SEARCH_FAILED"
    FUSION_FAILED = "FUSION_FAILED"
    INVALID_FILTER = "INVALID_FILTER"
    UNAUTHORIZED_KNOWLEDGE_BASE = "UNAUTHORIZED_KNOWLEDGE_BASE"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class RetrievalException(AppException):
    """Custom domain exception raised during retrieval pipeline execution."""

    def __init__(
        self,
        message: str,
        code: RetrievalErrorCode | str = RetrievalErrorCode.INTERNAL_ERROR,
        status_code: int = 422,
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code.value if isinstance(code, RetrievalErrorCode) else code,
            status_code=status_code,
            details=details,
        )
