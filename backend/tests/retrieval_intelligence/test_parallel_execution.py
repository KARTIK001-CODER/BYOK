import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

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
from app.services.retrieval_intelligence.service import AdaptiveRetrievalService, _parallel_retrieve


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
        score=0.8,
        rank=1,
        source="hybrid",
        provenance=prov,
    )


@pytest.mark.asyncio
async def test_parallel_retrieve_overlap(mocker):
    async def fake_search(session, organization_id, request):
        await asyncio.sleep(0.08)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res(f"c_{request.query}")],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        side_effect=fake_search,
    )
    session = MagicMock()
    session.bind = None
    queries = ["q1 hello world extra", "q2 hello world extra", "q3 hello world extra"]
    start = time.perf_counter()
    responses, timings = await _parallel_retrieve(
        session=session,
        organization_id="org1",
        queries=queries,
        top_k=5,
        candidate_k=20,
        knowledge_base_ids=None,
        parallel_limit=3,
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 0.20, f"Not concurrent enough: {elapsed:.3f}s"
    assert timings["parallel_tasks"] == 3


@pytest.mark.asyncio
async def test_parallel_session_isolation(mocker):
    session = MagicMock()
    mock_bind = MagicMock()
    session.bind = mock_bind
    created = []

    class FakeMaker:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            s = MagicMock()
            created.append(s)
            return s

        async def __aexit__(self, *a):
            pass

    mocker.patch(
        "app.services.retrieval_intelligence.service.async_sessionmaker", return_value=FakeMaker
    )

    async def fake_search(session, organization_id, request):
        await asyncio.sleep(0.02)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res(f"c_{request.query}")],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        side_effect=fake_search,
    )
    queries = ["q1 hello", "q2 hello"]
    responses, timings = await _parallel_retrieve(
        session=session,
        organization_id="org1",
        queries=queries,
        top_k=5,
        candidate_k=20,
        knowledge_base_ids=None,
        parallel_limit=3,
    )
    assert len(created) == 2


@pytest.mark.asyncio
async def test_semaphore_limits_concurrency(mocker):
    async def fake_search(session, organization_id, request):
        await asyncio.sleep(0.05)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res(f"c_{request.query}")],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        side_effect=fake_search,
    )
    session = MagicMock()
    session.bind = None
    queries = ["q1 hello world", "q2 hello world", "q3 hello world"]
    start = time.perf_counter()
    responses, timings = await _parallel_retrieve(
        session=session,
        organization_id="org1",
        queries=queries,
        top_k=5,
        candidate_k=20,
        knowledge_base_ids=None,
        parallel_limit=1,
    )
    elapsed = time.perf_counter() - start
    assert elapsed >= 0.14
    assert timings["parallel_tasks"] == 3


@pytest.mark.asyncio
async def test_parallel_tenant_isolation(mocker):
    orgs = []

    async def fake_search(session, organization_id, request):
        orgs.append(organization_id)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res("c1")],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        side_effect=fake_search,
    )
    session = MagicMock()
    session.bind = None
    await _parallel_retrieve(
        session=session,
        organization_id="tenant_X",
        queries=["q1 hello world", "q2 hello world"],
        top_k=5,
        candidate_k=20,
        knowledge_base_ids=None,
        parallel_limit=3,
    )
    assert all(o == "tenant_X" for o in orgs)
    assert len(orgs) == 2


@pytest.mark.asyncio
async def test_adaptive_multi_query_uses_parallel(mocker):
    mock_parallel = mocker.patch(
        "app.services.retrieval_intelligence.service._parallel_retrieve", new_callable=AsyncMock
    )
    fake_resp = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
    )
    mock_parallel.return_value = (
        [fake_resp],
        {
            "parallel_retrieval_ms": 50,
            "result_merge_ms": 2,
            "parallel_tasks": 2,
            "parallel_success": 2,
            "parallel_overlap": True,
        },
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_multi_query=True, max_expanded_queries=3)
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
    assert mock_parallel.called
    assert intel.timings.get("parallel_retrieval_ms", 0) > 0
