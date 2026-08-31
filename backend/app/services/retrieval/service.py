import hashlib
import logging
import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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
        query_hash = cls._hash_query(request.query)

        # 1. Query Normalization & Validation
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

        # 2. Scoping & Authorization Validation
        all_kb_ids: list[str] | None = None
        if request.knowledge_base_ids or (request.filters and request.filters.knowledge_base_ids):
            kb_set: set[str] = set()
            if request.knowledge_base_ids:
                kb_set.update(request.knowledge_base_ids)
            if request.filters and request.filters.knowledge_base_ids:
                kb_set.update(request.filters.knowledge_base_ids)
            all_kb_ids = list(kb_set)

        await cls.validate_knowledge_bases_access(session, organization_id, all_kb_ids)

        logger.info(
            "Retrieval started: org_id=%s, q_hash=%s, mode=%s, top_k=%d, candidate_k=%d",
            organization_id,
            query_hash,
            request.search_mode.value,
            request.top_k,
            request.candidate_k,
        )

        # 3. Query Embedding (if Vector or Hybrid mode)
        query_embedding: list[float] | None = None
        embed_duration_ms = 0.0

        if request.search_mode in (SearchMode.VECTOR, SearchMode.HYBRID):
            e_start = time.perf_counter()
            embedding_provider = provider or get_embedding_provider()
            query_embedding = embedding_provider.embed_query(normalized_query)
            embed_duration_ms = (time.perf_counter() - e_start) * 1000.0

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

        if request.search_mode == SearchMode.VECTOR:
            assert query_embedding is not None
            v_start = time.perf_counter()
            vector_candidates = await VectorRetriever.retrieve(
                session=session,
                organization_id=organization_id,
                query_embedding=query_embedding,
                candidate_k=request.candidate_k,
                knowledge_base_ids=request.knowledge_base_ids,
                document_ids=request.document_ids,
                filters=request.filters,
            )
            vector_duration_ms = (time.perf_counter() - v_start) * 1000.0
            vector_candidates_count = len(vector_candidates)

            # Format top_k results
            for rank, c in enumerate(vector_candidates[: request.top_k], start=1):
                chunk: DocumentChunk = c.chunk
                provenance = ChunkProvenance(
                    organization_id=chunk.organization_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    document_id=chunk.document_id,
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

        elif request.search_mode == SearchMode.KEYWORD:
            k_start = time.perf_counter()
            keyword_candidates = await KeywordRetriever.retrieve(
                session=session,
                organization_id=organization_id,
                query=normalized_query,
                candidate_k=request.candidate_k,
                knowledge_base_ids=request.knowledge_base_ids,
                document_ids=request.document_ids,
                filters=request.filters,
            )
            keyword_duration_ms = (time.perf_counter() - k_start) * 1000.0
            keyword_candidates_count = len(keyword_candidates)

            for rank, c in enumerate(keyword_candidates[: request.top_k], start=1):
                chunk: DocumentChunk = c.chunk
                provenance = ChunkProvenance(
                    organization_id=chunk.organization_id,
                    knowledge_base_id=chunk.knowledge_base_id,
                    document_id=chunk.document_id,
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

        elif request.search_mode == SearchMode.HYBRID:
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
                candidate_k=request.candidate_k,
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

        total_duration_ms = (time.perf_counter() - total_start) * 1000.0

        trace = RetrievalTrace(
            query_hash=query_hash,
            search_mode=request.search_mode.value,
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
        )

        logger.info(
            "Retrieval completed: org_id=%s, q_hash=%s, results=%d, total_ms=%.2f "
            "(embed=%.2f, vec=%.2f, kw=%.2f, fuse=%.2f)",
            organization_id,
            query_hash,
            len(results),
            total_duration_ms,
            embed_duration_ms,
            vector_duration_ms,
            keyword_duration_ms,
            fusion_duration_ms,
        )

        return RetrievalResponse(
            query=request.query,
            search_mode=request.search_mode,
            total_results=len(results),
            results=results,
            trace=trace if request.debug else None,
        )
