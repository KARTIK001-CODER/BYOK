from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.services.ingestion.extractors.base import ExtractedSection


@dataclass
class RawChunk:
    """A generated chunk with textual content and origin provenance."""

    content: str
    page_number: int | None
    section_title: str | None
    character_count: int
    word_count: int


class BaseChunker(ABC):
    """Abstract chunker protocol."""

    @abstractmethod
    def chunk(self, sections: list[ExtractedSection]) -> list[RawChunk]:
        """
        Split a list of extracted sections into chunks with overlap.

        Returns:
            list[RawChunk]
        """
        pass
