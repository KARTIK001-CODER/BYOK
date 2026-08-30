import hashlib
import re
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import ValidationException

# Supported file format mappings: extension -> accepted MIME types
SUPPORTED_EXTENSIONS: dict[str, set[str]] = {
    ".pdf": {"application/pdf", "application/octet-stream"},
    ".txt": {"text/plain", "application/octet-stream"},
    ".md": {"text/markdown", "text/plain", "application/octet-stream"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
        "application/octet-stream",
    },
}

# Magic byte signatures
MAGIC_BYTES_PDF = b"%PDF"
MAGIC_BYTES_DOCX = b"PK\x03\x04"


def sanitize_filename(original_filename: str) -> str:
    """
    Sanitize the user-provided filename to prevent path traversal and shell injection.
    """
    if not original_filename or not original_filename.strip():
        return "unnamed_document"

    # Extract base name only (stripping absolute/relative path components)
    clean_name = Path(original_filename).name

    # Remove any dangerous characters, keep alphanumeric, dots, hyphens, underscores, spaces
    clean_name = re.sub(r"[^\w\s\.-]", "_", clean_name).strip()
    return clean_name or "unnamed_document"


def calculate_sha256(content: bytes) -> str:
    """Calculate cryptographic SHA-256 digest of file content."""
    return hashlib.sha256(content).hexdigest()


def validate_upload_file(
    filename: str,
    content: bytes,
    content_type: str | None = None,
) -> tuple[str, str]:
    """
    Validate an uploaded file:
    1. Size within limit
    2. Extension is supported
    3. Magic byte inspection for binary formats (PDF, DOCX)
    4. Canonical Content-Type resolution

    Returns:
        tuple[sanitized_filename, canonical_content_type]
    """
    _ = content_type
    settings = get_settings()

    # 1. Size Validation
    if len(content) == 0:
        raise ValidationException(message="Uploaded file is empty.")

    if len(content) > settings.max_upload_size_bytes:
        msg = (
            f"File size ({len(content)} bytes) exceeds the maximum "
            f"allowed limit of {settings.MAX_UPLOAD_SIZE_MB}MB."
        )
        raise ValidationException(message=msg)

    # 2. Filename & Extension Validation
    clean_filename = sanitize_filename(filename)
    extension = Path(clean_filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        allowed = ", ".join(SUPPORTED_EXTENSIONS.keys())
        raise ValidationException(
            message=f"Unsupported file extension '{extension}'. Allowed formats: {allowed}."
        )

    # 3. Magic Bytes Inspection
    if extension == ".pdf":
        if not content.startswith(MAGIC_BYTES_PDF):
            raise ValidationException(message="Invalid PDF file format: missing '%PDF' header.")
        canonical_type = "application/pdf"

    elif extension == ".docx":
        if not content.startswith(MAGIC_BYTES_DOCX):
            raise ValidationException(message="Invalid DOCX file format: missing ZIP signature.")
        canonical_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    elif extension == ".md":
        canonical_type = "text/markdown"
    else:  # .txt
        canonical_type = "text/plain"

    return clean_filename, canonical_type
