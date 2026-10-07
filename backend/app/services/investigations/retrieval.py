"""Tenant-safe hybrid evidence retrieval for TracePilot investigations.

Upgrades investigation evidence retrieval to a multi-channel hybrid system combining:
1. Lexical search (term overlap + exact phrase matching)
2. Semantic vector similarity (FastEmbed BAAI/bge-small-en-v1.5 + pgvector cosine distance)
3. Recency signal (chronological proximity ranking)
4. Reciprocal Rank Fusion (RRF) with deterministic tie-breaking.

Tenant isolation is strictly enforced inside database queries before any ranking:
`organization_id == caller_organization AND incident_id == requested_incident`.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.tracing import get_current_trace
from app.models.evidence import EvidenceEvent
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.providers import get_embedding_provider
from app.services.investigations.evidence_embedding import generate_query_embedding

logger = logging.getLogger("app.services.investigations.retrieval")


def _tokenize(text: str) -> set[str]:
    """Extract lowercase token set with minimum length 3."""
    return {t for t in re.findall(r"\b\w+\b", text.lower()) if len(t) > 2}


def _cosine_similarity(vec1: Sequence[float], vec2: Sequence[float]) -> float:
    """Compute cosine similarity between two float vectors in Python."""
    dot = sum(a * b for a, b in zip(vec1, vec2, strict=False))
    norm1 = math.sqrt(sum(a * a for a in vec1))
    norm2 = math.sqrt(sum(b * b for b in vec2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return dot / (norm1 * norm2)


@dataclass
class RetrievedEvidence:
    """Evidence candidate with rich retrieval provenance."""

    event: EvidenceEvent
    rank: int
    retrieval_score: float
    retrieval_sources: list[str]  # e.g. ["lexical", "semantic", "recency"]
    retrieval_method: str  # "hybrid" | "semantic" | "lexical" | "recency"
    score: float | None = None
    lexical_rank: int | None = None
    semantic_rank: int | None = None
    recency_rank: int | None = None

    def __post_init__(self) -> None:
        if self.score is None:
            self.score = self.retrieval_score

    @property
    def evidence_event_id(self) -> str:
        return self.event.id

    @property
    def event_timestamp(self) -> datetime:
        return self.event.event_timestamp

    @property
    def source_type(self) -> str:
        return self.event.source_type

    @property
    def summary(self) -> str:
        return self.event.summary


def _rrf_fuse_multichannel(
    lexical_ranking: list[str],
    semantic_ranking: list[str],
    recency_ranking: list[str],
    rrf_k: int,
    by_id: dict[str, EvidenceEvent],
    positive_lexical_ids: set[str],
    positive_semantic_ids: set[str],
) -> list[tuple[str, float, list[str], int | None, int | None, int | None]]:
    """Fuse up to three ranked ID channels with Reciprocal Rank Fusion.

    Tie-breaker is deterministic: (-rrf_score, event_timestamp ASC, id ASC).
    """
    scores: dict[str, float] = {}
    sources_map: dict[str, list[str]] = {}

    lex_rank_map = {eid: r for r, eid in enumerate(lexical_ranking, start=1)}
    sem_rank_map = {eid: r for r, eid in enumerate(semantic_ranking, start=1)}
    rec_rank_map = {eid: r for r, eid in enumerate(recency_ranking, start=1)}

    all_ids = set(lex_rank_map.keys()) | set(sem_rank_map.keys()) | set(rec_rank_map.keys())

    for eid in all_ids:
        s = 0.0
        sources: list[str] = []

        if eid in lex_rank_map:
            s += 1.0 / (rrf_k + lex_rank_map[eid])
            # Mark as lexical source if in top lexical or has positive lexical match
            if eid in positive_lexical_ids or not positive_lexical_ids:
                sources.append("lexical")

        if eid in sem_rank_map:
            s += 1.0 / (rrf_k + sem_rank_map[eid])
            if eid in positive_semantic_ids or not positive_semantic_ids:
                sources.append("semantic")

        if eid in rec_rank_map:
            s += 1.0 / (rrf_k + rec_rank_map[eid])
            sources.append("recency")

        # Fallback if no specific source tagged
        if not sources:
            sources.append("recency" if eid in rec_rank_map else "lexical")

        scores[eid] = s
        sources_map[eid] = sources

    # Deterministic tie-breaker: score desc, timestamp asc, id asc
    sorted_ids = sorted(
        all_ids,
        key=lambda eid: (-scores[eid], by_id[eid].event_timestamp, eid),
    )

    return [
        (
            eid,
            scores[eid],
            sources_map[eid],
            lex_rank_map.get(eid),
            sem_rank_map.get(eid),
            rec_rank_map.get(eid),
        )
        for eid in sorted_ids
    ]


class InvestigationRetrievalService:
    """Tenant-scoped hybrid evidence and runbook retrieval for investigations."""

    @classmethod
    async def retrieve_evidence(
        cls,
        session: AsyncSession,
        organization_id: str,
        incident_id: str,
        query: str,
        limit: int = 20,
        time_window_start: datetime | None = None,
        time_window_end: datetime | None = None,
        source_types: list[str] | None = None,
        provider: BaseEmbeddingProvider | None = None,
    ) -> list[RetrievedEvidence]:
        """Retrieve and rank incident evidence using multi-channel hybrid search.

        Combines:
        1. Lexical retrieval
        2. Semantic vector retrieval (via pgvector / FastEmbed)
        3. Recency signal
        Fused via Reciprocal Rank Fusion (RRF).

        Filters by organization_id AND incident_id at the database level before ranking.
        """
        t0 = time.perf_counter()
        settings = get_settings()
        limit = max(1, min(limit, 100))
        fetch_cap = max(limit, settings.INVESTIGATION_EVIDENCE_FETCH_CAP)

        # ── 1. Fetch tenant-scoped incident evidence ─────────────────────
        where_clauses = [
            EvidenceEvent.organization_id == organization_id,
            EvidenceEvent.incident_id == incident_id,
        ]
        if time_window_start is not None:
            where_clauses.append(EvidenceEvent.event_timestamp >= time_window_start)
        if time_window_end is not None:
            where_clauses.append(EvidenceEvent.event_timestamp <= time_window_end)
        if source_types:
            where_clauses.append(EvidenceEvent.source_type.in_(source_types))

        stmt = (
            select(EvidenceEvent)
            .where(*where_clauses)
            .order_by(
                EvidenceEvent.event_timestamp.asc(),
                EvidenceEvent.id.asc(),
            )
            .limit(fetch_cap)
        )
        events = list((await session.execute(stmt)).scalars().all())
        if not events:
            return []

        by_id: dict[str, EvidenceEvent] = {ev.id: ev for ev in events}

        # ── 2. Lexical Channel ───────────────────────────────────────────
        query_terms = _tokenize(query)
        lexical_scored: list[tuple[str, float]] = []
        positive_lexical_ids: set[str] = set()

        for ev in events:
            haystack = _tokenize(
                f"{ev.summary} {ev.event_type} {ev.source_type} {ev.source_reference or ''}"
            )
            overlap = len(query_terms & haystack) if query_terms else 0
            phrase_bonus = 0.5 if query.strip().lower() in ev.summary.lower() else 0.0
            score = float(overlap) + phrase_bonus
            lexical_scored.append((ev.id, score))
            if score > 0:
                positive_lexical_ids.add(ev.id)

        # Lexical tie-breaker: score desc, timestamp asc, id asc
        lexical_ranking = [
            eid
            for eid, _ in sorted(
                lexical_scored,
                key=lambda kv: (-kv[1], by_id[kv[0]].event_timestamp, kv[0]),
            )
        ]

        # ── 3. Semantic Vector Channel ───────────────────────────────────
        semantic_ranking: list[str] = []
        positive_semantic_ids: set[str] = set()
        embed_t0 = time.perf_counter()
        embed_ms = 0.0

        if settings.EVIDENCE_EMBEDDING_ENABLED:
            try:
                embed_provider = provider or get_embedding_provider()
                query_vector = await generate_query_embedding(query, provider=embed_provider)
                embed_ms = (time.perf_counter() - embed_t0) * 1000.0

                if query_vector is not None:
                    # Filter events that have an embedding vector
                    events_with_embedding = [ev for ev in events if ev.embedding is not None]
                    if events_with_embedding:
                        dialect_name = (
                            session.bind.dialect.name if session.bind else "postgresql"
                        )
                        semantic_scored: list[tuple[str, float]] = []

                        if dialect_name == "postgresql":
                            # Native pgvector cosine distance
                            vec_dist = EvidenceEvent.embedding.cosine_distance(query_vector)
                            vec_stmt = (
                                select(EvidenceEvent.id, vec_dist.label("distance"))
                                .where(
                                    *where_clauses,
                                    EvidenceEvent.embedding.is_not(None),
                                )
                                .order_by(
                                    vec_dist.asc(),
                                    EvidenceEvent.event_timestamp.asc(),
                                    EvidenceEvent.id.asc(),
                                )
                                .limit(min(settings.EVIDENCE_SEMANTIC_TOP_K, fetch_cap))
                            )
                            rows = (await session.execute(vec_stmt)).all()
                            for eid, distance in rows:
                                dist_val = float(distance) if distance is not None else 1.0
                                sim = max(0.0, min(1.0, 1.0 - dist_val))
                                semantic_scored.append((eid, sim))
                                if sim > 0.1:
                                    positive_semantic_ids.add(eid)
                        else:
                            # SQLite in-memory / fallback computation
                            for ev in events_with_embedding:
                                sim = _cosine_similarity(query_vector, ev.embedding)
                                sim = max(0.0, min(1.0, sim))
                                semantic_scored.append((ev.id, sim))
                                if sim > 0.1:
                                    positive_semantic_ids.add(ev.id)

                            semantic_scored.sort(
                                key=lambda kv: (-kv[1], by_id[kv[0]].event_timestamp, kv[0])
                            )

                        semantic_ranking = [
                            eid
                            for eid, _ in semantic_scored[: settings.EVIDENCE_SEMANTIC_TOP_K]
                        ]
            except Exception as exc:
                logger.warning(
                    "Semantic retrieval channel failed (safe fallback to lexical+recency): %s",
                    type(exc).__name__,
                )
                semantic_ranking = []

        # ── 4. Recency Channel ───────────────────────────────────────────
        recency_ranking = [
            ev.id
            for ev in sorted(
                events,
                key=lambda e: (e.event_timestamp, e.id),
                reverse=True,
            )[: settings.EVIDENCE_RECENCY_TOP_K]
        ]

        # ── 5. Reciprocal Rank Fusion ────────────────────────────────────
        fused = _rrf_fuse_multichannel(
            lexical_ranking=lexical_ranking[: settings.EVIDENCE_LEXICAL_TOP_K],
            semantic_ranking=semantic_ranking,
            recency_ranking=recency_ranking,
            rrf_k=settings.RRF_K,
            by_id=by_id,
            positive_lexical_ids=positive_lexical_ids,
            positive_semantic_ids=positive_semantic_ids,
        )

        results: list[RetrievedEvidence] = []
        for rank, (eid, rrf_score, sources, lex_r, sem_r, rec_r) in enumerate(
            fused[:limit], start=1
        ):
            # Determine high-level method name for backward compatibility
            if len(sources) > 1:
                method = "hybrid"
            elif "semantic" in sources:
                method = "semantic"
            elif "lexical" in sources:
                method = "lexical"
            else:
                method = "recency"

            results.append(
                RetrievedEvidence(
                    event=by_id[eid],
                    rank=rank,
                    retrieval_score=round(rrf_score, 6),
                    retrieval_sources=sources,
                    retrieval_method=method,
                    score=round(rrf_score, 6),
                    lexical_rank=lex_r,
                    semantic_rank=sem_r,
                    recency_rank=rec_r,
                )
            )

        total_ms = (time.perf_counter() - t0) * 1000.0

        # Observability / Tracing
        trace = get_current_trace()
        if trace:
            trace.record("evidence_retrieval_total_ms", total_ms)
            trace.record("evidence_embedding_ms", embed_ms)
            trace.set_counter("evidence_lexical_candidates", len(lexical_ranking))
            trace.set_counter("evidence_semantic_candidates", len(semantic_ranking))
            trace.set_counter("evidence_final_candidates", len(results))

        logger.info(
            "Evidence retrieval completed: org=%s, incident=%s, "
            "lexical_cands=%d, semantic_cands=%d, final_cands=%d, "
            "embed_ms=%.2f, total_ms=%.2f",
            organization_id[:8] + "..." if len(organization_id) > 8 else organization_id,
            incident_id[:8] + "..." if len(incident_id) > 8 else incident_id,
            len(lexical_ranking),
            len(semantic_ranking),
            len(results),
            embed_ms,
            total_ms,
        )

        return results

    @classmethod
    async def retrieve_evidence_lexical_only(
        cls,
        session: AsyncSession,
        organization_id: str,
        incident_id: str,
        query: str,
        limit: int = 20,
    ) -> list[RetrievedEvidence]:
        """Evaluation helper: execute lexical-only evidence retrieval."""
        settings = get_settings()
        limit = max(1, min(limit, 100))
        stmt = (
            select(EvidenceEvent)
            .where(
                EvidenceEvent.organization_id == organization_id,
                EvidenceEvent.incident_id == incident_id,
            )
            .order_by(
                EvidenceEvent.event_timestamp.asc(),
                EvidenceEvent.id.asc(),
            )
            .limit(settings.INVESTIGATION_EVIDENCE_FETCH_CAP)
        )
        events = list((await session.execute(stmt)).scalars().all())
        if not events:
            return []

        by_id = {ev.id: ev for ev in events}
        query_terms = _tokenize(query)
        lexical_scored: list[tuple[str, float]] = []

        for ev in events:
            haystack = _tokenize(
                f"{ev.summary} {ev.event_type} {ev.source_type} {ev.source_reference or ''}"
            )
            overlap = len(query_terms & haystack) if query_terms else 0
            phrase_bonus = 0.5 if query.strip().lower() in ev.summary.lower() else 0.0
            lexical_scored.append((ev.id, float(overlap) + phrase_bonus))

        lexical_scored.sort(key=lambda kv: (-kv[1], by_id[kv[0]].event_timestamp, kv[0]))

        return [
            RetrievedEvidence(
                event=by_id[eid],
                rank=rank,
                retrieval_score=round(score, 6),
                retrieval_sources=["lexical"],
                retrieval_method="lexical",
                score=round(score, 6),
                lexical_rank=rank,
            )
            for rank, (eid, score) in enumerate(lexical_scored[:limit], start=1)
        ]

    @classmethod
    async def retrieve_evidence_semantic_only(
        cls,
        session: AsyncSession,
        organization_id: str,
        incident_id: str,
        query: str,
        limit: int = 20,
        provider: BaseEmbeddingProvider | None = None,
    ) -> list[RetrievedEvidence]:
        """Evaluation helper: execute semantic-only evidence retrieval."""
        settings = get_settings()
        limit = max(1, min(limit, 100))
        stmt = (
            select(EvidenceEvent)
            .where(
                EvidenceEvent.organization_id == organization_id,
                EvidenceEvent.incident_id == incident_id,
                EvidenceEvent.embedding.is_not(None),
            )
            .order_by(
                EvidenceEvent.event_timestamp.asc(),
                EvidenceEvent.id.asc(),
            )
            .limit(settings.INVESTIGATION_EVIDENCE_FETCH_CAP)
        )
        events = list((await session.execute(stmt)).scalars().all())
        if not events:
            return []

        by_id = {ev.id: ev for ev in events}
        embed_provider = provider or get_embedding_provider()
        query_vector = await generate_query_embedding(query, provider=embed_provider)
        if query_vector is None:
            return []

        scored: list[tuple[str, float]] = []
        for ev in events:
            sim = _cosine_similarity(query_vector, ev.embedding)
            sim = max(0.0, min(1.0, sim))
            scored.append((ev.id, sim))

        scored.sort(key=lambda kv: (-kv[1], by_id[kv[0]].event_timestamp, kv[0]))

        return [
            RetrievedEvidence(
                event=by_id[eid],
                rank=rank,
                retrieval_score=round(score, 6),
                retrieval_sources=["semantic"],
                retrieval_method="semantic",
                score=round(score, 6),
                semantic_rank=rank,
            )
            for rank, (eid, score) in enumerate(scored[:limit], start=1)
        ]

    @staticmethod
    async def retrieve_runbooks(
        session: AsyncSession,
        organization_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict]:
        """Retrieve relevant runbooks/operational docs via the existing pipeline.

        Strictly tenant-scoped (organization_id enforced inside the retrieval
        service). Never raises: runbook retrieval is advisory and must not fail
        an investigation. Returns provenance dicts.
        """
        from app.services.retrieval.schemas import RetrievalRequest, SearchMode

        settings = get_settings()
        top_k = max(1, min(top_k, 20))
        mode = SearchMode.HYBRID if settings.INVESTIGATION_RUNBOOK_HYBRID else SearchMode.KEYWORD
        try:
            from app.services.retrieval.service import RetrievalService

            response = await RetrievalService.search(
                session=session,
                organization_id=organization_id,
                request=RetrievalRequest(
                    query=query[: settings.MAX_QUERY_LENGTH],
                    search_mode=mode,
                    top_k=top_k,
                    candidate_k=min(settings.DEFAULT_CANDIDATE_K, 50),
                ),
            )
            return [
                {
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "document_name": r.document_name,
                    "knowledge_base_id": r.knowledge_base_id,
                    "content": r.content[:2000],
                    "score": r.score,
                    "rank": r.rank,
                    "retrieval_method": r.source,
                }
                for r in response.results
            ]
        except Exception as exc:  # advisory only — log and continue without runbooks
            logger.warning(
                "Runbook retrieval failed (advisory, continuing): %s", type(exc).__name__
            )
            return []
