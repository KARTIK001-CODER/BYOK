"""Safe, idempotent, tenant-scoped backfill of evidence embeddings for TracePilot."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import EvidenceEvent
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.embeddings.providers import get_embedding_provider
from app.services.investigations.evidence_embedding import (
    build_evidence_embedding_text,
    generate_evidence_embedding,
)

logger = logging.getLogger("app.services.investigations.backfill")


@dataclass
class BackfillStats:
    total_eligible: int = 0
    processed: int = 0
    embedded: int = 0
    skipped: int = 0
    failed: int = 0
    batch_count: int = 0
    dry_run: bool = False


class EvidenceEmbeddingBackfillService:
    """Service orchestrating batch backfilling of evidence vector embeddings."""

    @staticmethod
    async def backfill(
        session: AsyncSession,
        batch_size: int = 50,
        organization_id: str | None = None,
        incident_id: str | None = None,
        dry_run: bool = False,
        force_reembed: bool = False,
        provider: BaseEmbeddingProvider | None = None,
    ) -> BackfillStats:
        """Backfill vector embeddings for evidence events idempotently and safely.

        Args:
            session: Async database session.
            batch_size: Number of records to process per batch.
            organization_id: Optional filter for tenant isolation.
            incident_id: Optional filter for a specific incident.
            dry_run: If True, inspect records without computing or saving embeddings.
            force_reembed: If True, overwrite existing embeddings. Default False.
            provider: Optional custom embedding provider.

        Returns:
            BackfillStats detailing progress and outcomes.
        """
        stats = BackfillStats(dry_run=dry_run)
        batch_size = max(1, min(batch_size, 500))

        # 1. Base query for eligible records
        base_stmt = select(EvidenceEvent)
        if organization_id:
            base_stmt = base_stmt.where(EvidenceEvent.organization_id == organization_id)
        if incident_id:
            base_stmt = base_stmt.where(EvidenceEvent.incident_id == incident_id)

        if not force_reembed:
            query_stmt = base_stmt.where(EvidenceEvent.embedding.is_(None))
        else:
            query_stmt = base_stmt

        query_stmt = query_stmt.order_by(
            EvidenceEvent.event_timestamp.asc(),
            EvidenceEvent.id.asc(),
        )

        all_events = list((await session.execute(query_stmt)).scalars().all())
        stats.total_eligible = len(all_events)

        logger.info(
            "Evidence backfill started: eligible=%d, dry_run=%s, org_filter=%s, incident_filter=%s",
            stats.total_eligible,
            dry_run,
            organization_id,
            incident_id,
        )

        if dry_run or not all_events:
            stats.processed = stats.total_eligible
            return stats

        embed_provider = provider or get_embedding_provider()

        # 2. Process in bounded batches
        for offset in range(0, len(all_events), batch_size):
            batch = all_events[offset : offset + batch_size]
            stats.batch_count += 1
            batch_embedded = 0

            for ev in batch:
                stats.processed += 1
                try:
                    text = build_evidence_embedding_text(
                        source_type=ev.source_type,
                        event_type=ev.event_type,
                        summary=ev.summary,
                        normalized_payload=ev.normalized_payload,
                        source_reference=ev.source_reference,
                    )
                    vec = await generate_evidence_embedding(text, provider=embed_provider)
                    if vec is not None:
                        ev.embedding = vec
                        ev.embedding_model = embed_provider.model_name
                        ev.embedded_at = datetime.now(UTC)
                        stats.embedded += 1
                        batch_embedded += 1
                    else:
                        stats.failed += 1
                except Exception as exc:
                    stats.failed += 1
                    logger.warning(
                        "Failed to backfill embedding for evidence %s: %s",
                        ev.id,
                        type(exc).__name__,
                    )

            # Commit batch atomically
            try:
                await session.commit()
                logger.info(
                    "Backfill batch %d committed: %d embedded, cumulative progress %d/%d",
                    stats.batch_count,
                    batch_embedded,
                    stats.processed,
                    stats.total_eligible,
                )
            except Exception as exc:
                await session.rollback()
                logger.error("Failed to commit backfill batch %d: %s", stats.batch_count, exc)
                stats.failed += batch_embedded
                stats.embedded -= batch_embedded

        return stats
