from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import get_settings
from app.services.rag.schemas import RAGChatRequest
from app.services.rag.service import RAGService
from app.services.retrieval.schemas import (
    ChunkProvenance,
    RetrievalResponse,
    RetrievalResult,
    SearchMode,
)
from app.services.retrieval_intelligence.schemas import (
    RetrievalConfidenceResult,
    RetrievalIntelligenceResult,
    RetrievalStrategyType,
)


def _res(cid, score=0.8, doc_name="Doc"):
    prov = ChunkProvenance(
        organization_id="org1",
        knowledge_base_id="kb1",
        document_id=f"doc_{cid}",
        document_name=doc_name,
        document_version_id="v1",
        chunk_id=cid,
        chunk_index=0,
    )
    return RetrievalResult(
        chunk_id=cid,
        document_id=f"doc_{cid}",
        document_name=doc_name,
        document_version_id="v1",
        knowledge_base_id="kb1",
        content=f"content {cid}",
        score=score,
        rank=1,
        source="hybrid",
        provenance=prov,
    )


@pytest.mark.asyncio
async def test_feature_flag_disabled_uses_hybrid(mocker):
    settings = get_settings()
    orig = settings.ENABLE_ADAPTIVE_RETRIEVAL
    settings.ENABLE_ADAPTIVE_RETRIEVAL = False
    try:
        mock_search = mocker.patch(
            "app.services.retrieval.service.RetrievalService.search", new_callable=AsyncMock
        )
        mock_search.return_value = MagicMock(
            results=[_res("c1")],
            trace=MagicMock(
                query_embedding_duration_ms=5,
                vector_search_duration_ms=10,
                keyword_search_duration_ms=8,
                fusion_duration_ms=2,
            ),
        )
        mock_adaptive = mocker.patch(
            "app.services.rag.service.AdaptiveRetrievalService.retrieve", new_callable=AsyncMock
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=MagicMock(id="conv1", knowledge_base_ids=["kb1"]),
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.add_message",
            new_callable=AsyncMock,
            side_effect=[MagicMock(id="user1"), MagicMock(id="assistant1")],
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.get_recent_messages",
            new_callable=AsyncMock,
            return_value=[],
        )
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.generate = AsyncMock(
            return_value=MagicMock(
                content="answer hi",
                usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        )
        mocker.patch(
            "app.services.rag.service.LLMProviderFactory.create",
            return_value=(mock_provider, "mock-model"),
        )
        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        svc = RAGService()
        req = RAGChatRequest(message="hello", top_k=5, search_mode="hybrid", provider="mock")
        resp = await svc.generate(
            session=session, organization_id="org1", user_id="user1", request=req
        )
        assert mock_search.called
        assert not mock_adaptive.called
        assert resp.answer == "answer hi"
    finally:
        settings.ENABLE_ADAPTIVE_RETRIEVAL = orig


@pytest.mark.asyncio
async def test_feature_flag_enabled_uses_adaptive(mocker):
    settings = get_settings()
    orig = settings.ENABLE_ADAPTIVE_RETRIEVAL
    settings.ENABLE_ADAPTIVE_RETRIEVAL = True
    try:
        fake_resp = RetrievalResponse(
            query="hello",
            search_mode=SearchMode.HYBRID,
            total_results=1,
            results=[_res("c1")],
            trace=None,
        )
        fake_intel = RetrievalIntelligenceResult(
            original_query="hello",
            strategy=RetrievalStrategyType.DIRECT,
            query_variants=["hello"],
            retrieval_attempts=1,
            candidate_count=1,
            final_result_count=1,
            retrieval_confidence=RetrievalConfidenceResult(
                confidence=0.8, strategy="DIRECT", reason="test"
            ),
            fallback_used=False,
            timings={
                "query_intelligence_ms": 1,
                "retrieval_strategy_selection_ms": 0.5,
                "parallel_retrieval_ms": 20,
                "result_merge_ms": 2,
                "adaptive_retry_ms": 0,
                "retrieval_total_ms": 25,
            },
        )
        mocker.patch(
            "app.services.rag.service.AdaptiveRetrievalService.retrieve",
            new_callable=AsyncMock,
            return_value=(fake_resp, fake_intel),
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=MagicMock(id="conv1", knowledge_base_ids=["kb1"]),
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.add_message",
            new_callable=AsyncMock,
            side_effect=[MagicMock(id="user1"), MagicMock(id="assistant1")],
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.get_recent_messages",
            new_callable=AsyncMock,
            return_value=[],
        )
        mock_provider = MagicMock()
        mock_provider.name = "mock"
        mock_provider.generate = AsyncMock(
            return_value=MagicMock(
                content="adaptive answer",
                usage=MagicMock(prompt_tokens=10, completion_tokens=5, total_tokens=15),
            )
        )
        mocker.patch(
            "app.services.rag.service.LLMProviderFactory.create",
            return_value=(mock_provider, "mock-model"),
        )
        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        svc = RAGService()
        req = RAGChatRequest(
            message="hello adaptive", top_k=5, search_mode="hybrid", provider="mock"
        )
        resp = await svc.generate(
            session=session, organization_id="org1", user_id="user1", request=req
        )
        assert resp.answer == "adaptive answer"
    finally:
        settings.ENABLE_ADAPTIVE_RETRIEVAL = orig


@pytest.mark.asyncio
async def test_streaming_preserves_citations(mocker):
    settings = get_settings()
    orig = settings.ENABLE_ADAPTIVE_RETRIEVAL
    settings.ENABLE_ADAPTIVE_RETRIEVAL = False
    try:
        mocker.patch(
            "app.services.retrieval.service.RetrievalService.search",
            new_callable=AsyncMock,
            return_value=MagicMock(results=[_res("c1", doc_name="Refund Policy")], trace=None),
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.get_or_create_conversation",
            new_callable=AsyncMock,
            return_value=MagicMock(id="conv1", knowledge_base_ids=["kb1"]),
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.add_message",
            new_callable=AsyncMock,
            side_effect=[MagicMock(id="user1"), MagicMock(id="assistant1")],
        )
        mocker.patch(
            "app.services.rag.service.ConversationService.get_recent_messages",
            new_callable=AsyncMock,
            return_value=[],
        )
        mock_provider = MagicMock()
        mock_provider.name = "mock"

        async def fake_stream(req):
            yield MagicMock(delta="hello ", usage=None)
            yield MagicMock(
                delta="world", usage=MagicMock(prompt_tokens=5, completion_tokens=2, total_tokens=7)
            )

        mock_provider.stream = fake_stream
        mocker.patch(
            "app.services.rag.service.LLMProviderFactory.create",
            return_value=(mock_provider, "mock-model"),
        )
        session = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()
        svc = RAGService()
        req = RAGChatRequest(message="test stream", top_k=5, search_mode="hybrid", provider="mock")
        events = []
        async for chunk in svc.stream_chat(
            session=session, organization_id="org1", user_id="user1", request=req
        ):
            events.append(chunk)
        combined = "".join(events)
        assert "event: token" in combined
        assert "event: citation" in combined or "event: done" in combined
    finally:
        settings.ENABLE_ADAPTIVE_RETRIEVAL = orig
