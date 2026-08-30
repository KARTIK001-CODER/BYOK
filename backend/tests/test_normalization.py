from app.services.ingestion.normalization import TextNormalizer


def test_normalize_line_endings() -> None:
    """Verify CRLF and CR are converted to LF."""
    raw_text = "Line 1\r\nLine 2\rLine 3\nLine 4"
    normalized = TextNormalizer.normalize(raw_text)
    assert "\r" not in normalized
    assert normalized == "Line 1\nLine 2\nLine 3\nLine 4"


def test_normalize_control_characters_and_null_bytes() -> None:
    """Verify null bytes and control characters are stripped."""
    raw_text = "Clean text\x00 with hidden \x07bell and \x1b escape code."
    normalized = TextNormalizer.normalize(raw_text)
    assert "\x00" not in normalized
    assert "\x07" not in normalized
    assert "\x1b" not in normalized
    assert normalized == "Clean text with hidden bell and escape code."


def test_normalize_excessive_whitespace_and_blank_lines() -> None:
    """Verify multiple blank lines are compressed to max 2 (\n\n)."""
    raw_text = "Paragraph 1\n\n\n\n\nParagraph 2   \n\n\nParagraph 3"
    normalized = TextNormalizer.normalize(raw_text)
    assert "\n\n\n" not in normalized
    assert normalized == "Paragraph 1\n\nParagraph 2\n\nParagraph 3"


def test_word_and_character_counting() -> None:
    """Verify exact word and character counts."""
    text = "RAGForge is a scalable RAG engine."
    assert TextNormalizer.count_words(text) == 6
    assert TextNormalizer.count_characters(text) == len(text)
    assert TextNormalizer.count_words("") == 0
    assert TextNormalizer.count_characters("") == 0
