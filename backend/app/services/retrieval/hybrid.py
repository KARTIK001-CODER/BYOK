import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

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
        v_start = time.perf_counter()
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

        vector_duration_ms = (time.perf_counter() - v_start) * 1000.0

        k_start = time.perf_counter()
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

        keyword_duration_ms = (time.perf_counter() - k_start) * 1000.0

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
        }

        return fused_results, vector_candidates, keyword_candidates, timing_data
