import asyncio
import contextlib
import json
import logging
import sys
import time
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.models.message import MessageRole
from app.services.llm.base import LLMRequest
from app.services.llm.errors import LLMException
from app.services.llm.factory import LLMProviderFactory
from app.services.rag.citations import CitationBuilder
from app.services.rag.context import ContextBuilder
from app.services.rag.conversations import ConversationService
from app.services.rag.prompt import PromptBuilder
from app.services.rag.schemas import (
    RAGChatRequest,
    RAGChatResponse,
    RetrievalSummary,
)
from app.services.retrieval.arxiv_client import ArxivClient
from app.services.retrieval.errors import RetrievalException
from app.services.retrieval.schemas import RetrievalRequest, SearchMode
from app.services.retrieval.service import RetrievalService
from app.services.retrieval_intelligence.service import AdaptiveRetrievalService

logger = logging.getLogger("app.services.rag.service")


class RAGService:
    """Core service orchestrating Hybrid Retrieval, Context Assembly, and Generation."""

    def __init__(
        self,
        context_builder: ContextBuilder | None = None,
        prompt_builder: PromptBuilder | None = None,
        citation_builder: CitationBuilder | None = None,
    ) -> None:
        self.context_builder = context_builder or ContextBuilder()
        self.prompt_builder = prompt_builder or PromptBuilder()
        self.citation_builder = citation_builder or CitationBuilder()

    async def generate(
        self,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        request: RAGChatRequest,
    ) -> RAGChatResponse:
        """
        Execute synchronous end-to-end RAG generation.
        Returns RAGChatResponse with generated answer, validated citations, and metadata.
        """
        trace = get_current_trace()
        try:
            return await self._generate_internal(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                request=request,
            )
        except LLMException as exc:
            if trace:
                trace.add_error(f"LLMException {exc.code}: {exc.message}")
                trace.emit_performance_summary(outcome="FAILED", error_category=f"LLM_{exc.code.upper()}")
            raise
        except RetrievalException as exc:
            if trace:
                code_name = exc.code.name if hasattr(exc.code, "name") else str(exc.code)
                trace.add_error(f"RetrievalException {code_name}: {exc.message}")
                trace.emit_performance_summary(outcome="FAILED", error_category=f"RETRIEVAL_{code_name.upper()}")
            raise
        except asyncio.CancelledError:
            if trace:
                trace.emit_performance_summary(outcome="CANCELLED", error_category="CLIENT_DISCONNECT")
            raise
        except Exception as exc:
            if trace:
                trace.add_error(str(exc))
                trace.emit_performance_summary(outcome="FAILED", error_category="INTERNAL_ERROR")
            raise
        finally:
            if trace and not trace._summary_emitted:
                trace.emit_performance_summary(outcome=trace.outcome or "UNKNOWN")

    async def _generate_internal(
        self,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        request: RAGChatRequest,
    ) -> RAGChatResponse:
        total_start = time.perf_counter()
        trace = get_current_trace()
        if trace:
            trace.mark("rag_generate_start")
            prep_t0 = time.perf_counter()
            normalized_query = request.message.strip()
            prep_ms = (time.perf_counter() - prep_t0) * 1000.0
            trace.record("query_preprocessing_ms", prep_ms)
            trace.record("query_normalization_ms", prep_ms)
            trace.set_counter("query_length", len(normalized_query))
        settings = get_settings()

        # 1. Fetch or create conversation
        conv_t0 = time.perf_counter()
        conv = await ConversationService.get_or_create_conversation(
            session=session,
            organization_id=organization_id,
            user_id=user_id,
            conversation_id=request.conversation_id,
            initial_query=request.message,
            knowledge_base_ids=request.knowledge_base_ids,
            flush=False,
        )
        conv_ms = (time.perf_counter() - conv_t0) * 1000.0
        if trace:
            trace.record("conversation_lookup_ms", conv_ms)
            trace.mark("conversation_done")
            trace.set_counter("conversation_id", conv.id)

        # 2. Persist user message
        persist_user_t0 = time.perf_counter()
        user_msg = await ConversationService.add_message(
            session=session,
            conversation_id=conv.id,
            role=MessageRole.USER,
            content=request.message,
            flush=False,
        )
        persist_user_ms = (time.perf_counter() - persist_user_t0) * 1000.0
        if trace:
            trace.record("user_message_persist_ms", persist_user_ms)

        # 3. Retrieve context chunks — router: Adaptive vs Hybrid (Phase 2.5 integration, feature flagged)
        kb_scope = request.knowledge_base_ids or conv.knowledge_base_ids
        candidate_k = max(request.top_k * 4, 30)

        # 6 (early). Start history fetch on an isolated session so its DB round
        # trip overlaps retrieval I/O below. Isolated session is required because
        # AsyncSession is not safe for concurrent use. Correctness: for a new
        # conversation there is no committed history ([] is correct); for an
        # existing one only the uncommitted current user message is invisible,
        # and it is excluded by id filter anyway.
        async def _load_history_early() -> tuple[list, float]:
            if request.conversation_id is None:
                return [], 0.0
            hist_inner_t0 = time.perf_counter()
            hist_maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
            async with hist_maker() as hist_session:
                msgs = await ConversationService.get_recent_messages(
                    session=hist_session,
                    conversation_id=conv.id,
                    limit=settings.MAX_HISTORY_MESSAGES + 1,
                )
            return msgs, (time.perf_counter() - hist_inner_t0) * 1000.0

        history_task = asyncio.create_task(_load_history_early())
        # If retrieval below raises, consume a late history failure so it never
        # surfaces as "Task exception was never retrieved".
        history_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
        retrieval_start = time.perf_counter()
        if trace:
            trace.mark("retrieval_start")
        retrieval_resp = None
        retrieval_intel = None
        if settings.ENABLE_ADAPTIVE_RETRIEVAL:
            try:
                # Retrieval Intelligence path: Query Intelligence -> Retrieval Intelligence -> Retrieval Engine
                retrieval_resp, retrieval_intel = await AdaptiveRetrievalService.retrieve(
                    session=session,
                    organization_id=organization_id,
                    query=request.message,
                    top_k=request.top_k,
                    candidate_k=candidate_k,
                    knowledge_base_ids=kb_scope,
                )
                if trace and retrieval_intel:
                    # Observability: stages from adaptive service
                    for tk, tv in retrieval_intel.timings.items():
                        # Map internal names to spec observability names where needed
                        trace.record(tk, tv)
                    trace.set_counter("adaptive_retrieval_enabled", True)
                    trace.set_counter("retrieval_strategy", retrieval_intel.strategy.value)
                    trace.set_counter("retrieval_query_count", len(retrieval_intel.query_variants))
                    trace.set_counter("retrieval_attempts", retrieval_intel.retrieval_attempts)
                    trace.set_counter("fallback_triggered", retrieval_intel.fallback_used)
                    if retrieval_intel.retrieval_confidence:
                        trace.set_counter(
                            "retrieval_confidence", retrieval_intel.retrieval_confidence.confidence
                        )
                    trace.set_counter(
                        "parallel_tasks", retrieval_intel.timings.get("parallel_tasks", 1)
                    )
            except Exception as e:
                logger.warning("Adaptive retrieval router failed, fallback to Hybrid: %s", e)
                if trace:
                    trace.add_error(f"adaptive_router_failed: {e}")
                    trace.set_counter("fallback_triggered", True)
                # Fallback safety: Hybrid Retrieval
                retrieval_req = RetrievalRequest(
                    query=request.message,
                    knowledge_base_ids=kb_scope,
                    top_k=request.top_k,
                    candidate_k=candidate_k,
                    search_mode=SearchMode(request.search_mode),
                    parallel_execution=request.parallel_execution,
                )
                retrieval_resp = await RetrievalService.search(
                    session=session,
                    organization_id=organization_id,
                    request=retrieval_req,
                )
        if retrieval_resp is None:
            # Standard path when adaptive disabled or fallback
            if trace:
                if not settings.ENABLE_ADAPTIVE_RETRIEVAL:
                    trace.set_counter("adaptive_retrieval_enabled", False)
                trace.set_counter("retrieval_query_count", 1)
            retrieval_req = RetrievalRequest(
                query=request.message,
                knowledge_base_ids=kb_scope,
                top_k=request.top_k,
                candidate_k=candidate_k,
                search_mode=SearchMode(request.search_mode),
                parallel_execution=request.parallel_execution,
            )
            retrieval_resp = await RetrievalService.search(
                session=session,
                organization_id=organization_id,
                request=retrieval_req,
            )
        # Phase 1.6: Arxiv fallback — fast bounded, opt-in, fail-fast (Part 15-17)
        # Before: unconditional 10s blocking external call. After: disabled by default, 2s bounded.
        arxiv_ms = 0.0
        is_test_env = settings.APP_ENV == "test" or "pytest" in sys.modules
        # Only trigger if local retrieval empty AND fallback explicitly enabled
        if not retrieval_resp.results and not is_test_env and settings.ENABLE_ARXIV_FALLBACK:
            import asyncio as _asyncio

            ax_t0 = time.perf_counter()
            try:
                arxiv_results = await _asyncio.wait_for(
                    ArxivClient.search(
                        query=request.message, top_k=request.top_k, organization_id=organization_id
                    ),
                    timeout=float(settings.ARXIV_TIMEOUT_SECONDS),
                )
            except (TimeoutError, Exception) as e:
                logger.warning(
                    f"Arxiv fallback timeout/failure (bounded {settings.ARXIV_TIMEOUT_SECONDS}s): {e}"
                )
                arxiv_results = []
            arxiv_ms = (time.perf_counter() - ax_t0) * 1000.0
            if arxiv_results:
                retrieval_resp.results = arxiv_results
            if trace:
                trace.set_counter("arxiv_triggered", True)
                trace.set_counter("arxiv_timeout_s", settings.ARXIV_TIMEOUT_SECONDS)
        elif not retrieval_resp.results and trace:
            trace.set_counter("arxiv_triggered", False)
            trace.set_counter("arxiv_skipped_reason", "disabled_or_test")
        retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000.0
        if trace:
            trace.record("retrieval_total_ms", retrieval_latency_ms)
            if arxiv_ms:
                trace.record("arxiv_fallback_ms", arxiv_ms)
            trace.mark("retrieval_complete")
            trace.set_counter("retrieved_chunks", len(retrieval_resp.results))
            # Propagate retrieval sub-trace stages
            if retrieval_resp.trace:
                trace.record(
                    "retrieval_embedding_ms", retrieval_resp.trace.query_embedding_duration_ms
                )
                trace.record(
                    "query_embedding_ms", retrieval_resp.trace.query_embedding_duration_ms
                )
                trace.record("retrieval_vector_ms", retrieval_resp.trace.vector_search_duration_ms)
                trace.record(
                    "retrieval_keyword_ms", retrieval_resp.trace.keyword_search_duration_ms
                )
                trace.record("retrieval_fusion_ms", retrieval_resp.trace.fusion_duration_ms)
                if retrieval_resp.trace.embedding_cache_hit:
                    trace.record("embedding_cache_latency_ms", retrieval_resp.trace.embedding_cache_latency_ms)
                    trace.set_counter("embedding_cache_hit", True)
                    trace.set_counter("embedding_provider_calls", 0)
                else:
                    trace.record("embedding_cache_latency_ms", 0.0)
                    trace.set_counter("embedding_cache_hit", False)
                    trace.set_counter(
                        "embedding_provider_calls",
                        1 if retrieval_resp.trace.query_embedding_duration_ms > 0 else 0,
                    )
                v_count = retrieval_resp.trace.vector_candidate_count or 0
                k_count = retrieval_resp.trace.keyword_candidate_count or 0
                trace.set_counter("vector_candidates", v_count)
                trace.set_counter("keyword_candidates", k_count)
                trace.set_counter(
                    "retrieved_candidates",
                    (v_count + k_count) if (v_count + k_count) > 0 else len(retrieval_resp.results),
                )
            trace.set_counter("retained_candidates", len(retrieval_resp.results))

        # 4. Fetch document names for citations
        doc_names_t0 = time.perf_counter()
        doc_names = {
            r.document_id: r.document_name for r in retrieval_resp.results if r.document_name
        }
        doc_names_ms = (time.perf_counter() - doc_names_t0) * 1000.0
        if trace:
            trace.record("doc_names_ms", doc_names_ms)

        # 5. Assemble context with provenance and token budgeting
        ctx_t0 = time.perf_counter()
        assembled_context = self.context_builder.assemble(
            retrieval_results=retrieval_resp.results,
            document_names=doc_names,
        )
        ctx_ms = (time.perf_counter() - ctx_t0) * 1000.0
        if trace:
            trace.record("context_selection_ms", ctx_ms)  # context_selection ~ assemble time
            trace.record("context_assembly_ms", ctx_ms)
            trace.record("context_formatting_ms", ctx_ms)
            trace.record("context_deduplication_ms", 0.0)  # no dedup yet
            trace.set_counter("context_chars", len(assembled_context.formatted_context))
            trace.set_counter("context_tokens", assembled_context.estimated_tokens)
            trace.set_counter("selected_chunks", assembled_context.total_chunks_included)
            trace.set_counter("context_chunks_used", assembled_context.total_chunks_included)
            trace.mark("context_done")

        # 6. Load recent conversation history (excluding current user message).
        # Fetch started before retrieval; awaiting here hides its latency behind
        # retrieval I/O. hist_ms measures the isolated query wall time.
        all_messages, hist_ms = await history_task
        history = [m for m in all_messages if m.id != user_msg.id]
        if trace:
            trace.record("message_history_ms", hist_ms)
            trace.record("conversation_history_formatting_ms", hist_ms)
            trace.set_counter("history_messages", len(history))
            trace.mark("history_done")

        # 7. Construct LLM prompt messages
        prompt_t0 = time.perf_counter()
        llm_messages = self.prompt_builder.build_messages(
            query=request.message,
            context=assembled_context,
            history=history,
            max_history=settings.MAX_HISTORY_MESSAGES,
        )
        prompt_ms = (time.perf_counter() - prompt_t0) * 1000.0
        prompt_tokens = sum(len(m.content) // 4 for m in llm_messages)
        if trace:
            trace.record("prompt_construction_ms", prompt_ms)
            trace.record("prompt_token_estimation_ms", 0.1)  # heuristic is inline
            trace.set_counter("prompt_messages", len(llm_messages))
            trace.set_counter("prompt_tokens", prompt_tokens)
            trace.set_counter("final_prompt_tokens", prompt_tokens)
            trace.mark("prompt_done")

        # 8. Resolve provider and model via factory
        prov_t0 = time.perf_counter()
        provider, model_name = LLMProviderFactory.create(
            provider=request.provider,
            model=request.model,
        )
        prov_ms = (time.perf_counter() - prov_t0) * 1000.0
        if trace:
            trace.record("provider_resolution_ms", prov_ms)
            trace.record("provider_factory_ms", prov_ms)
            trace.record("provider_initialization_ms", prov_ms)
            trace.record("model_configuration_ms", prov_ms)
            trace.set_counter("provider", provider.name)
            trace.set_counter("model", model_name)
            trace.mark("provider_done")

        # Release DB connection before network-bound LLM call
        commit_t0 = time.perf_counter()
        with contextlib.suppress(Exception):
            await session.commit()
        commit_ms = (time.perf_counter() - commit_t0) * 1000.0
        if trace:
            trace.record("pre_llm_commit_ms", commit_ms)

        # 9. Invoke LLM generation
        req_serial_t0 = time.perf_counter()
        llm_req = LLMRequest(
            provider=provider.name,
            model=model_name,
            messages=llm_messages,
            temperature=request.temperature,
            max_tokens=settings.MAX_GENERATION_TOKENS,
            stream=False,
        )
        req_serial_ms = (time.perf_counter() - req_serial_t0) * 1000.0
        if trace:
            trace.record("request_serialization_ms", req_serial_ms)
            trace.mark("llm_request_started")

        gen_start = time.perf_counter()
        llm_resp = await provider.generate(llm_req)
        gen_latency_ms = (time.perf_counter() - gen_start) * 1000.0
        if trace:
            trace.record("llm_request_ms", gen_latency_ms)
            trace.record("llm_total_ms", gen_latency_ms)
            trace.record("generation_completion_ms", gen_latency_ms)
            trace.record("token_generation_ms", gen_latency_ms)
            # For non-streaming, TTFT == total
            trace.record("time_to_first_token_ms", gen_latency_ms)
            trace.record("token_streaming_ms", 0.0)
            trace.set_counter("llm_call_count", 1)
            trace.mark("llm_done")

        # 10. Extract & validate citations
        cit_t0 = time.perf_counter()
        citations = self.citation_builder.build_citations(
            answer_text=llm_resp.content,
            context=assembled_context,
        )
        cit_ms = (time.perf_counter() - cit_t0) * 1000.0
        if trace:
            trace.record("citation_construction_ms", cit_ms)
            trace.set_counter("citations", len(citations))
            trace.mark("citations_done")

        # 10.5 Groundedness verification (Phase 2.3) — claim extraction → evidence selection → verification → aggregation
        groundedness_dict: dict | None = None
        groundedness_trace = None
        verify_t0 = time.perf_counter()
        try:
            from app.services.verification.schemas import VerificationConfig
            from app.services.verification.service import VerificationService

            settings_verify = get_settings()
            if getattr(settings_verify, "ENABLE_GROUNDEDNESS_CHECK", False):
                # Prepare evidence from retrieved chunks (already reranked if enabled)
                evidence_chunks = [
                    {
                        "chunk_id": r.chunk_id,
                        "document_id": r.document_id,
                        "document_name": r.document_name,
                        "content": r.content,
                        "retrieval_rank": r.rank,
                        "rerank_rank": None,
                    }
                    for r in retrieval_resp.results
                ]
                # Fallback to context sources if no retrieval results (should be at least citation context)
                if not evidence_chunks and assembled_context.sources:
                    evidence_chunks = [
                        {
                            "chunk_id": s.chunk_id,
                            "document_id": s.document_id,
                            "document_name": s.document_name,
                            "content": s.content,
                            "retrieval_rank": s.citation_id,
                        }
                        for s in assembled_context.sources
                    ]
                cfg = VerificationConfig(
                    enabled=True,
                    evidence_top_k=getattr(settings_verify, "VERIFICATION_EVIDENCE_TOP_K", 3),
                    timeout_seconds=float(
                        getattr(settings_verify, "VERIFICATION_TIMEOUT_SECONDS", 2.0)
                    ),
                )
                groundedness_res, groundedness_trace = await VerificationService.verify_answer(
                    answer=llm_resp.content,
                    evidence_chunks=evidence_chunks,
                    config=cfg,
                )
                groundedness_dict = groundedness_res.model_dump()
                if trace and groundedness_trace:
                    trace.record("claim_extraction_ms", groundedness_trace.claim_extraction_ms)
                    trace.record("verification_total_ms", groundedness_trace.verification_total_ms)
                    trace.set_counter("claim_count", groundedness_trace.claim_count)
                    trace.set_counter("groundedness_score", groundedness_trace.groundedness_score)
                    trace.set_counter("supported_claims", groundedness_trace.supported_claims)
                    trace.set_counter("contradicted_claims", groundedness_trace.contradicted_claims)
                    trace.mark("verification_done")
            else:
                if trace:
                    trace.set_counter("groundedness_enabled", False)
        except Exception as e:
            logger.warning("Groundedness verification failed, proceeding without: %s", e)
            if trace:
                trace.add_error(f"groundedness_failed: {e}")
            groundedness_dict = None
        verify_ms = (time.perf_counter() - verify_t0) * 1000.0
        if trace:
            trace.record("groundedness_verification_ms", verify_ms)

        # 11. Persist assistant message with metadata
        retrieval_summary = RetrievalSummary(
            search_mode=request.search_mode,
            result_count=len(retrieval_resp.results),
            latency_ms=round(retrieval_latency_ms, 2),
        )

        usage_dict = None
        if llm_resp.usage:
            usage_dict = {
                "prompt_tokens": llm_resp.usage.prompt_tokens,
                "completion_tokens": llm_resp.usage.completion_tokens,
                "total_tokens": llm_resp.usage.total_tokens,
            }

        total_latency_ms = (time.perf_counter() - total_start) * 1000.0

        assistant_metadata = {
            "provider": provider.name,
            "model": model_name,
            "citations": [c.model_dump() for c in citations],
            "retrieval": retrieval_summary.model_dump(),
            "usage": usage_dict,
            "latency_ms": round(total_latency_ms, 2),
            "generation_latency_ms": round(gen_latency_ms, 2),
            "retrieval_latency_ms": round(retrieval_latency_ms, 2),
            "groundedness": groundedness_dict,
        }

        persist_t0 = time.perf_counter()
        create_t0 = time.perf_counter()
        assistant_msg = await ConversationService.add_message(
            session=session,
            conversation_id=conv.id,
            role=MessageRole.ASSISTANT,
            content=llm_resp.content,
            metadata=assistant_metadata,
            flush=False,
        )
        create_ms = (time.perf_counter() - create_t0) * 1000.0
        flush_ms = 0.0  # flush is inside add_message
        commit_t2 = time.perf_counter()
        await session.commit()
        commit2_ms = (time.perf_counter() - commit_t2) * 1000.0
        refresh_ms = 0.0  # no refresh: expire_on_commit=False keeps flushed attributes
        persist_ms = (time.perf_counter() - persist_t0) * 1000.0
        db_total_ms = conv_ms + persist_user_ms + hist_ms + commit_ms + create_ms + commit2_ms
        if trace:
            trace.record("assistant_message_creation_ms", create_ms)
            trace.record("assistant_message_save_ms", create_ms)
            trace.record("user_message_save_ms", persist_user_ms)
            trace.record("session_flush_ms", flush_ms)
            trace.record("persistence_commit_ms", commit2_ms)
            trace.record("database_commit_ms", commit2_ms)
            trace.record("persistence_refresh_ms", refresh_ms)
            trace.record("persistence_total_ms", persist_ms)
            trace.record("database_latency_ms", round(db_total_ms, 2))
            trace.set_counter("db_queries", trace.counters.get("db_queries", 0) + 4)
            trace.record("total_ms", total_latency_ms)
            trace.mark("persistence_done")
            trace.mark("persistence_completed")
            trace.emit_performance_summary(outcome="SUCCESS")
            # Avoid log flooding: full waterfall only in DEBUG or slow requests
            if settings.DEBUG or total_latency_ms > 2000:
                trace.log_summary()

        return RAGChatResponse(
            conversation_id=conv.id,
            message_id=assistant_msg.id,
            user_message_id=user_msg.id,
            answer=llm_resp.content,
            citations=citations,
            retrieval=retrieval_summary,
            model=model_name,
            provider=provider.name,
            usage=usage_dict,
            latency_ms=round(total_latency_ms, 2),
            groundedness=groundedness_dict,
        )

    async def stream_chat(
        self,
        session: AsyncSession,
        organization_id: str,
        user_id: str,
        request: RAGChatRequest,
    ) -> AsyncGenerator[str, None]:
        import uuid

        """Execute streaming RAG generation yielding Server-Sent Events (SSE)."""
        total_start = time.perf_counter()
        trace = get_current_trace()
        if trace:
            trace.mark("request_received")
            prep_t0 = time.perf_counter()
            normalized_query = request.message.strip()
            prep_ms = (time.perf_counter() - prep_t0) * 1000.0
            trace.record("query_preprocessing_ms", prep_ms)
            trace.record("query_normalization_ms", prep_ms)
            trace.set_counter("query_length", len(normalized_query))
        settings = get_settings()

        try:
            # 1. Fetch or create conversation
            conv_t0 = time.perf_counter()
            conv = await ConversationService.get_or_create_conversation(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                conversation_id=request.conversation_id,
                initial_query=request.message,
                knowledge_base_ids=request.knowledge_base_ids,
                flush=False,
            )
            if trace:
                trace.record("conversation_lookup_ms", (time.perf_counter() - conv_t0) * 1000.0)
                trace.mark("conversation_done")

            # 2. Persist user message
            persist_t0 = time.perf_counter()
            user_msg = await ConversationService.add_message(
                session=session,
                conversation_id=conv.id,
                role=MessageRole.USER,
                content=request.message,
                flush=False,
            )
            if trace:
                trace.record("user_message_persist_ms", (time.perf_counter() - persist_t0) * 1000.0)
            commit_t0 = time.perf_counter()
            await session.commit()
            if trace:
                trace.record("user_message_commit_ms", (time.perf_counter() - commit_t0) * 1000.0)
                trace.mark("user_message_done")

            # Yield start event
            prov_t0 = time.perf_counter()
            provider, model_name = LLMProviderFactory.create(
                provider=request.provider,
                model=request.model,
            )
            if trace:
                trace.record("provider_resolution_ms", (time.perf_counter() - prov_t0) * 1000.0)
                trace.record("provider_factory_ms", (time.perf_counter() - prov_t0) * 1000.0)
                trace.set_counter("provider", provider.name)
                trace.set_counter("model", model_name)
            assistant_msg_id = str(uuid.uuid4())
            start_payload = {
                "conversation_id": conv.id,
                "user_message_id": user_msg.id,
                "message_id": assistant_msg_id,
                "provider": provider.name,
                "model": model_name,
            }
            if trace:
                trace.mark("start_event_sent")
            yield f"event: start\ndata: {json.dumps(start_payload)}\n\n"

            # 3. Retrieve context chunks — router (adaptive vs hybrid)
            kb_scope = request.knowledge_base_ids or conv.knowledge_base_ids
            candidate_k = max(request.top_k * 4, 30)

            # 6 (early). History fetch on an isolated session overlaps retrieval
            # I/O. The committed user message is visible here but excluded by id.
            async def _load_history_early() -> tuple[list, float]:
                if request.conversation_id is None:
                    return [], 0.0
                hist_inner_t0 = time.perf_counter()
                hist_maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
                async with hist_maker() as hist_session:
                    msgs = await ConversationService.get_recent_messages(
                        session=hist_session,
                        conversation_id=conv.id,
                        limit=settings.MAX_HISTORY_MESSAGES + 1,
                    )
                return msgs, (time.perf_counter() - hist_inner_t0) * 1000.0

            history_task = asyncio.create_task(_load_history_early())
            history_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
            retrieval_start = time.perf_counter()
            if trace:
                trace.mark("retrieval_start")
            retrieval_resp = None
            retrieval_intel = None
            if settings.ENABLE_ADAPTIVE_RETRIEVAL:
                try:
                    retrieval_resp, retrieval_intel = await AdaptiveRetrievalService.retrieve(
                        session=session,
                        organization_id=organization_id,
                        query=request.message,
                        top_k=request.top_k,
                        candidate_k=candidate_k,
                        knowledge_base_ids=kb_scope,
                    )
                    if trace and retrieval_intel:
                        for tk, tv in retrieval_intel.timings.items():
                            trace.record(tk, tv)
                        trace.set_counter("adaptive_retrieval_enabled", True)
                        trace.set_counter("retrieval_strategy", retrieval_intel.strategy.value)
                        trace.set_counter(
                            "retrieval_query_count", len(retrieval_intel.query_variants)
                        )
                        trace.set_counter("retrieval_attempts", retrieval_intel.retrieval_attempts)
                        trace.set_counter("fallback_triggered", retrieval_intel.fallback_used)
                        if retrieval_intel.retrieval_confidence:
                            trace.set_counter(
                                "retrieval_confidence",
                                retrieval_intel.retrieval_confidence.confidence,
                            )
                except Exception as e:
                    logger.warning(
                        "Adaptive retrieval router (stream) failed, fallback to Hybrid: %s", e
                    )
                    if trace:
                        trace.add_error(f"adaptive_router_failed: {e}")
                    retrieval_resp = None
            if retrieval_resp is None:
                if trace:
                    if not settings.ENABLE_ADAPTIVE_RETRIEVAL:
                        trace.set_counter("adaptive_retrieval_enabled", False)
                    trace.set_counter("retrieval_query_count", 1)
                retrieval_req = RetrievalRequest(
                    query=request.message,
                    knowledge_base_ids=kb_scope,
                    top_k=request.top_k,
                    candidate_k=candidate_k,
                    search_mode=SearchMode(request.search_mode),
                )
                retrieval_resp = await RetrievalService.search(
                    session=session,
                    organization_id=organization_id,
                    request=retrieval_req,
                )
            arxiv_ms = 0.0
            is_test_env2 = settings.APP_ENV == "test" or "pytest" in sys.modules
            # Phase 1.6: bounded opt-in fallback (same as generate path)
            if not retrieval_resp.results and not is_test_env2 and settings.ENABLE_ARXIV_FALLBACK:
                import asyncio as _asyncio2

                ax_t0 = time.perf_counter()
                try:
                    arxiv_results = await _asyncio2.wait_for(
                        ArxivClient.search(
                            query=request.message,
                            top_k=request.top_k,
                            organization_id=organization_id,
                        ),
                        timeout=float(settings.ARXIV_TIMEOUT_SECONDS),
                    )
                except (TimeoutError, Exception) as e:
                    logger.warning(
                        f"Arxiv fallback timeout/failure (bounded {settings.ARXIV_TIMEOUT_SECONDS}s): {e}"
                    )
                    arxiv_results = []
                arxiv_ms = (time.perf_counter() - ax_t0) * 1000.0
                if arxiv_results:
                    retrieval_resp.results = arxiv_results
                if trace:
                    trace.set_counter("arxiv_triggered", True)
            elif not retrieval_resp.results and trace:
                trace.set_counter("arxiv_triggered", False)
            retrieval_latency_ms = (time.perf_counter() - retrieval_start) * 1000.0
            if trace:
                trace.record("retrieval_total_ms", retrieval_latency_ms)
                if arxiv_ms:
                    trace.record("arxiv_fallback_ms", arxiv_ms)
                trace.set_counter("retrieved_chunks", len(retrieval_resp.results))
                if retrieval_resp.trace:
                    trace.record(
                        "retrieval_embedding_ms", retrieval_resp.trace.query_embedding_duration_ms
                    )
                    trace.record(
                        "query_embedding_ms", retrieval_resp.trace.query_embedding_duration_ms
                    )
                    trace.record(
                        "retrieval_vector_ms", retrieval_resp.trace.vector_search_duration_ms
                    )
                    trace.record(
                        "retrieval_keyword_ms", retrieval_resp.trace.keyword_search_duration_ms
                    )
                    trace.record("retrieval_fusion_ms", retrieval_resp.trace.fusion_duration_ms)
                    if retrieval_resp.trace.embedding_cache_hit:
                        trace.record("embedding_cache_latency_ms", retrieval_resp.trace.embedding_cache_latency_ms)
                        trace.set_counter("embedding_cache_hit", True)
                        trace.set_counter("embedding_provider_calls", 0)
                    else:
                        trace.record("embedding_cache_latency_ms", 0.0)
                        trace.set_counter("embedding_cache_hit", False)
                        trace.set_counter(
                            "embedding_provider_calls",
                            1 if retrieval_resp.trace.query_embedding_duration_ms > 0 else 0,
                        )
                    v_count = retrieval_resp.trace.vector_candidate_count or 0
                    k_count = retrieval_resp.trace.keyword_candidate_count or 0
                    trace.set_counter("vector_candidates", v_count)
                    trace.set_counter("keyword_candidates", k_count)
                    trace.set_counter(
                        "retrieved_candidates",
                        (v_count + k_count) if (v_count + k_count) > 0 else len(retrieval_resp.results),
                    )
                trace.set_counter("retained_candidates", len(retrieval_resp.results))
                trace.mark("retrieval_complete")

            retrieval_payload = {
                "search_mode": request.search_mode,
                "result_count": len(retrieval_resp.results),
                "latency_ms": round(retrieval_latency_ms, 2),
            }
            if trace:
                trace.mark("retrieval_event_sent")
            yield f"event: retrieval\ndata: {json.dumps(retrieval_payload)}\n\n"

            # 4. Extract doc names
            doc_names_t0 = time.perf_counter()
            doc_names = {
                r.document_id: r.document_name for r in retrieval_resp.results if r.document_name
            }
            if trace:
                trace.record("doc_names_ms", (time.perf_counter() - doc_names_t0) * 1000.0)

            # 5. Assemble context
            ctx_t0 = time.perf_counter()
            assembled_context = self.context_builder.assemble(
                retrieval_results=retrieval_resp.results,
                document_names=doc_names,
            )
            if trace:
                trace.record("context_selection_ms", (time.perf_counter() - ctx_t0) * 1000.0)
                trace.record("context_assembly_ms", (time.perf_counter() - ctx_t0) * 1000.0)
                trace.set_counter("context_chars", len(assembled_context.formatted_context))
                trace.set_counter("context_tokens", assembled_context.estimated_tokens)
                trace.set_counter("selected_chunks", assembled_context.total_chunks_included)
                trace.set_counter("context_chunks_used", assembled_context.total_chunks_included)
                trace.mark("context_done")

            # 6. Load recent history (fetch started before retrieval; awaiting
            # here hides its latency behind retrieval I/O).
            all_messages, hist_ms = await history_task
            history = [m for m in all_messages if m.id != user_msg.id]
            if trace:
                trace.record("message_history_ms", hist_ms)
                trace.record("conversation_history_formatting_ms", hist_ms)
                trace.set_counter("history_messages", len(history))
                trace.mark("history_done")

            # Release DB connection before long-lived LLM streaming
            commit_t0 = time.perf_counter()
            with contextlib.suppress(Exception):
                await session.commit()
            if trace:
                trace.record("pre_llm_commit_ms", (time.perf_counter() - commit_t0) * 1000.0)

            # 7. Construct prompt
            prompt_t0 = time.perf_counter()
            llm_messages = self.prompt_builder.build_messages(
                query=request.message,
                context=assembled_context,
                history=history,
                max_history=settings.MAX_HISTORY_MESSAGES,
            )
            prompt_tokens = sum(len(m.content) // 4 for m in llm_messages)
            if trace:
                trace.record("prompt_construction_ms", (time.perf_counter() - prompt_t0) * 1000.0)
                trace.set_counter("prompt_messages", len(llm_messages))
                trace.set_counter("prompt_tokens", prompt_tokens)
                trace.mark("prompt_done")

            # 8. Start streaming tokens from provider
            llm_req = LLMRequest(
                provider=provider.name,
                model=model_name,
                messages=llm_messages,
                temperature=request.temperature,
                max_tokens=settings.MAX_GENERATION_TOKENS,
                stream=True,
            )
            if trace:
                trace.record("request_serialization_ms", 0.1)
                trace.mark("llm_request_started")

            accumulated_tokens: list[str] = []
            final_usage = None
            first_token_time: float | None = None
            first_token_sent_time: float | None = None
            stream_start = time.perf_counter()
            chunk_count = 0

            async for chunk in provider.stream(llm_req):
                chunk_count += 1
                if chunk.delta:
                    if first_token_time is None:
                        first_token_time = (time.perf_counter() - stream_start) * 1000.0
                        if trace:
                            trace.record("time_to_first_token_ms", first_token_time)
                            trace.mark("first_token_received")
                    accumulated_tokens.append(chunk.delta)
                    # Mark first_token_sent before yield
                    is_first = first_token_sent_time is None
                    if is_first:
                        t_before_yield = time.perf_counter()
                    yield f"event: token\ndata: {json.dumps({'delta': chunk.delta})}\n\n"
                    if is_first:
                        first_token_sent_time = (time.perf_counter() - t_before_yield) * 1000.0
                        user_ttft_ms = (time.perf_counter() - total_start) * 1000.0
                        if trace:
                            trace.record("first_token_sent_ms", first_token_sent_time)
                            trace.record("sse_first_token_gap_ms", first_token_sent_time)
                            trace.record("user_ttft_ms", user_ttft_ms)
                            trace.mark("first_token_sent")
                            # LLM first token → client first token overhead
                            if first_token_time is not None:
                                trace.record(
                                    "llm_to_client_first_token_overhead_ms",
                                    (time.perf_counter() - stream_start) * 1000.0
                                    - first_token_time,
                                )
                if chunk.usage:
                    final_usage = chunk.usage

            last_token_gap_t0 = time.perf_counter()
            full_answer = "".join(accumulated_tokens)
            gen_latency_ms = (time.perf_counter() - stream_start) * 1000.0
            streaming_dur_ms = gen_latency_ms - (first_token_time or 0.0)
            tokens_count = (
                final_usage.completion_tokens
                if (final_usage and final_usage.completion_tokens)
                else max(1, len(full_answer) // 4)
            )
            tps = round(tokens_count / max(streaming_dur_ms / 1000.0, 0.001), 2)
            if trace:
                trace.record("token_streaming_ms", streaming_dur_ms)
                trace.record("generation_completion_ms", gen_latency_ms)
                trace.record("generation_ms", gen_latency_ms)
                trace.record("llm_total_ms", gen_latency_ms)
                trace.record("tokens_per_second", tps)
                trace.set_counter("tokens_per_sec", tps)
                trace.set_counter("generated_chars", len(full_answer))
                trace.set_counter("generated_tokens_est", tokens_count)
                trace.set_counter("chunks_streamed", chunk_count)
                trace.set_counter("llm_call_count", 1)
                trace.mark("last_token_received")
                trace.mark("last_token_sent")
                trace.record(
                    "sse_last_token_gap_ms", (time.perf_counter() - last_token_gap_t0) * 1000.0
                )

            # 9. Extract & validate citations
            cit_t0 = time.perf_counter()
            citations = self.citation_builder.build_citations(
                answer_text=full_answer,
                context=assembled_context,
            )
            if trace:
                trace.record("citation_construction_ms", (time.perf_counter() - cit_t0) * 1000.0)
                trace.set_counter("citations", len(citations))

            for cit in citations:
                yield f"event: citation\ndata: {json.dumps(cit.model_dump())}\n\n"

            # 9.5 Groundedness verification (Phase 2.3) — after citations, before persistence
            groundedness_dict = None
            verify_t0 = time.perf_counter()
            try:
                from app.services.verification.schemas import VerificationConfig
                from app.services.verification.service import VerificationService

                settings_v = get_settings()
                if getattr(settings_v, "ENABLE_GROUNDEDNESS_CHECK", False):
                    evidence_chunks = [
                        {
                            "chunk_id": r.chunk_id,
                            "document_id": r.document_id,
                            "document_name": r.document_name,
                            "content": r.content,
                            "retrieval_rank": r.rank,
                        }
                        for r in retrieval_resp.results
                    ]
                    if not evidence_chunks and assembled_context.sources:
                        evidence_chunks = [
                            {
                                "chunk_id": s.chunk_id,
                                "document_id": s.document_id,
                                "document_name": s.document_name,
                                "content": s.content,
                                "retrieval_rank": s.citation_id,
                            }
                            for s in assembled_context.sources
                        ]
                    cfg = VerificationConfig(
                        enabled=True,
                        evidence_top_k=getattr(settings_v, "VERIFICATION_EVIDENCE_TOP_K", 3),
                        timeout_seconds=float(
                            getattr(settings_v, "VERIFICATION_TIMEOUT_SECONDS", 2.0)
                        ),
                    )
                    groundedness_res, groundedness_trace = await VerificationService.verify_answer(
                        answer=full_answer,
                        evidence_chunks=evidence_chunks,
                        config=cfg,
                    )
                    groundedness_dict = groundedness_res.model_dump()
                    if trace and groundedness_trace:
                        trace.record("claim_extraction_ms", groundedness_trace.claim_extraction_ms)
                        trace.record(
                            "verification_total_ms", groundedness_trace.verification_total_ms
                        )
                        trace.set_counter(
                            "groundedness_score", groundedness_trace.groundedness_score
                        )
                        trace.mark("verification_done")
                    # Yield groundedness SSE event
                    yield f"event: groundedness\ndata: {json.dumps(groundedness_dict)}\n\n"
                else:
                    if trace:
                        trace.set_counter("groundedness_enabled", False)
            except Exception as e:
                logger.warning("Groundedness verification (stream) failed: %s", e)
                if trace:
                    trace.add_error(f"groundedness_failed: {e}")
            if trace:
                trace.record(
                    "groundedness_verification_ms", (time.perf_counter() - verify_t0) * 1000.0
                )

            # 10. Persist complete response
            if trace:
                trace.mark("persistence_started")
            total_latency_ms = (time.perf_counter() - total_start) * 1000.0
            usage_dict = None
            if final_usage:
                usage_dict = {
                    "prompt_tokens": final_usage.prompt_tokens,
                    "completion_tokens": final_usage.completion_tokens,
                    "total_tokens": final_usage.total_tokens,
                }
            elif full_answer:
                tok_len = max(1, len(full_answer) // 4)
                usage_dict = {
                    "prompt_tokens": assembled_context.estimated_tokens,
                    "completion_tokens": tok_len,
                    "total_tokens": assembled_context.estimated_tokens + tok_len,
                }

            retrieval_summary = RetrievalSummary(
                search_mode=request.search_mode,
                result_count=len(retrieval_resp.results),
                latency_ms=round(retrieval_latency_ms, 2),
            )

            assistant_metadata = {
                "provider": provider.name,
                "model": model_name,
                "citations": [c.model_dump() for c in citations],
                "retrieval": retrieval_summary.model_dump(),
                "usage": usage_dict,
                "latency_ms": round(total_latency_ms, 2),
                "generation_latency_ms": round(gen_latency_ms, 2),
                "retrieval_latency_ms": round(retrieval_latency_ms, 2),
                "time_to_first_token_ms": (
                    round(first_token_time, 2) if first_token_time else None
                ),
                "groundedness": groundedness_dict,
            }

            persist_t0 = time.perf_counter()
            create_t0 = time.perf_counter()
            assistant_msg = await ConversationService.add_message(
                session=session,
                conversation_id=conv.id,
                role=MessageRole.ASSISTANT,
                content=full_answer,
                metadata=assistant_metadata,
                message_id=assistant_msg_id,
                flush=False,
            )
            if trace:
                trace.record(
                    "assistant_message_creation_ms", (time.perf_counter() - create_t0) * 1000.0
                )
                trace.record(
                    "assistant_message_save_ms", (time.perf_counter() - create_t0) * 1000.0
                )
                trace.record(
                    "user_message_save_ms", trace.stages.get("user_message_persist_ms", 0.0)
                )
            commit_t0 = time.perf_counter()
            await session.commit()
            if trace:
                trace.record("persistence_commit_ms", (time.perf_counter() - commit_t0) * 1000.0)
                trace.record("database_commit_ms", (time.perf_counter() - commit_t0) * 1000.0)
            # No refresh: expire_on_commit=False keeps flushed attributes (id set client-side).
            if trace:
                trace.record("persistence_refresh_ms", 0.0)
                trace.record("persistence_total_ms", (time.perf_counter() - persist_t0) * 1000.0)
                trace.record("total_ms", (time.perf_counter() - total_start) * 1000.0)
                db_total_ms = (
                    trace.stages.get("conversation_lookup_ms", 0.0)
                    + trace.stages.get("user_message_persist_ms", 0.0)
                    + trace.stages.get("user_message_commit_ms", 0.0)
                    + trace.stages.get("message_history_ms", 0.0)
                    + trace.stages.get("pre_llm_commit_ms", 0.0)
                    + (time.perf_counter() - create_t0) * 1000.0
                    + (time.perf_counter() - commit_t0) * 1000.0
                )
                trace.record("database_latency_ms", round(db_total_ms, 2))
                trace.set_counter("db_queries", trace.counters.get("db_queries", 0) + 4)
                trace.mark("persistence_completed")

            # Done event
            done_t0 = time.perf_counter()
            done_payload = {
                "message_id": assistant_msg.id,
                "conversation_id": conv.id,
                "latency_ms": round(total_latency_ms, 2),
                "time_to_first_token_ms": round(first_token_time, 2) if first_token_time else None,
                "usage": usage_dict,
            }
            yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
            done_ms = (time.perf_counter() - done_t0) * 1000.0
            if trace:
                trace.record("sse_done_gap_ms", done_ms)
                trace.record("done_event_sent_ms", done_ms)
                trace.mark("done_sent")
                trace.emit_performance_summary(outcome="SUCCESS")
                if settings.DEBUG or total_latency_ms > 2000:
                    trace.log_summary()

        except asyncio.CancelledError:
            if trace:
                trace.emit_performance_summary(outcome="CANCELLED", error_category="CLIENT_DISCONNECT")
            raise
        except LLMException as exc:
            logger.warning("RAG streaming encountered domain error: [%s] %s", exc.code, exc.message)
            if trace:
                trace.add_error(f"LLMException {exc.code}: {exc.message}")
                trace.emit_performance_summary(outcome="FAILED", error_category=f"LLM_{exc.code.upper()}")
            err_data = {"code": exc.code, "message": exc.message}
            yield f"event: error\ndata: {json.dumps(err_data)}\n\n"
        except Exception as exc:
            logger.exception("RAG streaming unexpected failure: %s", exc)
            if trace:
                trace.add_error(str(exc))
                trace.emit_performance_summary(outcome="FAILED", error_category="INTERNAL_ERROR")
            fallback_err = {
                "code": "GENERATION_FAILED",
                "message": "We couldn't generate an answer. Please try again.",
            }
            yield f"event: error\ndata: {json.dumps(fallback_err)}\n\n"
        finally:
            if trace and not trace._summary_emitted:
                trace.emit_performance_summary(outcome=trace.outcome or "UNKNOWN")
