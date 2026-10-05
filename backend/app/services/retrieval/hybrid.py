import asyncio
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.services.retrieval.errors import RetrievalErrorCode, RetrievalException
from app.services.retrieval.fusion import CandidateMatch, ReciprocalRankFusion
from app.services.retrieval.keyword import KeywordRetriever
from app.services.retrieval.schemas import RetrievalFilter, RetrievalResult
from app.services.retrieval.vector import VectorRetriever

logger = logging.getLogger("app.services.retrieval.hybrid")


class HybridRetriever:
    """Retriever combining dense vector search and lexical FTS with Reciprocal Rank Fusion (RRF)."""

    def __init__(self, rrf_k: int | None = None, parallel: bool | None = None) -> None:
        settings = get_settings()
        self.rrf_k = rrf_k or settings.RRF_K
        self.parallel = (
            parallel
            if parallel is not None
            else getattr(settings, "ENABLE_PARALLEL_HYBRID_SEARCH", True)
        )
        self.fusion = ReciprocalRankFusion(rrf_k=self.rrf_k)

    async def retrieve(
        self,
        session: AsyncSession,
        organization_id: str,
        query: str,
        query_embedding: list[float],
        top_k: int = 10,
        candidate_k: int = 50,
        knowledge_base_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        filters: RetrievalFilter | None = None,
        parallel: bool | None = None,
    ) -> tuple[list[RetrievalResult], list[CandidateMatch], list[CandidateMatch], dict]:
        """
        Execute parallel or connection-safe sequential vector + keyword search and fuse candidates.

        Args:
            session: Active SQLAlchemy AsyncSession.
            organization_id: Scoping organization ID.
            query: Normalized search query.
            query_embedding: Dense embedding vector.
            top_k: Number of final fused results to return.
            candidate_k: Candidate fetch size for each branch.
            knowledge_base_ids: Optional KB filters.
            document_ids: Optional document filters.
            filters: Structured retrieval filters.
            parallel: Optional override for parallel vs sequential execution.

        Returns:
            tuple: (fused_results, vector_candidates, keyword_candidates, timing_and_status_dict)
        """
        is_parallel = parallel if parallel is not None else self.parallel
        hybrid_start = time.perf_counter()
        vector_start_offset = None
        keyword_start_offset = None
        vector_end_offset = None
        keyword_end_offset = None

        if not is_parallel:
            # ── Sequential Execution: Single Session, Zero Secondary Sessions ──
            from app.core.tracing import get_current_trace as _gct_seq

            tr_seq = _gct_seq()
            db_sessions_created = 0

            # 1. Vector Search Branch
            v_start_t = time.perf_counter()
            vector_start_offset = (v_start_t - hybrid_start) * 1000.0
            if tr_seq:
                tr_seq.mark("vector_search_started")
            vector_candidates: list[CandidateMatch] = []
            vector_error: Exception | None = None
            try:
                vector_candidates = await VectorRetriever.retrieve(
                    session=session,
                    organization_id=organization_id,
                    query_embedding=query_embedding,
                    candidate_k=candidate_k,
                    knowledge_base_ids=knowledge_base_ids,
                    document_ids=document_ids,
                    filters=filters,
                )
            except Exception as e:
                logger.warning("Vector search encountered failure: %s", e)
                vector_error = e
            finally:
                v_end_t = time.perf_counter()
                vector_end_offset = (v_end_t - hybrid_start) * 1000.0
                vector_duration_ms = (v_end_t - v_start_t) * 1000.0
                if tr_seq:
                    tr_seq.mark("vector_search_completed")

            # 2. Keyword Search Branch (sequential on same session, never concurrent)
            k_start_t = time.perf_counter()
            keyword_start_offset = (k_start_t - hybrid_start) * 1000.0
            if tr_seq:
                tr_seq.mark("keyword_search_started")
            keyword_candidates: list[CandidateMatch] = []
            keyword_error: Exception | None = None
            try:
                keyword_candidates = await KeywordRetriever.retrieve(
                    session=session,
                    organization_id=organization_id,
                    query=query,
                    candidate_k=candidate_k,
                    knowledge_base_ids=knowledge_base_ids,
                    document_ids=document_ids,
                    filters=filters,
                )
            except Exception as e:
                logger.warning("Keyword search encountered failure: %s", e)
                keyword_error = e
            finally:
                k_end_t = time.perf_counter()
                keyword_end_offset = (k_end_t - hybrid_start) * 1000.0
                keyword_duration_ms = (k_end_t - k_start_t) * 1000.0
                if tr_seq:
                    tr_seq.mark("keyword_search_completed")

            p_wall = round(vector_duration_ms + keyword_duration_ms, 2)
            p_sum = p_wall
            p_overlap = 0.0
            p_efficiency = 1.0

            if tr_seq:
                tr_seq.record("parallel_wall_time_ms", p_wall)
                tr_seq.record("parallel_sum_task_time_ms", p_sum)
                tr_seq.record("parallel_overlap_ms", p_overlap)
                tr_seq.record("parallel_efficiency", p_efficiency)
                tr_seq.set_counter("parallel_task_count", 1)
                tr_seq.set_counter("parallel_efficiency", p_efficiency)

            logger.info(
                "Hybrid sequential: vector %.2f ms, keyword %.2f ms, wall=%.2f ms, secondary_sessions=0",
                vector_duration_ms,
                keyword_duration_ms,
                p_wall,
            )

        else:
            # ── Parallel Execution: Concurrent Tasks with Dedicated Isolated Sessions ──
            maker = async_sessionmaker(
                bind=session.bind,
                expire_on_commit=False,
                autoflush=False,
            )
            db_sessions_created = 2

            async def run_vector() -> tuple[list[CandidateMatch], Exception | None, float]:
                nonlocal vector_start_offset, vector_end_offset
                vector_start_offset = (time.perf_counter() - hybrid_start) * 1000.0
                from app.core.tracing import get_current_trace as _gct

                tr = _gct()
                if tr:
                    tr.mark("vector_search_started")
                    tr.record_session_created(1)
                v_start_t = time.perf_counter()
                sess_t0 = time.perf_counter()
                try:
                    async with maker() as local_session:
                        sess_ms = (time.perf_counter() - sess_t0) * 1000.0
                        candidates = await VectorRetriever.retrieve(
                            session=local_session,
                            organization_id=organization_id,
                            query_embedding=query_embedding,
                            candidate_k=candidate_k,
                            knowledge_base_ids=knowledge_base_ids,
                            document_ids=document_ids,
                            filters=filters,
                        )
                        vector_end_offset = (time.perf_counter() - hybrid_start) * 1000.0
                        total_ms = (time.perf_counter() - v_start_t) * 1000.0
                        if tr:
                            tr.mark("vector_search_completed")
                            tr.record("vector_session_acquisition_ms", sess_ms)
                            tr.record("vector_connection_ms", sess_ms)
                        return candidates, None, total_ms
                except Exception as e:
                    vector_end_offset = (time.perf_counter() - hybrid_start) * 1000.0
                    if tr:
                        tr.mark("vector_search_completed")
                    logger.warning("Vector search encountered failure: %s", e)
                    return [], e, (time.perf_counter() - v_start_t) * 1000.0

            async def run_keyword() -> tuple[list[CandidateMatch], Exception | None, float]:
                nonlocal keyword_start_offset, keyword_end_offset
                keyword_start_offset = (time.perf_counter() - hybrid_start) * 1000.0
                from app.core.tracing import get_current_trace as _gct2

                tr2 = _gct2()
                if tr2:
                    tr2.mark("keyword_search_started")
                    tr2.record_session_created(1)
                k_start_t = time.perf_counter()
                sess_t0 = time.perf_counter()
                try:
                    async with maker() as local_session:
                        sess_ms = (time.perf_counter() - sess_t0) * 1000.0
                        candidates = await KeywordRetriever.retrieve(
                            session=local_session,
                            organization_id=organization_id,
                            query=query,
                            candidate_k=candidate_k,
                            knowledge_base_ids=knowledge_base_ids,
                            document_ids=document_ids,
                            filters=filters,
                        )
                        keyword_end_offset = (time.perf_counter() - hybrid_start) * 1000.0
                        total_ms = (time.perf_counter() - k_start_t) * 1000.0
                        if tr2:
                            tr2.mark("keyword_search_completed")
                            tr2.record("keyword_session_acquisition_ms", sess_ms)
                        return candidates, None, total_ms
                except Exception as e:
                    keyword_end_offset = (time.perf_counter() - hybrid_start) * 1000.0
                    if tr2:
                        tr2.mark("keyword_search_completed")
                    logger.warning("Keyword search encountered failure: %s", e)
                    return [], e, (time.perf_counter() - k_start_t) * 1000.0

            v_task = asyncio.create_task(run_vector())
            k_task = asyncio.create_task(run_keyword())

            try:
                vector_res, keyword_res = await asyncio.gather(v_task, k_task)
            except asyncio.CancelledError:
                # Cancel both child tasks and wait for their session context managers to exit cleanly
                v_task.cancel()
                k_task.cancel()
                await asyncio.gather(v_task, k_task, return_exceptions=True)
                raise

            vector_candidates, vector_error, vector_duration_ms = vector_res
            keyword_candidates, keyword_error, keyword_duration_ms = keyword_res

            # Calculate exact parallel efficiency & overlap
            v_s = vector_start_offset or 0.0
            v_e = vector_end_offset or 0.0
            k_s = keyword_start_offset or 0.0
            k_e = keyword_end_offset or 0.0
            p_start = round(min(v_s, k_s), 2)
            p_end = round(max(v_e, k_e), 2)
            p_wall = round(max(0.01, p_end - p_start), 2)
            p_sum = round(vector_duration_ms + keyword_duration_ms, 2)
            p_overlap = round(max(0.0, min(v_e, k_e) - max(v_s, k_s)), 2)
            p_efficiency = round(p_sum / max(p_wall, 0.01), 2)

            from app.core.tracing import get_current_trace as _gct3

            tr3 = _gct3()
            if tr3:
                tr3.record("parallel_wall_time_ms", p_wall)
                tr3.record("parallel_sum_task_time_ms", p_sum)
                tr3.record("parallel_overlap_ms", p_overlap)
                tr3.record("parallel_efficiency", p_efficiency)
                tr3.set_counter("parallel_task_count", 2)
                tr3.set_counter("parallel_efficiency", p_efficiency)

            if vector_start_offset is not None and keyword_start_offset is not None:
                overlap = not (
                    vector_end_offset < keyword_start_offset
                    or keyword_end_offset < vector_start_offset
                )
                logger.info(
                    "Hybrid concurrency: vector %.2f-%.2f ms, keyword %.2f-%.2f ms, overlap=%s, efficiency=%.2fx, gap=%.2f ms",
                    vector_start_offset,
                    vector_end_offset or 0,
                    keyword_start_offset,
                    keyword_end_offset or 0,
                    overlap,
                    p_efficiency,
                    abs(vector_start_offset - keyword_start_offset),
                )

        # ── Common Result Handling and RRF Candidate Fusion ──
        if vector_error and keyword_error:
            logger.error("Both vector and keyword search branches failed.")
            raise RetrievalException(
                message=(
                    f"Hybrid search failed: vector ({vector_error}), keyword ({keyword_error})"
                ),
                code=RetrievalErrorCode.RETRIEVAL_DATABASE_ERROR,
            )

        partial_failure = bool(vector_error or keyword_error)
        partial_reason = (
            f"Vector failed: {vector_error}"
            if vector_error
            else (f"Keyword failed: {keyword_error}" if keyword_error else None)
        )

        f_start = time.perf_counter()
        fused_results = self.fusion.fuse(
            vector_candidates=vector_candidates,
            keyword_candidates=keyword_candidates,
            top_k=top_k,
        )
        fusion_duration_ms = (time.perf_counter() - f_start) * 1000.0

        timing_data = {
            "vector_duration_ms": round(vector_duration_ms, 2),
            "keyword_duration_ms": round(keyword_duration_ms, 2),
            "fusion_duration_ms": round(fusion_duration_ms, 2),
            "partial_failure": partial_failure,
            "partial_failure_reason": partial_reason,
            "vector_start_offset_ms": round(vector_start_offset or 0, 2),
            "keyword_start_offset_ms": round(keyword_start_offset or 0, 2),
            "vector_end_offset_ms": round(vector_end_offset or 0, 2),
            "keyword_end_offset_ms": round(keyword_end_offset or 0, 2),
            "hybrid_overlap_ms": round(p_overlap, 2),
            "parallel_execution": is_parallel,
            "db_sessions_created": db_sessions_created,
        }

        return fused_results, vector_candidates, keyword_candidates, timing_data
