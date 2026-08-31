import logging
import re
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document_chunk import DocumentChunk
from app.services.retrieval.filters import RetrievalFilterBuilder
from app.services.retrieval.fusion import CandidateMatch
from app.services.retrieval.schemas import RetrievalFilter

logger = logging.getLogger("app.services.retrieval.keyword")


class KeywordRetriever:
    """Retriever executing exact and lexical keyword search using PostgreSQL Full-Text Search."""

    @staticmethod
    def _sqlite_lexical_score(query: str, content: str, title: str | None) -> float:
        """
        Lightweight BM25/TF-like lexical ranker for SQLite test fallback.
        Calculates term match frequencies and bonuses for title and multi-term proximity.
        """
        combined = f"{title or ''} {content}".lower()
        terms = [t for t in re.findall(r"\b\w+\b", query.lower()) if len(t) > 1]
        if not terms:
            return 0.0

        matches = 0
        total_term_freq = 0
        for term in terms:
            cnt = combined.count(term)
            if cnt > 0:
                matches += 1
                total_term_freq += cnt

        if matches == 0:
            return 0.0

        # Term overlap ratio + frequency component + exact phrase bonus
        overlap_ratio = matches / len(terms)
        freq_score = min(1.0, total_term_freq / (len(terms) * 5.0))
        phrase_bonus = 0.5 if query.lower() in combined else 0.0

        return (overlap_ratio * 0.5) + (freq_score * 0.3) + phrase_bonus

    @classmethod
    async def retrieve(
        cls,
        session: AsyncSession,
        organization_id: str,
        query: str,
        candidate_k: int = 50,
        knowledge_base_ids: list[str] | None = None,
        document_ids: list[str] | None = None,
        filters: RetrievalFilter | None = None,
    ) -> list[CandidateMatch]:
        """
        Execute tenant-scoped keyword/full-text search.

        Returns:
            list[CandidateMatch]: Ranked candidate matches ordered by FTS rank score descending.
        """
        where_clauses = RetrievalFilterBuilder.build_chunk_filters(
            organization_id=organization_id,
            knowledge_base_ids=knowledge_base_ids,
            document_ids=document_ids,
            filters=filters,
        )

        dialect_name = session.bind.dialect.name if session.bind else "postgresql"
        candidates: list[CandidateMatch] = []

        if dialect_name == "postgresql":
            # Native PostgreSQL Full-Text Search with plainto_tsquery and ts_rank_cd
            query_ts = func.plainto_tsquery("english", query)
            rank_expr = func.ts_rank_cd(DocumentChunk.search_vector, query_ts)

            stmt = (
                select(DocumentChunk, rank_expr.label("rank_score"))
                .where(and_(*where_clauses, DocumentChunk.search_vector.op("@@")(query_ts)))
                .order_by(rank_expr.desc())
                .limit(candidate_k)
            )
            result = await session.execute(stmt)
            rows = result.all()

            for rank, (chunk, score) in enumerate(rows, start=1):
                candidates.append(
                    CandidateMatch(
                        chunk=chunk,
                        score=float(score) if score is not None else 0.0,
                        rank=rank,
                        source="keyword",
                    )
                )
        else:
            # Fallback for SQLite in-memory unit tests
            stmt = select(DocumentChunk).where(and_(*where_clauses))
            result = await session.execute(stmt)
            chunks = result.scalars().all()

            scored_chunks: list[tuple[Any, float]] = []
            for chunk in chunks:
                score = cls._sqlite_lexical_score(query, chunk.content, chunk.section_title)
                if score > 0.0:
                    scored_chunks.append((chunk, score))

            scored_chunks.sort(key=lambda x: -x[1])
            top_candidates = scored_chunks[:candidate_k]

            for rank, (chunk, score) in enumerate(top_candidates, start=1):
                candidates.append(
                    CandidateMatch(
                        chunk=chunk,
                        score=score,
                        rank=rank,
                        source="keyword",
                    )
                )

        logger.debug(
            "Keyword retrieval found %d candidates for org_id=%s (candidate_k=%d)",
            len(candidates),
            organization_id,
            candidate_k,
        )
        return candidates
