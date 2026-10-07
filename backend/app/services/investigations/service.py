"""Durable investigation job lifecycle. The database row is the source of truth."""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import ConflictException, NotFoundException
from app.models.incident import Incident
from app.models.investigation import (
    HypothesisEvidenceLink,
    InvestigationErrorCategory,
    InvestigationJob,
    InvestigationStatus,
    RootCauseHypothesis,
)
from app.services.incidents.service import IncidentService

logger = logging.getLogger("app.services.investigations.service")

_ACTIVE_STATUSES = (
    InvestigationStatus.QUEUED.value,
    InvestigationStatus.RUNNING.value,
)

# Forward-only transitions. Cancellation is only honored from queued.
# Enforced by conditional UPDATEs (WHERE status = <expected>) in
# claim/complete/fail/cancel, so stale reads and races yield rowcount 0
# (409) instead of illegal transitions — never by in-memory checks alone.
_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    InvestigationStatus.QUEUED.value: {
        InvestigationStatus.RUNNING.value,
        InvestigationStatus.CANCELLED.value,
    },
    InvestigationStatus.RUNNING.value: {
        InvestigationStatus.COMPLETED.value,
        InvestigationStatus.FAILED.value,
    },
    InvestigationStatus.COMPLETED.value: set(),
    InvestigationStatus.FAILED.value: set(),
    InvestigationStatus.CANCELLED.value: set(),
}


