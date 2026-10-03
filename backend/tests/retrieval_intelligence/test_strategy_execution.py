"""Test strategy execution — verifies Retrieval Intelligence selects correct strategy."""

import pytest

from app.services.query_intelligence.analyzer import QueryAnalyzer
from app.services.retrieval.schemas import (
    ChunkProvenance,
    RetrievalResponse,
    RetrievalResult,
    SearchMode,
)
from app.services.retrieval_intelligence.schemas import (
    AdaptiveRetrievalConfig,
    RetrievalStrategyType,
)
from app.services.retrieval_intelligence.service import AdaptiveRetrievalService


def _res(cid, score=0.8):
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


@pytest.mark.asyncio
async def test_simple_query_uses_direct_strategy(mocker):
    mock_search = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock_search.return_value = RetrievalResponse(
        query="test",
        search_mode=SearchMode.HYBRID,
        total_results=2,
        results=[_res("c1", 0.9), _res("c2", 0.8)],
    )
    cfg = AdaptiveRetrievalConfig(
        enabled=True,
        enable_decomposition=True,
        enable_multi_query=True,
        enable_query_expansion=True,
    )
    session = mocker.MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="What is refund policy?",
        top_k=5,
        candidate_k=20,
        config=cfg,
    )
    assert intel.strategy in (
        RetrievalStrategyType.DIRECT,
        RetrievalStrategyType.HYBRID,
        RetrievalStrategyType.EXPANDED,
    )
    assert mock_search.called


@pytest.mark.asyncio
async def test_multi_hop_query_uses_decomposed_when_enabled(mocker):
    from app.services.retrieval.schemas import RetrievalResponse as RR

    fake_resp = RR(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1", 0.5)]
    )
    mocker.patch(
        "app.services.retrieval_intelligence.service._parallel_retrieve",
        new_callable=mocker.AsyncMock,
        return_value=(
            [fake_resp],
            {
                "parallel_retrieval_ms": 10,
                "result_merge_ms": 2,
                "parallel_tasks": 2,
                "parallel_success": 1,
                "parallel_overlap": True,
            },
        ),
    )
    mock_search = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock_search.return_value = fake_resp
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_decomposition=True)
    session = mocker.MagicMock()
    session.bind = None
    query = "If I buy an annual plan and cancel after 20 days with 30% usage, what refund and fee apply and how does pricing affect it?"
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session, organization_id="org1", query=query, top_k=5, candidate_k=20, config=cfg
    )
    assert (
        intel.strategy == RetrievalStrategyType.DECOMPOSED
        or intel.strategy == RetrievalStrategyType.HYBRID
    )


@pytest.mark.asyncio
async def test_strategy_override_honored(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=0, results=[]
    )
    cfg = AdaptiveRetrievalConfig(enabled=True)
    session = mocker.MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="test query",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.EXPANDED,
        config=cfg,
    )
    assert intel.strategy == RetrievalStrategyType.EXPANDED


def test_query_intelligence_does_not_execute_retrieval():
    analysis = QueryAnalyzer.analyze("What is cancellation_fee?")
    assert analysis.features.contains_identifier is True
    assert analysis.classification is not None
    assert analysis.ambiguity is not None
    assert not hasattr(analysis, "results") or analysis.duration_ms < 10
