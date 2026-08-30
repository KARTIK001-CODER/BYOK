import logging

from app.services.ingestion.errors import IngestionErrorCode, IngestionException
from app.services.ingestion.extractors.base import BaseExtractor, ExtractedSection

logger = logging.getLogger("app.services.ingestion.extractors.text")


class TextExtractor(BaseExtractor):
    """Plain text extractor with robust UTF-8 and fallback encodings (latin-1, cp1252)."""

    def extract(self, content: bytes) -> list[ExtractedSection]:
        if not content or len(content) == 0:
            raise IngestionException(
                message="Text file content is empty.",
                code=IngestionErrorCode.EMPTY_DOCUMENT,
            )

        decoded_text: str | None = None
        for encoding in ["utf-8", "utf-8-sig", "latin-1", "cp1252"]:
            try:
                decoded_text = content.decode(encoding)
                break
            except UnicodeDecodeError:
                continue

        if decoded_text is None:
            raise IngestionException(
                message="Unable to decode plain text document using standard encodings.",
                code=IngestionErrorCode.UNSUPPORTED_FILE_TYPE,
            )

        if not decoded_text.strip():
            raise IngestionException(
                message="Text document contains no extractable content.",
                code=IngestionErrorCode.EMPTY_DOCUMENT,
            )

        return [ExtractedSection(text=decoded_text, page_number=None, section_title=None)]
