import logging
import re

from app.services.ingestion.errors import IngestionErrorCode, IngestionException
from app.services.ingestion.extractors.base import BaseExtractor, ExtractedSection

logger = logging.getLogger("app.services.ingestion.extractors.markdown")


class MarkdownExtractor(BaseExtractor):
    """Structure-aware Markdown extractor detecting headings and section titles."""

    def extract(self, content: bytes) -> list[ExtractedSection]:
        if not content or len(content) == 0:
            raise IngestionException(
                message="Markdown file content is empty.",
                code=IngestionErrorCode.EMPTY_DOCUMENT,
            )

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")

        if not text.strip():
            raise IngestionException(
                message="Markdown document contains no extractable content.",
                code=IngestionErrorCode.EMPTY_DOCUMENT,
            )

        # Detect Markdown headings (# Header, ## Subheader)
        sections: list[ExtractedSection] = []
        current_title: str | None = None
        current_lines: list[str] = []

        heading_pattern = re.compile(r"^(#{1,6})\s+(.+)$")

        for line in text.splitlines():
            match = heading_pattern.match(line.strip())
            if match:
                # Flush previous block if exists
                if current_lines:
                    block_text = "\n".join(current_lines).strip()
                    if block_text:
                        sections.append(
                            ExtractedSection(
                                text=block_text,
                                page_number=None,
                                section_title=current_title,
                            )
                        )
                    current_lines = []
                current_title = match.group(2).strip()
                current_lines.append(line)
            else:
                current_lines.append(line)

        if current_lines:
            block_text = "\n".join(current_lines).strip()
            if block_text:
                sections.append(
                    ExtractedSection(
                        text=block_text,
                        page_number=None,
                        section_title=current_title,
                    )
                )

        if not sections:
            return [ExtractedSection(text=text, page_number=None, section_title=None)]

        return sections
