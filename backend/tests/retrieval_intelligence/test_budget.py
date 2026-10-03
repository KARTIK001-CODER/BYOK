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


def _res(cid):
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
        score=0.5,
        rank=1,
        source="hybrid",
        provenance=prov,
    )


@pytest.mark.asyncio
async def test_budget_exceeded_fallback(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
    )
    cfg = AdaptiveRetrievalConfig(
        enabled=True,
        enable_multi_query=True,
        max_expanded_queries=3,
        max_total_candidates=5,
        max_retrieval_attempts=2,
        max_sub_queries=3,
        simple_top_k=5,
        simple_candidate_k=10,
        complex_top_k=5,
        complex_candidate_k=10,
    )
    session = MagicMock()
    session.bind = None
    # query with enough parts to trigger 3 variants -> 3*10=30 >5 budget
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund policy details and pricing structure overview and handbook contents summary and trial period details",
        top_k=5,
        candidate_k=10,
        strategy_override=RetrievalStrategyType.MULTI_QUERY,
        config=cfg,
    )
    assert intel.fallback_used is True or intel.timings.get("budget_exceeded") == 1.0
    assert resp is not None


@pytest.mark.asyncio
async def test_candidate_k_within_budget(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
    )
    cfg = AdaptiveRetrievalConfig(
        enabled=True, enable_multi_query=True, max_total_candidates=100, max_expanded_queries=3
    )
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund and pricing",
        top_k=5,
        candidate_k=10,
        strategy_override=RetrievalStrategyType.MULTI_QUERY,
        config=cfg,
    )
    assert intel.timings.get("budget_exceeded", 0) == 0


def test_budget_config_exists():
    from app.core.config import get_settings

    s = get_settings()
    assert hasattr(s, "MAX_RETRIEVAL_ATTEMPTS")
    assert hasattr(s, "MAX_PARALLEL_RETRIEVAL_QUERIES")
    assert hasattr(s, "MAX_EXPANDED_QUERIES")
    assert hasattr(s, "MAX_DECOMPOSED_QUERIES")
    assert hasattr(s, "MAX_TOTAL_CANDIDATES")
