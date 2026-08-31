from app.services.rag.citations import CitationBuilder
from app.services.rag.context import ContextBuilder
from app.services.retrieval.schemas import ChunkProvenance, RetrievalResult


def _create_result(chunk_id: str, doc_id: str, doc_name: str) -> RetrievalResult:
    provenance = ChunkProvenance(
        organization_id="org-1",
        knowledge_base_id="kb-1",
        document_id=doc_id,
        document_version_id="ver-1",
        chunk_id=chunk_id,
        chunk_index=0,
        page_number=4,
        section_title="Security",
    )
    return RetrievalResult(
        chunk_id=chunk_id,
        document_id=doc_id,
        document_version_id="ver-1",
        knowledge_base_id="kb-1",
        content="JWT tokens expire after 15 minutes.",
        score=0.9,
        rank=1,
        source="hybrid",
        page_number=4,
        section_title="Security",
        metadata={"document_name": doc_name},
        provenance=provenance,
    )


def test_citation_extraction_and_mapping():
    """Test extracting valid [1], [2] citations and building structured metadata."""
    results = [
        _create_result("c1", "d1", "Auth Spec"),
        _create_result("c2", "d2", "DB Spec"),
    ]
    ctx = ContextBuilder().assemble(results)

    answer = "The system uses JWTs [1] and PostgreSQL [2]."
    citations = CitationBuilder.build_citations(answer, ctx)

    assert len(citations) == 2
    assert citations[0].id == 1
    assert citations[0].document_name == "Auth Spec"
    assert citations[0].page_number == 4
    assert citations[1].id == 2
    assert citations[1].document_name == "DB Spec"


def test_citation_out_of_bounds_rejected():
    """Test that nonexistent citation numbers like [999] are ignored and not mapped."""
    results = [_create_result("c1", "d1", "Auth Spec")]
    ctx = ContextBuilder().assemble(results)

    answer = "The system supports biometric MFA [999]."
    citations = CitationBuilder.build_citations(answer, ctx)

    # Citation [999] is invalid and not present in sources
    for c in citations:
        assert c.id != 999


def test_citation_multi_reference():
    """Test parsing multi-number brackets like [1, 2]."""
    ids = CitationBuilder.extract_citation_ids("Authentication is secure [1, 2, 3].")
    assert ids == [1, 2, 3]
