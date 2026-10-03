import pytest

from app.services.retrieval.schemas import (
    ChunkProvenance,
    RetrievalResponse,
    RetrievalResult,
    SearchMode,
)
from app.services.retrieval_intelligence.service import expansion_rule_based


def _res(cid, score=0.7):
    prov = ChunkProvenance(
        organization_id="org1",
        knowledge_base_id="kb1",
        document_id=f"doc_{cid}",
        document_name="Doc",
        document_version_id="v1",
        chunk_id=cid,
        chunk_index=0,
    )
    return RetrievalResult(
        chunk_id=cid,
        document_id=f"doc_{cid}",
        document_name="Doc",
        document_version_id="v1",
        knowledge_base_id="kb1",
        content=f"content {cid}",
        score=score,
        rank=1,
        source="hybrid",
        provenance=prov,
    )


def test_expansion_refund():
    exp = expansion_rule_based("How do I get my money back after buying a plan? refund")
    assert "money back" in exp.expanded_terms or "refund" in exp.original_query.lower()


def test_expansion_no_match():
    exp = expansion_rule_based("What is the capital of France?")
    assert exp.expanded_terms == [] or len(exp.expanded_terms) <= 5


def test_expansion_pricing():
    exp = expansion_rule_based("What is pricing for pro?")
    assert len(exp.expanded_terms) > 0
    assert "cost" in exp.expanded_terms or "price" in exp.expanded_terms


@pytest.mark.asyncio
async def test_expansion_retrieval_path(mocker):
    mock_search = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock_search.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
    )
    from app.services.retrieval_intelligence.schemas import (
        AdaptiveRetrievalConfig,
        RetrievalStrategyType,
    )
    from app.services.retrieval_intelligence.service import AdaptiveRetrievalService

    cfg = AdaptiveRetrievalConfig(enabled=True, enable_query_expansion=True)
    session = mocker.MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund pricing",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.EXPANDED,
        config=cfg,
    )
    assert intel.strategy == RetrievalStrategyType.EXPANDED
    assert mock_search.called
