import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_request_id

logger = logging.getLogger("app.core.exceptions")


class AppException(Exception):
    """Base application exception."""

    def __init__(
        self,
        message: str,
        code: str = "INTERNAL_ERROR",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
        details: Any = None,
    ) -> None:
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details
        super().__init__(message)


class NotFoundException(AppException):
    def __init__(self, message: str = "Resource not found", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
            details=details,
        )


class ValidationException(AppException):
    def __init__(self, message: str = "Validation error", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="VALIDATION_ERROR",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=details,
        )


class DatabaseException(AppException):
    def __init__(self, message: str = "Database operation failed", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="DATABASE_ERROR",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


class ServiceUnavailableException(AppException):
    def __init__(self, message: str = "Service unavailable", details: Any = None) -> None:
        super().__init__(
            message=message,
            code="SERVICE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details=details,
        )


def create_error_response(
    code: str, message: str, status_code: int, details: Any = None
) -> JSONResponse:
    req_id = get_request_id() or "unknown"
    content: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": req_id,
        }
    }
    if details is not None:
        content["error"]["details"] = details
    return JSONResponse(status_code=status_code, content=content)


def register_exception_handlers(app: FastAPI) -> None:
    """Register centralized exception handlers for FastAPI app."""

    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "AppException handled: [%s] %s | path=%s", exc.code, exc.message, request.url.path
        )
        return create_error_response(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            status.HTTP_404_NOT_FOUND: "NOT_FOUND",
            status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
            status.HTTP_403_FORBIDDEN: "FORBIDDEN",
            status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
            status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
            status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
        }
        code = code_map.get(exc.status_code, "HTTP_ERROR")
        logger.warning(
            "HTTPException handled: status=%d code=%s | path=%s",
            exc.status_code,
            code,
            request.url.path,
        )
        message = str(exc.detail) if exc.detail else "An HTTP error occurred."
        return create_error_response(code=code, message=message, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.warning(
            "RequestValidationError handled: errors=%s | path=%s",
            exc.errors(),
            request.url.path,
        )
        return create_error_response(
            code="VALIDATION_ERROR",
            message="Request validation failed.",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            details=exc.errors(),
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server exception: %s | path=%s", str(exc), request.url.path)
        return create_error_response(
            code="INTERNAL_ERROR",
            message="An unexpected error occurred.",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
