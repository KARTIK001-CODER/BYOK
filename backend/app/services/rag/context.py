from dataclasses import dataclass
from typing import Any

from app.core.config import get_settings
from app.services.retrieval.schemas import RetrievalResult


@dataclass(frozen=True)
class ContextChunkItem:
    """Structured context entry with provenance and citation index."""

    citation_id: int
    chunk_id: str
    document_id: str
    document_version_id: str
    document_name: str
    page_number: int | None
    section_title: str | None
    content: str
    score: float
    metadata: dict[str, Any] | None


@dataclass
class AssembledContext:
    """The formatted context string and corresponding citation source mappings."""

    formatted_context: str
    sources: list[ContextChunkItem]
    total_chunks_retrieved: int
    total_chunks_included: int
    estimated_tokens: int


class ContextBuilder:
    """Assembles ranked retrieval results into a token-budgeted, provenance-preserving context block."""

    def __init__(self, max_context_tokens: int | None = None) -> None:
        settings = get_settings()
        self.max_context_tokens = max_context_tokens or settings.MAX_CONTEXT_TOKENS

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Heuristic token estimation (~4 characters per token)."""
        return max(1, len(text) // 4)

    def assemble(
        self,
        retrieval_results: list[RetrievalResult],
        document_names: dict[str, str] | None = None,
    ) -> AssembledContext:
        """
        Assemble top-ranked retrieved chunks into a structured context block respecting token limits.

        Args:
            retrieval_results: Ranked list of retrieved chunks from RetrievalService.
            document_names: Optional dictionary mapping document_id -> document display name.

        Returns:
            AssembledContext with structured string and source index mappings.
        """
        doc_map = document_names or {}
        included_sources: list[ContextChunkItem] = []
        context_blocks: list[str] = []
        accumulated_chars = 0
        max_char_budget = self.max_context_tokens * 4

        if not retrieval_results:
            return AssembledContext(
                formatted_context="[NO RELEVANT KNOWLEDGE BASE CONTEXT AVAILABLE]",
                sources=[],
                total_chunks_retrieved=0,
                total_chunks_included=0,
                estimated_tokens=8,
            )

        for idx, result in enumerate(retrieval_results, start=1):
            doc_name = (
                doc_map.get(result.document_id)
                or (result.metadata.get("document_name") if result.metadata else None)
                or f"Document-{result.document_id[:8]}"
            )
            section = result.section_title or "General"
            page_str = str(result.page_number) if result.page_number is not None else "N/A"

            block_text = (
                f"[Source {idx}]\n"
                f"Document: {doc_name}\n"
                f"Section: {section}\n"
                f"Page: {page_str}\n\n"
                f"Content:\n{result.content.strip()}"
            )

            block_length = len(block_text) + 2  # including separator
            if accumulated_chars + block_length > max_char_budget and included_sources:
                # Context budget exceeded; exclude lower-ranked chunks
                break

            context_blocks.append(block_text)
            accumulated_chars += block_length

            item = ContextChunkItem(
                citation_id=idx,
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                document_version_id=result.document_version_id,
                document_name=doc_name,
                page_number=result.page_number,
                section_title=result.section_title,
                content=result.content,
                score=result.score,
                metadata=result.metadata,
            )
            included_sources.append(item)

        formatted_context = "\n\n---\n\n".join(context_blocks)
        estimated_tokens = self._estimate_tokens(formatted_context)

        return AssembledContext(
            formatted_context=formatted_context,
            sources=included_sources,
            total_chunks_retrieved=len(retrieval_results),
            total_chunks_included=len(included_sources),
            estimated_tokens=estimated_tokens,
        )
