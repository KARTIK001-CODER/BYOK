import asyncio
import hashlib
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_base import KnowledgeBase
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.providers import get_embedding_provider
from app.services.retrieval.errors import RetrievalErrorCode, RetrievalException
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.keyword import KeywordRetriever
from app.services.retrieval.schemas import (
    ChunkProvenance,
    RetrievalRequest,
    RetrievalResponse,
    RetrievalResult,
    RetrievalTrace,
    SearchMode,
)
from app.services.retrieval.vector import VectorRetriever

logger = logging.getLogger("app.services.retrieval.service")


class RetrievalService:
    """Core domain service orchestrating vector, keyword, and hybrid retrieval pipelines."""

    @staticmethod
    def _hash_query(query: str) -> str:
        """Create non-reversible SHA-256 hash for secure telemetry correlation."""
        return hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]

    @staticmethod
    async def validate_knowledge_bases_access(
        session: AsyncSession,
        organization_id: str,
        kb_ids: list[str] | None,
    ) -> None:
        """Verify that all requested knowledge bases belong to the specified organization."""
        if not kb_ids:
            return

        stmt = select(KnowledgeBase.id).where(
            KnowledgeBase.organization_id == organization_id,
            KnowledgeBase.id.in_(kb_ids),
        )
        result = await session.execute(stmt)
        found_ids = set(result.scalars().all())

        missing_or_unauthorized = set(kb_ids) - found_ids
        if missing_or_unauthorized:
            raise RetrievalException(
                message=f"Unauthorized knowledge base(s): {list(missing_or_unauthorized)}",
                code=RetrievalErrorCode.UNAUTHORIZED_KNOWLEDGE_BASE,
                status_code=403,
            )

    @classmethod
    async def search(
        cls,
        session: AsyncSession,
        organization_id: str,
        request: RetrievalRequest,
        provider: BaseEmbeddingProvider | None = None,
    ) -> RetrievalResponse:
        """
        Execute tenant-scoped multi-modal search and ranking.

        Args:
            session: Database session.
            organization_id: Authenticated caller's organization ID.
            request: Validated RetrievalRequest payload.
            provider: Optional custom embedding provider.

        Returns:
            RetrievalResponse containing ranked chunks, scores, provenance, and diagnostic trace.
        """
        settings = get_settings()
        total_start = time.perf_counter()
        trace = get_current_trace()
        query_hash = cls._hash_query(request.query)

        # ── 1. Query Normalization & Validation ──
        norm_t0 = time.perf_counter()
        normalized_query = request.query.strip()
        if not normalized_query:
            raise RetrievalException(
                message="Retrieval query cannot be empty.",
                code=RetrievalErrorCode.RETRIEVAL_QUERY_EMPTY,
            )
        if len(normalized_query) > settings.MAX_QUERY_LENGTH:
            raise RetrievalException(
                message=f"Query exceeds max length of {settings.MAX_QUERY_LENGTH} chars.",
                code=RetrievalErrorCode.RETRIEVAL_QUERY_TOO_LONG,
            )
        norm_ms = (time.perf_counter() - norm_t0) * 1000.0
        if trace:
            trace.record("query_normalization_ms", norm_ms)
            trace.set_counter("query_length", len(normalized_query))
            trace.set_counter("query_hash", query_hash)

        # 2. Scoping & Authorization Validation
        authz_t0 = time.perf_counter()
        all_kb_ids: list[str] | None = None
        if request.knowledge_base_ids or (request.filters and request.filters.knowledge_base_ids):
            kb_set: set[str] = set()
            if request.knowledge_base_ids:
                kb_set.update(request.knowledge_base_ids)
            if request.filters and request.filters.knowledge_base_ids:
                kb_set.update(request.filters.knowledge_base_ids)
            all_kb_ids = list(kb_set)

        await cls.validate_knowledge_bases_access(session, organization_id, all_kb_ids)
        authz_ms = (time.perf_counter() - authz_t0) * 1000.0
        if trace:
            trace.record("retrieval_authz_ms", authz_ms)

        logger.info(
            "Retrieval started: org_id=%s, q_hash=%s, mode=%s, top_k=%d, candidate_k=%d",
            organization_id,
            query_hash,
            request.search_mode.value,
            request.top_k,
            request.candidate_k,
        )

        # Phase 2.1 — Query Intelligence (adaptive, no DB/LLM, <5ms, safe fallback to HYBRID)
        effective_search_mode = request.search_mode
        effective_candidate_k = request.candidate_k
        query_analysis_dict: dict | None = None
        if settings.ENABLE_QUERY_INTELLIGENCE:
            try:
                from app.services.query_intelligence.analyzer import QueryAnalyzer
                from app.services.query_intelligence.schemas import RetrievalStrategy

                analysis, qi_timings = QueryAnalyzer.analyze_with_timings(normalized_query)
                query_analysis_dict = analysis.model_dump()
                if trace:
                    for tk, tv in qi_timings.items():
                        trace.record(tk, tv)
                    trace.set_counter("qi_strategy", analysis.strategy.strategy.value)
                    trace.set_counter("qi_class", analysis.classification.primary_class.value)
                    trace.set_counter("qi_confidence", analysis.classification.confidence)
                    trace.set_counter("qi_ambiguity", analysis.ambiguity.ambiguity_score)
                    trace.set_counter("qi_reason", analysis.strategy.reason)
                # Map strategy to effective search mode / candidate_k
                strat = analysis.strategy.strategy
                if strat == RetrievalStrategy.KEYWORD:
                    effective_search_mode = SearchMode.KEYWORD
                elif strat == RetrievalStrategy.VECTOR:
                    effective_search_mode = SearchMode.VECTOR
                elif strat == RetrievalStrategy.HYBRID_WIDE:
                    effective_search_mode = SearchMode.HYBRID
                    effective_candidate_k = settings.HYBRID_WIDE_CANDIDATE_K
                else:
                    effective_search_mode = SearchMode.HYBRID
                    effective_candidate_k = request.candidate_k
                logger.info(
                    "Query intelligence: q_hash=%s class=%s conf=%.2f amb=%.2f strategy=%s reason=%s",
                    query_hash,
                    analysis.classification.primary_class.value,
                    analysis.classification.confidence,
                    analysis.ambiguity.ambiguity_score,
                    analysis.strategy.strategy.value,
                    analysis.strategy.reason,
                )
            except Exception as e:
                logger.warning("Query intelligence failed, fallback to HYBRID: %s", e)
                if trace:
                    trace.add_error(f"qi_failed: {e}")
                effective_search_mode = SearchMode.HYBRID
                effective_candidate_k = request.candidate_k
        else:
            if trace:
                trace.set_counter("qi_enabled", False)

        # 3. Query Embedding (if Vector or Hybrid mode)
        query_embedding: list[float] | None = None
        embed_duration_ms = 0.0
        embed_init_ms = 0.0
        embed_infer_ms = 0.0

        if effective_search_mode in (SearchMode.VECTOR, SearchMode.HYBRID):
            # Measure provider instantiation (model init) separately from inference
            init_t0 = time.perf_counter()
            embedding_provider = provider or get_embedding_provider()
            embed_init_ms = (time.perf_counter() - init_t0) * 1000.0

            infer_t0 = time.perf_counter()
            query_embedding = await asyncio.to_thread(
                embedding_provider.embed_query, normalized_query
            )
            embed_infer_ms = (time.perf_counter() - infer_t0) * 1000.0
            embed_duration_ms = embed_init_ms + embed_infer_ms

            if trace:
                trace.record("embedding_model_initialization_ms", embed_init_ms)
                trace.record("embedding_inference_ms", embed_infer_ms)
                trace.record("embedding_total_ms", embed_duration_ms)
                # Heuristic: if init > 100ms it's cold; else warm
                trace.set_counter("embedding_cold", embed_init_ms > 100)
                trace.set_counter("embedding_dimension", embedding_provider.dimension)

            # Validate embedding dimension
            if len(query_embedding) != embedding_provider.dimension:
                raise RetrievalException(
                    message=(
                        f"Query embedding dimension mismatch: generated {len(query_embedding)}, "
                        f"expected {embedding_provider.dimension}."
                    ),
                    code=RetrievalErrorCode.EMBEDDING_DIMENSION_MISMATCH,
                )

        # 4. Dispatch Search Strategy
        vector_candidates_count = 0
        keyword_candidates_count = 0
        vector_duration_ms = 0.0
        keyword_duration_ms = 0.0
        fusion_duration_ms = 0.0
        partial_failure = False
        partial_reason: str | None = None
        results: list[RetrievalResult] = []
        serialization_ms = 0.0

        if effective_search_mode == SearchMode.VECTOR:
            assert query_embedding is not None
            v_start = time.perf_counter()
            vector_candidates = await VectorRetriever.retrieve(
                session=session,
                organization_id=organization_id,
                query_embedding=query_embedding,
                candidate_k=effective_candidate_k,
                knowledge_base_ids=request.knowledge_base_ids,
                document_ids=request.document_ids,
                filters=request.filters,
            )
            vector_duration_ms = (time.perf_counter() - v_start) * 1000.0
            vector_candidates_count = len(vector_candidates)
            if trace:
                trace.record("vector_search_ms", vector_duration_ms)
                # vector internal breakdown added via VectorRetriever itself if trace present

            # Format top_k results
            ser_t0 = time.perf_counter()
            for rank, c in enumerate(vector_candidates[: request.top_k], start=1):
                chunk: DocumentChunk = c.chunk
                provenance = ChunkProvenance(
                    organization_id=chunk.organization_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    document_id=chunk.document_id,
                    document_name=c.document_name,
                    document_version_id=chunk.document_version_id,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    metadata=chunk.chunk_metadata,
                )
                results.append(
                    RetrievalResult(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        document_name=c.document_name,
                        document_version_id=chunk.document_version_id,
                        knowledge_base_id=chunk.knowledge_base_id,
                        content=chunk.content,
                        score=round(c.score, 4),
                        rank=rank,
                        source="vector",
                        vector_score=round(c.score, 4),
                        keyword_score=None,
                        rrf_score=None,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        metadata=chunk.chunk_metadata,
                        provenance=provenance,
                    )
                )
            serialization_ms = (time.perf_counter() - ser_t0) * 1000.0
            if trace:
                trace.record("result_serialization_ms", serialization_ms)

        elif effective_search_mode == SearchMode.KEYWORD:
            k_start = time.perf_counter()
            keyword_candidates = await KeywordRetriever.retrieve(
                session=session,
                organization_id=organization_id,
                query=normalized_query,
                candidate_k=effective_candidate_k,
                knowledge_base_ids=request.knowledge_base_ids,
                document_ids=request.document_ids,
                filters=request.filters,
            )
            keyword_duration_ms = (time.perf_counter() - k_start) * 1000.0
            if trace:
                trace.record("keyword_search_ms", keyword_duration_ms)
            keyword_candidates_count = len(keyword_candidates)

            ser_t0 = time.perf_counter()
            for rank, c in enumerate(keyword_candidates[: request.top_k], start=1):
                chunk: DocumentChunk = c.chunk
                provenance = ChunkProvenance(
                    organization_id=chunk.organization_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    document_id=chunk.document_id,
                    document_name=c.document_name,
                    document_version_id=chunk.document_version_id,
                    chunk_id=chunk.id,
                    chunk_index=chunk.chunk_index,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    metadata=chunk.chunk_metadata,
                )
                results.append(
                    RetrievalResult(
                        chunk_id=chunk.id,
                        document_id=chunk.document_id,
                        document_name=c.document_name,
                        document_version_id=chunk.document_version_id,
                        knowledge_base_id=chunk.knowledge_base_id,
                        content=chunk.content,
                        score=round(c.score, 4),
                        rank=rank,
                        source="keyword",
                        vector_score=None,
                        keyword_score=round(c.score, 4),
                        rrf_score=None,
                        page_number=chunk.page_number,
                        section_title=chunk.section_title,
                        metadata=chunk.chunk_metadata,
                        provenance=provenance,
                    )
                )
            serialization_ms = (time.perf_counter() - ser_t0) * 1000.0
            if trace:
                trace.record("result_serialization_ms", serialization_ms)

        elif effective_search_mode == SearchMode.HYBRID:
            assert query_embedding is not None
            hybrid_retriever = HybridRetriever()
            (
                results,
                v_candidates,
                k_candidates,
                timing_data,
            ) = await hybrid_retriever.retrieve(
                session=session,
                organization_id=organization_id,
                query=normalized_query,
                query_embedding=query_embedding,
                top_k=request.top_k,
                candidate_k=effective_candidate_k,
                knowledge_base_ids=request.knowledge_base_ids,
                document_ids=request.document_ids,
                filters=request.filters,
            )
            vector_candidates_count = len(v_candidates)
            keyword_candidates_count = len(k_candidates)
            vector_duration_ms = timing_data["vector_duration_ms"]
            keyword_duration_ms = timing_data["keyword_duration_ms"]
            fusion_duration_ms = timing_data["fusion_duration_ms"]
            partial_failure = timing_data["partial_failure"]
            partial_reason = timing_data["partial_failure_reason"]
            if trace:
                # Record hybrid breakdown + concurrency timestamps
                trace.record("vector_search_ms", vector_duration_ms)
                trace.record("keyword_search_ms", keyword_duration_ms)
                trace.record("fusion_ms", fusion_duration_ms)
                trace.record("fusion_latency_ms", fusion_duration_ms)
                serialization_ms = timing_data.get("serialization_ms", 0.0)
                if serialization_ms:
                    trace.record("result_serialization_ms", serialization_ms)
                # Concurrency verification timestamps if provided
                for k in ("vector_start_offset_ms", "keyword_start_offset_ms", "vector_end_offset_ms", "keyword_end_offset_ms"):
                    if k in timing_data:
                        trace.set_counter(k, timing_data[k])
                        trace.timestamps[k] = timing_data[k]  # reuse timestamps dict
                trace.set_counter("vector_candidates", vector_candidates_count)
                trace.set_counter("keyword_candidates", keyword_candidates_count)

        total_duration_ms = (time.perf_counter() - total_start) * 1000.0
        if trace:
            trace.record("retrieval_overall_ms", total_duration_ms)

        # Include effective mode in trace if adaptive
        effective_mode_str = effective_search_mode.value
        if query_analysis_dict and query_analysis_dict.get("strategy", {}).get("strategy") == "HYBRID_WIDE":
            effective_mode_str = "hybrid_wide"
            if trace:
                trace.set_counter("effective_candidate_k", effective_candidate_k)

        retr_trace = RetrievalTrace(
            query_hash=query_hash,
            search_mode=effective_mode_str,
            vector_candidate_count=vector_candidates_count,
            keyword_candidate_count=keyword_candidates_count,
            fused_candidate_count=vector_candidates_count + keyword_candidates_count,
            final_result_count=len(results),
            query_embedding_duration_ms=round(embed_duration_ms, 2),
            vector_search_duration_ms=round(vector_duration_ms, 2),
            keyword_search_duration_ms=round(keyword_duration_ms, 2),
            fusion_duration_ms=round(fusion_duration_ms, 2),
            total_duration_ms=round(total_duration_ms, 2),
            partial_failure=partial_failure,
            partial_failure_reason=partial_reason,
            query_analysis=query_analysis_dict,
        )

        logger.info(
            "Retrieval completed: org_id=%s, q_hash=%s, results=%d, total_ms=%.2f "
            "(embed=%.2f [init=%.2f infer=%.2f], vec=%.2f, kw=%.2f, fuse=%.2f, ser=%.2f) qi=%s",
            organization_id,
            query_hash,
            len(results),
            total_duration_ms,
            embed_duration_ms,
            embed_init_ms,
            embed_infer_ms,
            vector_duration_ms,
            keyword_duration_ms,
            fusion_duration_ms,
            serialization_ms,
            query_analysis_dict.get("strategy", {}).get("strategy") if query_analysis_dict else "none",
        )

        return RetrievalResponse(
            query=request.query,
            search_mode=effective_search_mode,
            total_results=len(results),
            results=results,
            trace=retr_trace if request.debug else None,
            query_analysis=query_analysis_dict,
        )
