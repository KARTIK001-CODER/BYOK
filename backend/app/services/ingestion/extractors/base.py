from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ExtractedSection:
    """Extracted text unit with provenance context (page number and section title)."""

    text: str
    page_number: int | None = None
    section_title: str | None = None


class BaseExtractor(ABC):
    """Abstract interface for format-specific document extractors."""

    @abstractmethod
    def extract(self, content: bytes) -> list[ExtractedSection]:
        """
        Extract text sections from raw document bytes.

        Returns:
            list[ExtractedSection]
        """
        pass
