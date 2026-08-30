import re


class TextNormalizer:
    """Text normalization service for retrieval-friendly representations."""

    # Regular expressions for cleaning
    _NULL_AND_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]")
    _EXCESSIVE_NEWLINES = re.compile(r"\n{3,}")
    _LINE_TRAILING_SPACES = re.compile(r"[ \t]+$", re.MULTILINE)
    _EXCESSIVE_HORIZONTAL_SPACES = re.compile(r"[^\S\r\n]{2,}")

    @classmethod
    def normalize(cls, text: str) -> str:
        """
        Clean and normalize raw extracted text:
        1. Convert CRLF / CR -> LF
        2. Strip null and non-printable control characters
        3. Compress trailing whitespace per line
        4. Compress multiple blank lines to at most two (\n\n)
        5. Trim leading and trailing whitespace
        """
        if not text:
            return ""

        # 1. Normalize line endings
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # 2. Strip null and control characters
        text = cls._NULL_AND_CONTROL_CHARS.sub("", text)

        # 3. Clean line whitespace
        text = cls._LINE_TRAILING_SPACES.sub("", text)

        # 4. Collapse runs of spaces (not newlines)
        text = cls._EXCESSIVE_HORIZONTAL_SPACES.sub(" ", text)

        # 5. Collapse excessive blank lines
        text = cls._EXCESSIVE_NEWLINES.sub("\n\n", text)

        return text.strip()

    @staticmethod
    def count_words(text: str) -> int:
        """Calculate word count for normalized text."""
        if not text:
            return 0
        return len(text.split())

    @staticmethod
    def count_characters(text: str) -> int:
        """Calculate character count for normalized text."""
        return len(text)
