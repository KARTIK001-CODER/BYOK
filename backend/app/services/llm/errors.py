import enum
from typing import Any

from fastapi import status

from app.core.exceptions import AppException


class LLMErrorCode(enum.StrEnum):
    """Standardized error codes for LLM generation failure modes."""

    LLM_PROVIDER_NOT_CONFIGURED = "LLM_PROVIDER_NOT_CONFIGURED"
    LLM_PROVIDER_UNSUPPORTED = "LLM_PROVIDER_UNSUPPORTED"
    LLM_MODEL_UNSUPPORTED = "LLM_MODEL_UNSUPPORTED"
    LLM_AUTHENTICATION_FAILED = "LLM_AUTHENTICATION_FAILED"
    LLM_RATE_LIMITED = "LLM_RATE_LIMITED"
    LLM_TIMEOUT = "LLM_TIMEOUT"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    CONTEXT_TOO_LARGE = "CONTEXT_TOO_LARGE"
    GENERATION_FAILED = "GENERATION_FAILED"


class LLMException(AppException):
    """Domain exception raised by LLM providers with user-friendly sanitized messages."""

    def __init__(
        self,
        message: str,
        code: LLMErrorCode | str = LLMErrorCode.GENERATION_FAILED,
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Any = None,
    ) -> None:
        super().__init__(
            message=message,
            code=code.value if isinstance(code, LLMErrorCode) else str(code),
            status_code=status_code,
            details=details,
        )
