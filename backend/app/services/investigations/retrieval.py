"""Deterministic evidence retrieval for TracePilot investigations.

Builds on the existing retrieval stack:

- Incident evidence (``evidence_events``) is ranked lexically in-process with a
  Reciprocal Rank Fusion of two deterministic signals (term-overlap ranking +
  recency ranking). The ``evidence_events`` table carries no embedding column
  in the Milestone 1 schema, so incident-evidence ranking is lexical by design;
  the fusion still uses RRF (k from ``settings.RRF_K``) so the combination
  stays deterministic and rank-based.
- Runbooks / operational documents reuse the existing
  :class:`RetrievalService` hybrid pipeline (vector + keyword + RRF) when
  ``INVESTIGATION_RUNBOOK_HYBRID`` is enabled and embeddings are available,
  otherwise the keyword branch (offline-safe, deterministic). Tenant scoping
  is enforced by the underlying retrievers via ``organization_id``.

Every retrieval path filters by ``organization_id`` before results are
combined, and every returned item carries provenance (evidence ID, source
type, timestamp, summary, source reference, retrieval method, score/rank).
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.evidence import EvidenceEvent

logger = logging.getLogger("app.services.investigations.retrieval")


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"\b\w+\b", text.lower()) if len(t) > 2}


@dataclass
class RetrievedEvidence:
    """One evidence event with retrieval provenance."""

    event: EvidenceEvent
    retrieval_method: str
    score: float | None
    rank: int | None


def _rrf_fuse(
    ranking_a: list[str],
    ranking_b: list[str],
    rrf_k: int,
) -> list[tuple[str, float]]:
    """Fuse two ID rankings with Reciprocal Rank Fusion (deterministic).

    Tie-break by evidence ID so repeated runs return identical order.
    """
    scores: dict[str, float] = {}
    for rank, eid in enumerate(ranking_a, start=1):
        scores[eid] = scores.get(eid, 0.0) + 1.0 / (rrf_k + rank)
    for rank, eid in enumerate(ranking_b, start=1):
        scores[eid] = scores.get(eid, 0.0) + 1.0 / (rrf_k + rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))


class InvestigationRetrievalService:
    """Tenant-scoped evidence + runbook retrieval for investigations."""

    @staticmethod
    async def retrieve_evidence(
        session: AsyncSession,
        organization_id: str,
        incident_id: str,
        query: str,
        limit: int = 20,
    ) -> list[RetrievedEvidence]:
        """Retrieve and rank incident evidence with provenance.

        The tenant filter (organization_id + incident_id) is applied in the
        database query before any ranking. Returns at most ``limit`` items;
        returns an empty list (never fabricated evidence) when nothing matches.
        """
        settings = get_settings()
        limit = max(1, min(limit, 100))
        # Bounded fetch: ranking needs the incident's evidence set, but an
        # incident with a pathological event volume must not blow up memory.
        # The cap is far above any realistic incident; retrieval stays exact
        # below it.
        fetch_cap = max(limit, settings.INVESTIGATION_EVIDENCE_FETCH_CAP)

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
            .limit(fetch_cap)
        )
        events = list((await session.execute(stmt)).scalars().all())
        if not events:
            return []

        query_terms = _tokenize(query)
        lexical_scored: list[tuple[str, float]] = []
        for ev in events:
            haystack = _tokenize(
                f"{ev.summary} {ev.event_type} {ev.source_type} {ev.source_reference or ''}"
            )
            overlap = len(query_terms & haystack) if query_terms else 0
            phrase_bonus = 0.5 if query.strip().lower() in ev.summary.lower() else 0.0
            lexical_scored.append((ev.id, float(overlap) + phrase_bonus))
        # Deterministic order: score desc, timestamp asc, id asc.
        by_id = {ev.id: ev for ev in events}
        lexical_ranking = [
            eid
            for eid, _ in sorted(
                lexical_scored,
                key=lambda kv: (-kv[1], by_id[kv[0]].event_timestamp, kv[0]),
            )
        ]
        # Recency ranking: most recent first. Stable sort over the
        # timestamp-then-id ordered fetch preserves id-asc within ties.
        recency_ranking = [
            ev.id for ev in sorted(events, key=lambda e: e.event_timestamp, reverse=True)
        ]

        fused = _rrf_fuse(lexical_ranking, recency_ranking, settings.RRF_K)
        in_lexical_top = set(lexical_ranking[:limit])
        in_recency_top = set(recency_ranking[:limit])

        results: list[RetrievedEvidence] = []
        for rank, (eid, score) in enumerate(fused[:limit], start=1):
            in_both = eid in in_lexical_top and eid in in_recency_top
            results.append(
                RetrievedEvidence(
                    event=by_id[eid],
                    retrieval_method="hybrid" if in_both else "lexical",
                    score=round(score, 6),
                    rank=rank,
                )
            )
        return results

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
