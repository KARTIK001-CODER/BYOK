import io
import logging

from docx import Document as DocxDocument

from app.services.ingestion.errors import IngestionErrorCode, IngestionException
from app.services.ingestion.extractors.base import BaseExtractor, ExtractedSection

logger = logging.getLogger("app.services.ingestion.extractors.docx")


class DOCXExtractor(BaseExtractor):
    """Microsoft Word DOCX extractor using python-docx with heading structure detection."""

    def extract(self, content: bytes) -> list[ExtractedSection]:
        if not content or len(content) == 0:
            raise IngestionException(
                message="DOCX file content is empty.",
                code=IngestionErrorCode.EMPTY_DOCUMENT,
            )

        try:
            doc = DocxDocument(io.BytesIO(content))
            sections: list[ExtractedSection] = []
            current_title: str | None = None
            current_paragraphs: list[str] = []

            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if not text:
                    continue

                style_name = paragraph.style.name.lower() if paragraph.style else ""
                if "heading" in style_name or "title" in style_name:
                    # Flush previous section
                    if current_paragraphs:
                        section_text = "\n\n".join(current_paragraphs).strip()
                        if section_text:
                            sections.append(
                                ExtractedSection(
                                    text=section_text,
                                    page_number=None,
                                    section_title=current_title,
                                )
                            )
                        current_paragraphs = []
                    current_title = text
                    current_paragraphs.append(text)
                else:
                    current_paragraphs.append(text)

            # Flush trailing paragraphs
            if current_paragraphs:
                section_text = "\n\n".join(current_paragraphs).strip()
                if section_text:
                    sections.append(
                        ExtractedSection(
                            text=section_text,
                            page_number=None,
                            section_title=current_title,
                        )
                    )

            if not sections:
                raise IngestionException(
                    message="No extractable text found in DOCX document.",
                    code=IngestionErrorCode.EMPTY_DOCUMENT,
                )

            return sections
        except IngestionException:
            raise
        except Exception as exc:
            logger.error("DOCX extraction failed: %s", str(exc))
            raise IngestionException(
                message=f"Failed to extract text from DOCX document: {exc!s}",
                code=IngestionErrorCode.DOCX_EXTRACTION_FAILED,
            ) from exc
