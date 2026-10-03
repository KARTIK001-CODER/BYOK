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
)
from app.services.retrieval_intelligence.service import AdaptiveRetrievalService


def _res(cid, score):
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
async def test_high_confidence_no_retry(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q",
        search_mode=SearchMode.HYBRID,
        total_results=2,
        results=[_res("c1", 0.9), _res("c2", 0.75)],
    )
    cfg = AdaptiveRetrievalConfig(
        enabled=True,
        enable_failure_detection=True,
        max_retrieval_attempts=2,
        enable_query_expansion=True,
    )
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="What is refund policy?",
        top_k=5,
        candidate_k=20,
        config=cfg,
    )
    assert intel.retrieval_attempts == 1
    assert intel.timings.get("retry_triggered", 0) == 0


@pytest.mark.asyncio
async def test_low_confidence_retry_triggered(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    first = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1", 0.2)]
    )
    second = RetrievalResponse(
        query="q expanded",
        search_mode=SearchMode.HYBRID,
        total_results=1,
        results=[_res("c2", 0.8)],
    )
    mock.side_effect = [first, second]
    mocker.patch(
        "app.services.retrieval_intelligence.service.expansion_rule_based",
        return_value=MagicMock(expanded_terms=["term"], expanded_query="q expanded"),
    )
    cfg = AdaptiveRetrievalConfig(
        enabled=True,
        enable_failure_detection=True,
        enable_query_expansion=True,
        max_retrieval_attempts=2,
    )
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session, organization_id="org1", query="refund", top_k=5, candidate_k=20, config=cfg
    )
    assert mock.call_count >= 1


@pytest.mark.asyncio
async def test_max_attempts_never_exceeded(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1", 0.1)]
    )
    mocker.patch(
        "app.services.retrieval_intelligence.service.expansion_rule_based",
        return_value=MagicMock(expanded_terms=["a"], expanded_query="q a"),
    )
    cfg = AdaptiveRetrievalConfig(
        enabled=True,
        enable_failure_detection=True,
        enable_query_expansion=True,
        max_retrieval_attempts=2,
    )
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session,
        organization_id="org1",
        query="refund pricing",
        top_k=5,
        candidate_k=20,
        config=cfg,
    )
    assert intel.retrieval_attempts <= 2


@pytest.mark.asyncio
async def test_retry_disabled_no_retry(mocker):
    mock = mocker.patch(
        "app.services.retrieval_intelligence.service.RetrievalService.search",
        new_callable=mocker.AsyncMock,
    )
    mock.return_value = RetrievalResponse(
        query="q", search_mode=SearchMode.HYBRID, total_results=1, results=[_res("c1", 0.2)]
    )
    cfg = AdaptiveRetrievalConfig(enabled=True, enable_failure_detection=False)
    session = MagicMock()
    session.bind = None
    resp, intel = await AdaptiveRetrievalService.retrieve(
        session=session, organization_id="org1", query="refund", top_k=5, candidate_k=20, config=cfg
    )
    assert mock.call_count == 1
