from unittest.mock import MagicMock

import pytest

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


def _res(cid, score=0.5):
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
async def test_multi_query_failure_fallback_to_hybrid(mocker):
    mocker.patch(
        "app.services.retrieval_intelligence.service._parallel_retrieve",
        side_effect=Exception("parallel fail"),
    )
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1", 0.7)]
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True)
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund and pricing",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.MULTI_QUERY,
        config=cfg,
    )
    assert intel.fallback_used is True
    assert len(resp.results) >= 1


@pytest.mark.asyncio
async def test_expansion_failure_fallback(mocker):
    mocker.patch(
        "app.services.retrieval_intelligence.service.expansion_rule_based",
        side_effect=Exception("expansion fail"),
    )
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_query_expansion=True)
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.EXPANDED,
        config=cfg,
    )
    assert resp is not None


@pytest.mark.asyncio
async def test_adaptive_service_failure_fallback_to_normal(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.side_effect = [
        Exception("first fail"),
        RetrievalResponse(
            query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
        ),
    ]
    cfg = AdaptiveRetrievalConfig(enabled=True)
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="test query",
        top_k=5,
        candidate_k=20,
        config=cfg,
    )
    assert resp is not None
    assert intel.fallback_used is True


@pytest.mark.asyncio
async def test_decomposition_failure_fallback(mocker):
    mocker.patch(
        "app.services.retrieval_intelligence.service.decompose_rule_based",
        side_effect=Exception("decompose fail"),
    )
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_decomposition=True)
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="compare refund and pricing",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.DECOMPOSED,
        config=cfg,
    )
    assert resp is not None
