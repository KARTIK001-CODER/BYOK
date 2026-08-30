import io
import logging

from pypdf import PdfReader

from app.services.ingestion.errors import IngestionErrorCode, IngestionException
from app.services.ingestion.extractors.base import BaseExtractor, ExtractedSection

logger = logging.getLogger("app.services.ingestion.extractors.pdf")


class PDFExtractor(BaseExtractor):
    """Pure-Python page-by-page PDF text extractor with provenance tracking."""

    def extract(self, content: bytes) -> list[ExtractedSection]:
        if not content or len(content) == 0:
            raise IngestionException(
                message="PDF file content is empty.",
                code=IngestionErrorCode.EMPTY_DOCUMENT,
            )

        try:
            reader = PdfReader(io.BytesIO(content))
            sections: list[ExtractedSection] = []

            for page_idx, page in enumerate(reader.pages, start=1):
                try:
                    text = page.extract_text() or ""
                    if text.strip():
                        sections.append(
                            ExtractedSection(
                                text=text,
                                page_number=page_idx,
                                section_title=None,
                            )
                        )
                except Exception as page_exc:
                    logger.warning("Failed to extract page %d: %s", page_idx, str(page_exc))

            if not sections:
                raise IngestionException(
                    message="No extractable text found in PDF document.",
                    code=IngestionErrorCode.EMPTY_DOCUMENT,
                )

            return sections
        except IngestionException:
            raise
        except Exception as exc:
            logger.error("PDF extraction failed: %s", str(exc))
            raise IngestionException(
                message=f"Failed to extract text from PDF: {exc!s}",
                code=IngestionErrorCode.PDF_EXTRACTION_FAILED,
            ) from exc