class InvestigationService:
    """CRUD + safe state machine for investigation jobs and hypotheses."""

    # ── jobs ──────────────────────────────────────────────────────────────

    @staticmethod
    async def create_job(
        session: AsyncSession,
        incident: Incident,
        organization_id: str,
        idempotency_key: str | None,
        provider: str | None = None,
        model: str | None = None,
        app_version: str | None = None,
    ) -> tuple[InvestigationJob, bool]:
        """Create a queued job, or return the existing one on duplicate requests.

        Dedupe order: (1) explicit idempotency_key match; (2) any active
        (queued/running) job for the incident. Returns (job, created).
        """
        key = idempotency_key.strip() if idempotency_key else None
        # Snapshot plain IDs: the IntegrityError path below rolls back (which
        # expires the ORM instances), so the handler must use locals, never
        # attribute access on possibly-expired objects.
        incident_id: str = incident.id

        if key:
            stmt = select(InvestigationJob).where(
                InvestigationJob.incident_id == incident_id,
                InvestigationJob.organization_id == organization_id,
                InvestigationJob.idempotency_key == key,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                return existing, False

        stmt = (
            select(InvestigationJob)
            .where(
                InvestigationJob.incident_id == incident_id,
                InvestigationJob.organization_id == organization_id,
                InvestigationJob.status.in_(_ACTIVE_STATUSES),
            )
            .order_by(InvestigationJob.requested_at.desc())
        )
        active = (await session.execute(stmt)).scalars().first()
        if active is not None:
            return active, False

        job = InvestigationJob(
            incident_id=incident_id,
            organization_id=organization_id,
            status=InvestigationStatus.QUEUED.value,
            stage="queued",
            progress=0,
            idempotency_key=key,
            provider=provider,
            model=model,
            app_version=app_version,
        )
        session.add(job)
        try:
            await session.commit()
        except IntegrityError:
            # Lost a concurrent-insert race: either the idempotency UNIQUE
            # (same key) or the single-active partial index (key-less
            # concurrent POSTs for one incident). Re-read and return the
            # winner instead of creating a duplicate.
            await session.rollback()
            if key:
                retry = select(InvestigationJob).where(
                    InvestigationJob.incident_id == incident_id,
                    InvestigationJob.organization_id == organization_id,
                    InvestigationJob.idempotency_key == key,
                )
                raced = (await session.execute(retry)).scalar_one_or_none()
                if raced is not None:
                    return raced, False
            # Fall back to the newest active job if one appeared concurrently.
            retry_active = (
                select(InvestigationJob)
                .where(
                    InvestigationJob.incident_id == incident_id,
                    InvestigationJob.organization_id == organization_id,
                    InvestigationJob.status.in_(_ACTIVE_STATUSES),
                )
                .order_by(InvestigationJob.requested_at.desc())
            )
            raced_active = (await session.execute(retry_active)).scalars().first()
            if raced_active is not None:
                return raced_active, False
            raise
        await session.refresh(job)
        logger.info("Created investigation job %s for incident %s", job.id, incident_id)
        return job, True

    @staticmethod
    async def claim_job(
        session: AsyncSession,
        job_id: str,
        organization_id: str,
    ) -> InvestigationJob | None:
        """Atomically claim a queued job (queued -> running).

        Single conditional UPDATE: exactly one worker wins the race. Returns
        the claimed job, or None when already claimed/finished/missing.
        """
        now = datetime.now(UTC)
        stmt = (
            update(InvestigationJob)
            .where(
                InvestigationJob.id == job_id,
                InvestigationJob.organization_id == organization_id,
                InvestigationJob.status == InvestigationStatus.QUEUED.value,
            )
            .values(
                status=InvestigationStatus.RUNNING.value,
                stage="running",
                progress=5,
                started_at=now,
                attempt_count=InvestigationJob.attempt_count + 1,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        if (result.rowcount or 0) != 1:
            return None
        claimed = await InvestigationService.get_job(session, job_id, organization_id)
        if claimed is None:  # pragma: no cover — defensive
            return None
        logger.info("Claimed investigation job %s (attempt %d)", job_id, claimed.attempt_count)
        return claimed

    @staticmethod
    async def claim_next_queued(
        session: AsyncSession,
        organization_id: str | None = None,
    ) -> InvestigationJob | None:
        """Claim the oldest queued (or stale-running, re-queued) job. Worker entry point."""
        stmt = select(InvestigationJob.id).where(
            InvestigationJob.status == InvestigationStatus.QUEUED.value,
        )
        if organization_id:
            stmt = stmt.where(InvestigationJob.organization_id == organization_id)
        stmt = stmt.order_by(InvestigationJob.requested_at.asc()).limit(1)
        job_id = (await session.execute(stmt)).scalar_one_or_none()
        if job_id is None:
            return None
        org_stmt = select(InvestigationJob.organization_id).where(InvestigationJob.id == job_id)
        org_id = (await session.execute(org_stmt)).scalar_one()
        return await InvestigationService.claim_job(session, job_id, org_id)

    @staticmethod
    async def requeue_stale_running(
        session: AsyncSession,
        stale_seconds: int,
        organization_id: str | None = None,
    ) -> int:
        """Re-queue running jobs whose worker died (started_at older than cutoff).

        Jobs exceeding max_attempts are failed instead. Returns count re-queued.
        """
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(seconds=stale_seconds)
        stmt = select(InvestigationJob).where(
            InvestigationJob.status == InvestigationStatus.RUNNING.value,
            InvestigationJob.started_at < cutoff,
        )
        if organization_id:
            stmt = stmt.where(InvestigationJob.organization_id == organization_id)
        stale = list((await session.execute(stmt)).scalars().all())
        requeued = 0
        for job in stale:
            if job.attempt_count >= job.max_attempts:
                job.status = InvestigationStatus.FAILED.value
                job.stage = "failed"
                job.error_category = InvestigationErrorCategory.INTERNAL_ERROR.value
                job.error_summary = (
                    "Investigation worker stopped responding; retry budget exhausted."
                )
                job.completed_at = datetime.now(UTC)
            else:
                job.status = InvestigationStatus.QUEUED.value
                job.stage = "queued"
                job.progress = 0
                job.started_at = None
                requeued += 1
        if stale:
            await session.commit()
            logger.info("Reclaimed %d stale jobs (%d re-queued)", len(stale), requeued)
        return requeued

    @staticmethod
    async def update_progress(
        session: AsyncSession,
        job: InvestigationJob,
        stage: str,
        progress: int,
    ) -> None:
        job.stage = stage
        job.progress = max(0, min(100, progress))
        await session.commit()

    @staticmethod
    async def complete_job(
        session: AsyncSession,
        job: InvestigationJob,
        result_summary: dict,
    ) -> InvestigationJob:
        """Atomically complete a running job.

        Conditional UPDATE (running -> completed): if the job was cancelled,
        re-queued, or finished by another executor, zero rows match and a
        409 is raised instead of silently overwriting the newer state.
        """
        now = datetime.now(UTC)
        stmt = (
            update(InvestigationJob)
            .where(
                InvestigationJob.id == job.id,
                InvestigationJob.organization_id == job.organization_id,
                InvestigationJob.status == InvestigationStatus.RUNNING.value,
            )
            .values(
                status=InvestigationStatus.COMPLETED.value,
                stage="completed",
                progress=100,
                completed_at=now,
                error_category=InvestigationErrorCategory.NONE.value,
                error_summary=None,
                result_summary=result_summary,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        if (result.rowcount or 0) != 1:
            raise ConflictException(
                message="Investigation is no longer running; completion refused."
            )
        await session.refresh(job)
        return job

    @staticmethod
    async def fail_job(
        session: AsyncSession,
        job: InvestigationJob,
        error_category: str,
        error_summary: str,
    ) -> InvestigationJob:
        """Atomically fail a running job (same ownership guard as complete)."""
        now = datetime.now(UTC)
        stmt = (
            update(InvestigationJob)
            .where(
                InvestigationJob.id == job.id,
                InvestigationJob.organization_id == job.organization_id,
                InvestigationJob.status == InvestigationStatus.RUNNING.value,
            )
            .values(
                status=InvestigationStatus.FAILED.value,
                stage="failed",
                # Never persist raw tracebacks, keys, or provider payloads —
                # callers must pass pre-sanitized safe text (capped at 500 chars).
                error_category=error_category,
                error_summary=(error_summary or "Investigation failed.")[:500],
                completed_at=now,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        if (result.rowcount or 0) != 1:
            raise ConflictException(
                message="Investigation is no longer running; failure update refused."
            )
        await session.refresh(job)
        return job

    @staticmethod
    async def cancel_job(
        session: AsyncSession,
        job: InvestigationJob,
    ) -> InvestigationJob:
        """Atomically cancel a queued job.

        Conditional UPDATE (queued -> cancelled): a job claimed by a worker
        (or already terminal) matches zero rows and yields 409 instead of
        cancelling a running investigation from a stale read. Repeated
        cancellation of an already-terminal job is likewise 409.
        """
        now = datetime.now(UTC)
        stmt = (
            update(InvestigationJob)
            .where(
                InvestigationJob.id == job.id,
                InvestigationJob.organization_id == job.organization_id,
                InvestigationJob.status == InvestigationStatus.QUEUED.value,
            )
            .values(
                status=InvestigationStatus.CANCELLED.value,
                stage="cancelled",
                completed_at=now,
            )
        )
        result = await session.execute(stmt)
        await session.commit()
        if (result.rowcount or 0) != 1:
            raise ConflictException(message="Only queued investigations can be cancelled.")
        await session.refresh(job)
        return job

    @staticmethod
    async def clear_attempt_artifacts(
        session: AsyncSession,
        job: InvestigationJob,
    ) -> None:
        """Delete hypotheses/links from a previous attempt of this job.

        Makes retries idempotent: a re-queued job that already persisted
        partial results starts from a clean slate instead of duplicating
        hypotheses on re-execution. Explicit deletes (not ORM cascade) so the
        behavior is identical on PostgreSQL and SQLite.
        """
        hyp_ids = select(RootCauseHypothesis.id).where(
            RootCauseHypothesis.investigation_job_id == job.id,
            RootCauseHypothesis.organization_id == job.organization_id,
        )
        await session.execute(
            delete(HypothesisEvidenceLink).where(HypothesisEvidenceLink.hypothesis_id.in_(hyp_ids))
        )
        await session.execute(
            delete(RootCauseHypothesis).where(
                RootCauseHypothesis.investigation_job_id == job.id,
                RootCauseHypothesis.organization_id == job.organization_id,
            )
        )
        await session.commit()

    @staticmethod
    async def get_job(
        session: AsyncSession,
        job_id: str,
        organization_id: str,
    ) -> InvestigationJob | None:
        stmt = select(InvestigationJob).where(
            InvestigationJob.id == job_id,
            InvestigationJob.organization_id == organization_id,
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def list_jobs(
        session: AsyncSession,
        incident_id: str,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[InvestigationJob], int]:
        incident = await IncidentService.get_incident(session, incident_id, organization_id)
        if incident is None:
            raise NotFoundException(message="Incident not found.")
        base = select(InvestigationJob).where(
            InvestigationJob.incident_id == incident_id,
            InvestigationJob.organization_id == organization_id,
        )
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        items = list(
            (
                await session.execute(
                    base.order_by(InvestigationJob.requested_at.desc(), InvestigationJob.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return items, total

    # ── hypotheses ────────────────────────────────────────────────────────

    @staticmethod
    async def list_hypotheses(
        session: AsyncSession,
        job_id: str,
        organization_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[RootCauseHypothesis], int]:
        job = await InvestigationService.get_job(session, job_id, organization_id)
        if job is None:
            raise NotFoundException(message="Investigation not found.")
        base = select(RootCauseHypothesis).where(
            RootCauseHypothesis.investigation_job_id == job_id,
            RootCauseHypothesis.organization_id == organization_id,
        )
        total = (
            await session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0
        items = list(
            (
                await session.execute(
                    base.options(selectinload(RootCauseHypothesis.evidence_links))
                    .order_by(RootCauseHypothesis.created_at.asc(), RootCauseHypothesis.id.asc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return items, total

    @staticmethod
    async def get_hypothesis(
        session: AsyncSession,
        hypothesis_id: str,
        organization_id: str,
    ) -> RootCauseHypothesis | None:
        stmt = (
            select(RootCauseHypothesis)
            .where(
                RootCauseHypothesis.id == hypothesis_id,
                RootCauseHypothesis.organization_id == organization_id,
            )
            .options(selectinload(RootCauseHypothesis.evidence_links))
        )
        return (await session.execute(stmt)).scalar_one_or_none()

    @staticmethod
    async def persist_hypotheses(
        session: AsyncSession,
        job: InvestigationJob,
        drafts: list[dict],
        provider: str | None,
        model: str | None,
    ) -> list[RootCauseHypothesis]:
        """Persist validated hypothesis drafts with their evidence links."""
        persisted: list[RootCauseHypothesis] = []
        for draft in drafts:
            hyp = RootCauseHypothesis(
                investigation_job_id=job.id,
                incident_id=job.incident_id,
                organization_id=job.organization_id,
                claim=draft["claim"],
                rationale=draft["rationale"],
                confidence=draft["confidence"],
                confidence_score=draft.get("confidence_score"),
                status=draft["status"],
                rejection_reason=draft.get("rejection_reason"),
                provider=provider,
                model=model,
            )
            session.add(hyp)
            await session.flush()  # assign id for links
            for link in draft.get("links", []):
                session.add(
                    HypothesisEvidenceLink(
                        hypothesis_id=hyp.id,
                        evidence_event_id=link["evidence_event_id"],
                        organization_id=job.organization_id,
                        link_type=link["link_type"],
                        excerpt=link.get("excerpt"),
                    )
                )
            persisted.append(hyp)
        await session.commit()
        for hyp in persisted:
            await session.refresh(hyp)
        return persisted
