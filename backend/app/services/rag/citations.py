import re

from app.services.rag.context import AssembledContext, ContextChunkItem
from app.services.rag.schemas import CitationItem


class CitationBuilder:
    """Extracts, validates, and builds structured citation metadata from generated answers."""

    # Matches bracket citation references like [1], [2], [1, 2], [1,2,3]
    CITATION_REGEX = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")

    @classmethod
    def extract_citation_ids(cls, text: str) -> list[int]:
        """Extract unique 1-indexed citation numbers mentioned in the answer text."""
        found_ids: set[int] = set()
        for match in cls.CITATION_REGEX.finditer(text):
            inner = match.group(1)
            parts = inner.split(",")
            for p in parts:
                try:
                    num = int(p.strip())
                    if num > 0:
                        found_ids.add(num)
                except ValueError:
                    continue
        return sorted(found_ids)

    @classmethod
    def build_citations(
        cls,
        answer_text: str,
        context: AssembledContext,
    ) -> list[CitationItem]:
        """
        Validate citation references in the generated answer against retrieved context sources.

        Args:
            answer_text: The LLM generated answer string containing [1], [2], etc.
            context: The AssembledContext with mapped ContextChunkItems.

        Returns:
            list[CitationItem]: Validated, structured citation objects.
        """
        source_map: dict[int, ContextChunkItem] = {src.citation_id: src for src in context.sources}

        referenced_ids = cls.extract_citation_ids(answer_text)
        citations: list[CitationItem] = []

        # If answer specifically references citation numbers, include them
        for cid in referenced_ids:
            source = source_map.get(cid)
            if source:
                content_preview = source.content.strip()
                if len(content_preview) > 200:
                    content_preview = content_preview[:197] + "..."

                citations.append(
                    CitationItem(
                        id=source.citation_id,
                        chunk_id=source.chunk_id,
                        document_id=source.document_id,
                        document_version_id=source.document_version_id,
                        document_name=source.document_name,
                        page_number=source.page_number,
                        section_title=source.section_title,
                        content_preview=content_preview,
                    )
                )

        # If the LLM didn't explicitly output brackets but valid context was used,
        # fallback to including the top-ranked sources that were in the context window
        if (
            not citations
            and context.sources
            and "I couldn't find enough information" not in answer_text
        ):
            for source in context.sources[:3]:
                content_preview = source.content.strip()
                if len(content_preview) > 200:
                    content_preview = content_preview[:197] + "..."
                citations.append(
                    CitationItem(
                        id=source.citation_id,
                        chunk_id=source.chunk_id,
                        document_id=source.document_id,
                        document_version_id=source.document_version_id,
                        document_name=source.document_name,
                        page_number=source.page_number,
                        section_title=source.section_title,
                        content_preview=content_preview,
                    )
                )

        return citations
