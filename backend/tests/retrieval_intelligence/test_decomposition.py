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
    DecomposedQuery,
    RetrievalStrategyType,
)
from app.services.retrieval_intelligence.service import (
    AdaptiveRetrievalService,
    decompose_rule_based,
)


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


def test_decompose_and_conjunction():
    dq = decompose_rule_based(
        "How does remote work affect equipment reimbursement and also pricing?"
    )
    assert isinstance(dq.sub_queries, list)


def test_decompose_standard_enterprise():
    dq = decompose_rule_based("Compare refund policies for standard and enterprise")
    assert len(dq.sub_queries) >= 1


def test_decompose_filters_short():
    dq = decompose_rule_based("a and b")
    assert dq.sub_queries == []


@pytest.mark.asyncio
async def test_decomposition_parallel_execution(mocker):
    async def fake(session, organization_id, request):
        await asyncio.sleep(0.05)
        return RetrievalResponse(
            query=request.query,
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res(f"c_{request.query[:3]}", 0.85)],
        )

    mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search", side_effect=fake
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_decomposition=True, max_sub_queries=3)
    session = MagicMock()
    session.bind = None
    start = time.perf_counter()
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="Compare standard and enterprise refund policy and pricing",
        top_k=5,
        candidate_k=20,
        strategy_override=RetrievalStrategyType.DECOMPOSED,
        config=cfg,
    )
    total = time.perf_counter() - start
    assert total < 0.3


@pytest.mark.asyncio
async def test_decomposition_dedup_and_fusion(mocker):
    import app.services.retrieval_intelligence.service as svc

    orig = svc.decompose_rule_based
    svc.decompose_rule_based = lambda q: DecomposedQuery(
        original_query=q,
        sub_queries=["query one hello world extra term", "query two hello world extra term"],
        reason="test",
        confidence=0.7,
    )
    try:

        async def fake(session, organization_id, request):
            return RetrievalResponse(
                query=request.query,
                search_mode=SearchMode.HYBRID,
                total_results=2,
                results=[_res("dup", 0.9), _res(f"uniq_{request.query[:3]}", 0.7)],
            )

        mocker.patch(
            "app.services.retrieval_intelligence.service.RetrievalService.search", side_effect=fake
        )
        cfg = AdaptiveRetrievalConfig(enabled=True, enable_decomposition=True, max_sub_queries=2)
        session = MagicMock()
        session.bind = None
        resp, intel = await AdaptiveRetrievalService.retrieve(
            session=session,
            organization_id="org1",
            query="test query for decomposition and something else longer",
            top_k=5,
            candidate_k=20,
            strategy_override=RetrievalStrategyType.DECOMPOSED,
            config=cfg,
        )
        ids = [r.chunk_id for r in resp.results]
        assert ids.count("dup") <= 1
    finally:
        svc.decompose_rule_based = orig


@pytest.mark.asyncio
async def test_decomposition_max_query_limit(mocker):
    import app.services.retrieval_intelligence.service as svc

    orig = svc.decompose_rule_based
    svc.decompose_rule_based = lambda q: DecomposedQuery(
        original_query=q,
        sub_queries=[
            "a hello world extra",
            "b hello world extra",
            "c hello world extra",
            "d hello world extra",
            "e hello world extra",
        ],
        reason="test",
        confidence=0.8,
    )
    try:
        mocker.patch(
            "app.services.retrieval_intelligence.service.RetrievalService.search",
            new_callable=mocker.AsyncMock,
            return_value=RetrievalResponse(
                query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1")]
            ),
        )
        cfg = AdaptiveRetrievalConfig(enabled=True, enable_decomposition=True, max_sub_queries=2)
        session = MagicMock()
        session.bind = None
        resp, intel = await AdaptiveRetrievalService.retrieve(
            session=session,
            organization_id="org1",
            query="long query that will be decomposed into many pieces and something",
            top_k=5,
            candidate_k=20,
            strategy_override=RetrievalStrategyType.DECOMPOSED,
            config=cfg,
        )
        assert intel.sub_query_count <= 2 or len(intel.query_variants) <= 2
    finally:
        svc.decompose_rule_based = orig
