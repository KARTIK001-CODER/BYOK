import logging
import math
import time
from collections.abc import Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.tracing import get_current_trace
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.services.retrieval.filters import RetrievalFilterBuilder
from app.services.retrieval.fusion import CandidateMatch
from app.services.retrieval.schemas import RetrievalFilter

logger = logging.getLogger("app.services.retrieval.vector")


class VectorRetriever:
    """Retriever executing dense semantic vector search via pgvector cosine distance."""

    @staticmethod
    def _cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
        """Compute cosine similarity between two float vectors in Python."""
        dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0.0 or norm2 == 0.0:
            return 0.0
        return dot / (norm1 * norm2)

    @classmethod
    async def retrieve(
        cls,
        session: AsyncSession,
        organization_id: str,
        query_embedding: list[float],
        candidate_k: int = 50,
        knowledge_base_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        filters: RetrievalFilter | None = None,
    ) -> list[CandidateMatch]:
        """
        Execute tenant-scoped nearest neighbor vector search.

        Returns:
            list[CandidateMatch]: Ranked list of candidate matches ordered by similarity descending.
        """
        where_clauses = RetrievalFilterBuilder.build_chunk_filters(
            organization_id=organization_id,
            knowledge_base_ids=knowledge_base_ids,
            document_ids=document_ids,
            filters=filters,
        )
        where_clauses.append(DocumentChunk.embedding.is_not(None))

        # Check database dialect to support native pgvector or test dialect
        dialect_name = session.bind.dialect.name if session.bind else "postgresql"

        candidates: list[CandidateMatch] = []
        trace = get_current_trace()

        if dialect_name == "postgresql":
            # Native PostgreSQL with pgvector <=> cosine distance operator
            prep_t0 = time.perf_counter()
            cosine_dist = DocumentChunk.embedding.cosine_distance(query_embedding)
            stmt = (
                select(DocumentChunk, Document.name.label("document_name"), cosine_dist.label("distance"))
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(and_(*where_clauses))
                .order_by(cosine_dist.asc())
                .limit(candidate_k)
            )
            prep_ms = (time.perf_counter() - prep_t0) * 1000.0
            sql_t0 = time.perf_counter()
            result = await session.execute(stmt)
            sql_ms = (time.perf_counter() - sql_t0) * 1000.0
            proc_t0 = time.perf_counter()
            rows = result.all()

            for rank, (chunk, document_name, distance) in enumerate(rows, start=1):
                # pgvector cosine distance is 1 - cosine_similarity (range [0, 2])
                dist_val = float(distance) if distance is not None else 1.0
                similarity_score = max(0.0, min(1.0, 1.0 - dist_val))
                candidates.append(
                    CandidateMatch(
                        chunk=chunk,
                        score=similarity_score,
                        rank=rank,
                        source="vector",
                        document_name=document_name,
                    )
                )
            proc_ms = (time.perf_counter() - proc_t0) * 1000.0
            if trace:
                trace.record("vector_query_prep_ms", prep_ms)
                trace.record("vector_sql_execution_ms", sql_ms)
                trace.record("vector_result_processing_ms", proc_ms)
                trace.set_counter("vector_rows_returned", len(rows))
        else:
            # Fallback for SQLite in-memory unit tests
            prep_t0 = time.perf_counter()
            stmt = (
                select(DocumentChunk, Document.name.label("document_name"))
                .join(Document, DocumentChunk.document_id == Document.id)
                .where(and_(*where_clauses))
            )
            prep_ms = (time.perf_counter() - prep_t0) * 1000.0
            sql_t0 = time.perf_counter()
            result = await session.execute(stmt)
            sql_ms = (time.perf_counter() - sql_t0) * 1000.0
            proc_t0 = time.perf_counter()
            rows = result.all()

            scored_chunks = []
            for chunk, document_name in rows:
                if chunk.embedding is not None:
                    sim = cls._cosine_similarity(query_embedding, chunk.embedding)
                    sim = max(0.0, min(1.0, sim))
                    scored_chunks.append((chunk, sim, document_name))

            # Sort descending by similarity
            scored_chunks.sort(key=lambda x: -x[1])
            top_candidates = scored_chunks[:candidate_k]

            for rank, (chunk, score, document_name) in enumerate(top_candidates, start=1):
                candidates.append(
                    CandidateMatch(
                        chunk=chunk,
                        score=score,
                        rank=rank,
                        source="vector",
                        document_name=document_name,
                    )
                )
            proc_ms = (time.perf_counter() - proc_t0) * 1000.0
            if trace:
                trace.record("vector_query_prep_ms", prep_ms)
                trace.record("vector_sql_execution_ms", sql_ms)
                trace.record("vector_result_processing_ms", proc_ms)

        logger.debug(
            "Vector retrieval found %d candidates for org_id=%s (candidate_k=%d)",
            len(candidates),
            organization_id,
            candidate_k,
        )
        return candidates
