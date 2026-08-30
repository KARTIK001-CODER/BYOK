from app.services.ingestion.chunking.recursive import RecursiveTextChunker
from app.services.ingestion.extractors.base import ExtractedSection


def test_chunker_small_text_single_chunk() -> None:
    """Verify small text under chunk_size produces exactly 1 chunk."""
    chunker = RecursiveTextChunker(chunk_size=500, chunk_overlap=50)
    sections = [
        ExtractedSection(
            text="Short document with a single paragraph.",
            page_number=1,
            section_title="Intro",
        )
    ]
    chunks = chunker.chunk(sections)
    assert len(chunks) == 1
    assert chunks[0].content == "Short document with a single paragraph."
    assert chunks[0].page_number == 1
    assert chunks[0].section_title == "Intro"
    assert chunks[0].character_count == len(chunks[0].content)
    assert chunks[0].word_count == 6


def test_chunker_large_text_multiple_chunks_with_overlap() -> None:
    """Verify large text is split into chunks respecting chunk_size and chunk_overlap."""
    chunker = RecursiveTextChunker(chunk_size=100, chunk_overlap=20)
    long_text = (
        "Paragraph one contains important introductory details. "
        "Paragraph two continues with architectural foundations. "
        "Paragraph three adds security rules and tenant boundaries."
    )
    sections = [ExtractedSection(text=long_text, page_number=2, section_title="Architecture")]
    chunks = chunker.chunk(sections)

    assert len(chunks) > 1
    for c in chunks:
        assert len(c.content) <= 120  # bounded by chunk size
        assert c.page_number == 2
        assert c.section_title == "Architecture"
        assert c.character_count == len(c.content)
        assert c.word_count > 0


def test_chunker_deterministic_output() -> None:
    """Verify chunking the same text twice generates identical chunks."""
    chunker = RecursiveTextChunker(chunk_size=150, chunk_overlap=30)
    sample_text = (
        "RAGForge is built with FastAPI and PostgreSQL pgvector. "
        "It supports multi-tenancy, RBAC, and document versioning. "
        "Each chunk preserves provenance and source page number."
    )
    sections = [ExtractedSection(text=sample_text, page_number=1, section_title="Overview")]

    run1 = chunker.chunk(sections)
    run2 = chunker.chunk(sections)

    assert len(run1) == len(run2)
    for c1, c2 in zip(run1, run2, strict=False):
        assert c1.content == c2.content
        assert c1.character_count == c2.character_count
        assert c1.word_count == c2.word_count
