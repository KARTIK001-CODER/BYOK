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

    def __init__(self, rrf_k: int | None = None) -> None:
        settings = get_settings()
        self.rrf_k = rrf_k or settings.RRF_K
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
    ) -> tuple[list[RetrievalResult], list[CandidateMatch], list[CandidateMatch], dict]:
        """
        Execute parallel or resilient vector + keyword search and fuse candidates.

        Returns:
            tuple: (fused_results, vector_candidates, keyword_candidates, timing_and_status_dict)
        """
        # For concurrency verification, capture absolute offsets from hybrid start
        hybrid_start = time.perf_counter()
        vector_start_offset = None
        keyword_start_offset = None
        vector_end_offset = None
        keyword_end_offset = None

        async def run_vector() -> tuple[list[CandidateMatch], Exception | None]:
            nonlocal vector_start_offset, vector_end_offset
            vector_start_offset = (time.perf_counter() - hybrid_start) * 1000.0
            v_start_t = time.perf_counter()
            # Measure session acquisition overhead (phase 1.5 DB connection overhead)
            sess_t0 = time.perf_counter()
            maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
            sess_ms = (time.perf_counter() - sess_t0) * 1000.0  # session creation is cheap but counted
            try:
                async with maker() as local_session:
                    conn_t0 = time.perf_counter()
                    # connection acquisition happens lazily on first execute; we measure via session acquisition + first query
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
                    # record session overhead in trace if present
                    from app.core.tracing import get_current_trace as _gct
                    tr = _gct()
                    if tr:
                        tr.record("vector_session_acquisition_ms", sess_ms)
                        tr.record("vector_connection_ms", (time.perf_counter() - conn_t0) * 1000.0 - total_ms + sess_ms)  # approximate
                    return candidates, None, total_ms
            except Exception as e:
                vector_end_offset = (time.perf_counter() - hybrid_start) * 1000.0
                logger.warning("Vector search encountered failure: %s", e)
                return [], e, (time.perf_counter() - v_start_t) * 1000.0

        async def run_keyword() -> tuple[list[CandidateMatch], Exception | None]:
            nonlocal keyword_start_offset, keyword_end_offset
            keyword_start_offset = (time.perf_counter() - hybrid_start) * 1000.0
            k_start_t = time.perf_counter()
            sess_t0 = time.perf_counter()
            maker = async_sessionmaker(bind=session.bind, expire_on_commit=False)
            sess_ms = (time.perf_counter() - sess_t0) * 1000.0
            try:
                async with maker() as local_session:
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
                    from app.core.tracing import get_current_trace as _gct2
                    tr2 = _gct2()
                    if tr2:
                        tr2.record("keyword_session_acquisition_ms", sess_ms)
                    return candidates, None, total_ms
            except Exception as e:
                keyword_end_offset = (time.perf_counter() - hybrid_start) * 1000.0
                logger.warning("Keyword search encountered failure: %s", e)
                return [], e, (time.perf_counter() - k_start_t) * 1000.0

        v_task = asyncio.create_task(run_vector())
        k_task = asyncio.create_task(run_keyword())
        
        vector_res, keyword_res = await asyncio.gather(v_task, k_task)
        
        vector_candidates, vector_error, vector_duration_ms = vector_res
        keyword_candidates, keyword_error, keyword_duration_ms = keyword_res

        # Log concurrency overlap evidence
        if vector_start_offset is not None and keyword_start_offset is not None:
            overlap = not (vector_end_offset < keyword_start_offset or keyword_end_offset < vector_start_offset)
            logger.info(
                "Hybrid concurrency: vector %.2f-%.2f ms, keyword %.2f-%.2f ms, overlap=%s, gap=%.2f ms",
                vector_start_offset, vector_end_offset or 0,
                keyword_start_offset, keyword_end_offset or 0,
                overlap,
                abs(vector_start_offset - keyword_start_offset),
            )

        # Handle complete vs partial search failures
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
            "hybrid_overlap_ms": round(abs((vector_start_offset or 0) - (keyword_start_offset or 0)), 2),
        }

        return fused_results, vector_candidates, keyword_candidates, timing_data
