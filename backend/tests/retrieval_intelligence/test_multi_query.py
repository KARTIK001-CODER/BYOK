import asyncio
import time
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
async def test_multi_query_concurrent_execution(mocker):
    async def fake_search(session, organization_id, request):
        await asyncio.sleep(0.05)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=2,
            results=[_res(f"c_{request.query[:3]}_{i}", 0.9 - i * 0.1) for i in range(2)],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        side_effect=fake_search,
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True, max_expanded_queries=3)
    session = MagicMock()
    session.bind = None
    start = time.perf_counter()
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund policy details and pricing structure overview and handbook contents summary",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.MULTI_QUERY,
        config=cfg,
    )
    total = time.perf_counter() - start
    assert total < 0.25
    assert len(intel.query_variants) >= 2


@pytest.mark.asyncio
async def test_multi_query_deduplication(mocker):
    async def fake(session, organization_id, request):
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=2,
            results=[_res("dup_id", 0.9), _res(f"unique_{request.query[:2]}", 0.8)],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search", side_effect=fake
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True, max_expanded_queries=2)
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
    chunk_ids = [r.chunk_id for r in resp.results]
    assert len(chunk_ids) == len(set(chunk_ids))
    assert "dup_id" in chunk_ids
    assert resp.results[0].score >= resp.results[-1].score


@pytest.mark.asyncio
async def test_multi_query_tenant_isolation(mocker):
    captured_orgs = []

    async def fake(session, organization_id, request):
        captured_orgs.append(organization_id)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res("c1")],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search", side_effect=fake
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True)
    session = MagicMock()
    session.bind = None
    await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="tenant_123",
        query="a and b and c and d",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.MULTI_QUERY,
        config=cfg,
    )
    assert all(o == "tenant_123" for o in captured_orgs)
    assert len(captured_orgs) >= 1


@pytest.mark.asyncio
async def test_multi_query_respects_knowledge_base_filter(mocker):
    captured_kbs = []

    async def fake(session, organization_id, request):
        captured_kbs.append(request.knowledge_base_ids)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res("c1")],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search", side_effect=fake
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True)
    session = MagicMock()
    session.bind = None
    await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund and pricing",
        top_k=5,
        candidate_k=20,
        knowledge_base_ids=["kb1"],
        strategy_override=RetrievalStrategyType.MULTI_QUERY,
        config=cfg,
    )
    assert all(kb == ["kb1"] for kb in captured_kbs if kb is not None)
