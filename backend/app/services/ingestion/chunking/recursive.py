from app.core.config import get_settings
from app.services.ingestion.chunking.base import BaseChunker, RawChunk
from app.services.ingestion.extractors.base import ExtractedSection
from app.services.ingestion.normalization import TextNormalizer


class RecursiveTextChunker(BaseChunker):
    """
    Production-grade recursive text chunker.
    Splits text hierarchically across paragraph, sentence, and word boundaries.
    """

    DEFAULT_SEPARATORS = ["\n\n", "\n", ". ", "! ", "? ", "; ", " ", ""]

    def __init__(
        self,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        separators: list[str] | None = None,
    ) -> None:
        settings = get_settings()
        self.chunk_size = chunk_size if chunk_size is not None else settings.CHUNK_SIZE
        self.chunk_overlap = chunk_overlap if chunk_overlap is not None else settings.CHUNK_OVERLAP
        self.separators = separators or self.DEFAULT_SEPARATORS

        if self.chunk_size <= 0:
            raise ValueError("chunk_size must be greater than 0")
        if self.chunk_overlap < 0 or self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be non-negative and less than chunk_size")

    def _split_text(self, text: str, separators: list[str]) -> list[str]:
        """Recursively split text by first matching separator."""
        final_chunks: list[str] = []
        separator = separators[-1]
        new_separators: list[str] = []

        for idx, sep in enumerate(separators):
            if sep == "":
                separator = ""
                break
            if sep in text:
                separator = sep
                new_separators = separators[idx + 1 :]
                break

        splits = text.split(separator) if separator else list(text)
        good_splits: list[str] = []

        for s in splits:
            if not s:
                continue
            if len(s) < self.chunk_size:
                good_splits.append(s)
            else:
                if good_splits:
                    merged = self._merge_splits(good_splits, separator)
                    final_chunks.extend(merged)
                    good_splits = []
                if not new_separators:
                    final_chunks.append(s[: self.chunk_size])
                else:
                    other_chunks = self._split_text(s, new_separators)
                    final_chunks.extend(other_chunks)

        if good_splits:
            merged = self._merge_splits(good_splits, separator)
            final_chunks.extend(merged)

        return final_chunks

    def _merge_splits(self, splits: list[str], separator: str) -> list[str]:
        """Combine split fragments into chunks respecting chunk_size and chunk_overlap."""
        docs: list[str] = []
        current_doc: list[str] = []
        total = 0

        for d in splits:
            _len = len(d) + (len(separator) if current_doc else 0)
            if total + _len > self.chunk_size:
                if total > self.chunk_size:
                    pass
                if current_doc:
                    doc = separator.join(current_doc).strip()
                    if doc:
                        docs.append(doc)
                    # Handle overlap
                    while total > self.chunk_overlap or (
                        total + _len > self.chunk_size and total > 0
                    ):
                        popped = current_doc.pop(0)
                        total -= len(popped) + (len(separator) if current_doc else 0)
                        if not current_doc:
                            break

            current_doc.append(d)
            total += len(d) + (len(separator) if len(current_doc) > 1 else 0)

        if current_doc:
            doc = separator.join(current_doc).strip()
            if doc:
                docs.append(doc)

        return docs

    def chunk(self, sections: list[ExtractedSection]) -> list[RawChunk]:
        """Process extracted sections into chunks while preserving provenance."""
        chunks: list[RawChunk] = []

        for section in sections:
            normalized_text = TextNormalizer.normalize(section.text)
            if not normalized_text:
                continue

            if len(normalized_text) <= self.chunk_size:
                chunks.append(
                    RawChunk(
                        content=normalized_text,
                        page_number=section.page_number,
                        section_title=section.section_title,
                        character_count=len(normalized_text),
                        word_count=TextNormalizer.count_words(normalized_text),
                    )
                )
            else:
                raw_pieces = self._split_text(normalized_text, self.separators)
                for piece in raw_pieces:
                    cleaned_piece = piece.strip()
                    if cleaned_piece:
                        chunks.append(
                            RawChunk(
                                content=cleaned_piece,
                                page_number=section.page_number,
                                section_title=section.section_title,
                                character_count=len(cleaned_piece),
                                word_count=TextNormalizer.count_words(cleaned_piece),
                            )
                        )

        return chunks
