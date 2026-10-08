import logging

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictException, NotFoundException
from app.models.evidence import EvidenceEvent
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.schemas.incidents import EvidenceEventCreate, IncidentCreate, IncidentUpdate

logger = logging.getLogger("app.services.incidents")


class IncidentService:
    """Service layer managing SRE Incidents, Evidence ingestion, and Chronological Timelines."""

    @staticmethod
    async def create_incident(
        session: AsyncSession,
        organization_id: str,
        user_id: str | None,
        payload: IncidentCreate,
    ) -> Incident:
        """Create a new incident scoped to a tenant organization."""
        incident = Incident(
            organization_id=organization_id,
            title=payload.title.strip(),
            description=payload.description.strip() if payload.description else None,
            severity=(
                payload.severity.value
                if isinstance(payload.severity, IncidentSeverity)
                else payload.severity
            ),
            status=(
                payload.status.value
                if isinstance(payload.status, IncidentStatus)
                else payload.status
            ),
            service_name=payload.service_name.strip() if payload.service_name else None,
            environment=payload.environment.strip() if payload.environment else "production",
            created_by_user_id=user_id,
            incident_metadata=payload.incident_metadata,
        )
        session.add(incident)
        await session.commit()
        await session.refresh(incident)
        logger.info(
            "Created incident %s for org %s (severity=%s, status=%s)",
            incident.id,
            organization_id,
            incident.severity,
            incident.status,
        )
        return incident

    @staticmethod
    async def get_incident(
        session: AsyncSession,
        incident_id: str,
        organization_id: str,
    ) -> Incident | None:
        """Fetch incident enforcing strict tenant isolation."""
        stmt = select(Incident).where(
            Incident.id == incident_id,
            Incident.organization_id == organization_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def list_incidents(
        session: AsyncSession,
        organization_id: str,
        status: IncidentStatus | str | None = None,
        severity: IncidentSeverity | str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Incident], int]:
        """List incidents for tenant organization with filtering and pagination."""
        base_query = select(Incident).where(Incident.organization_id == organization_id)

        if status:
            val = status.value if isinstance(status, IncidentStatus) else status
            base_query = base_query.where(Incident.status == val)
        if severity:
            val = severity.value if isinstance(severity, IncidentSeverity) else severity
            base_query = base_query.where(Incident.severity == val)
        if service_name:
            base_query = base_query.where(Incident.service_name == service_name)
        if environment:
            base_query = base_query.where(Incident.environment == environment)

        # Total count query
        count_stmt = select(func.count()).select_from(base_query.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        # Items query ordered by created_at DESC, id DESC
        items_stmt = (
            base_query.order_by(Incident.created_at.desc(), Incident.id.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(items_stmt)
        items = list(result.scalars().all())
        return items, total

    @staticmethod
    async def update_incident(
        session: AsyncSession,
        incident_id: str,
        organization_id: str,
        payload: IncidentUpdate,
    ) -> Incident:
        """Update incident attributes with tenant isolation."""
        incident = await IncidentService.get_incident(session, incident_id, organization_id)
        if incident is None:
            raise NotFoundException(message="Incident not found.")

        if payload.title is not None:
            incident.title = payload.title.strip()
        if payload.description is not None:
            incident.description = payload.description.strip() if payload.description else None
        if payload.severity is not None:
            incident.severity = (
                payload.severity.value
                if isinstance(payload.severity, IncidentSeverity)
                else payload.severity
            )
        if payload.status is not None:
            incident.status = (
                payload.status.value
                if isinstance(payload.status, IncidentStatus)
                else payload.status
            )
        if payload.service_name is not None:
            incident.service_name = payload.service_name.strip() if payload.service_name else None
        if payload.environment is not None:
            incident.environment = payload.environment.strip()
        if payload.incident_metadata is not None:
            incident.incident_metadata = payload.incident_metadata

        await session.commit()
        await session.refresh(incident)
        return incident

    @staticmethod
    async def create_evidence_event(
        session: AsyncSession,
        incident_id: str,
        organization_id: str,
        payload: EvidenceEventCreate,
    ) -> tuple[EvidenceEvent, bool]:
        """
        Ingest an evidence event for an incident idempotently.
        If deduplication_key is provided and an event with that key already exists,
        returns (existing_event, False). Otherwise inserts and returns (new_event, True).
        """
        incident = await IncidentService.get_incident(session, incident_id, organization_id)
        if incident is None:
            raise NotFoundException(message="Incident not found.")

        # Idempotency check (normalize whitespace so " key " matches "key")
        dedup_key = payload.deduplication_key.strip() if payload.deduplication_key else None
        if dedup_key:
            stmt = select(EvidenceEvent).where(
                EvidenceEvent.incident_id == incident_id,
                EvidenceEvent.organization_id == organization_id,
                EvidenceEvent.deduplication_key == dedup_key,
            )
            existing = (await session.execute(stmt)).scalar_one_or_none()
            if existing is not None:
                logger.info(
                    "Duplicate evidence event detected for incident %s (dedup_key=%s). Returning existing event %s.",
                    incident_id,
                    dedup_key,
                    existing.id,
                )
                return existing, False

        evidence = EvidenceEvent(
            incident_id=incident_id,
            organization_id=organization_id,
            source_type=payload.source_type.value,
            event_type=payload.event_type.strip(),
            event_timestamp=payload.event_timestamp,
            summary=payload.summary.strip(),
            normalized_payload=payload.normalized_payload,
            source_reference=payload.source_reference.strip() if payload.source_reference else None,
            deduplication_key=dedup_key,
        )
        session.add(evidence)
        try:
            await session.commit()
        except IntegrityError as exc:
            # Concurrent duplicate insert lost the check-then-insert race.
            # The UNIQUE constraint (incident_id, deduplication_key) rejected it.
            await session.rollback()
            if dedup_key:
                retry_stmt = select(EvidenceEvent).where(
                    EvidenceEvent.incident_id == incident_id,
                    EvidenceEvent.organization_id == organization_id,
                    EvidenceEvent.deduplication_key == dedup_key,
                )
                raced = (await session.execute(retry_stmt)).scalar_one_or_none()
                if raced is not None:
                    logger.info(
                        "Concurrent duplicate evidence event for incident %s (dedup_key=%s). Returning existing event %s.",
                        incident_id,
                        dedup_key,
                        raced.id,
                    )
                    return raced, False
            logger.warning(
                "Evidence insert conflict for incident %s: %s",
                incident_id,
                type(exc).__name__,
            )
            raise ConflictException(
                message="Evidence event conflicts with an existing record."
            ) from exc
        await session.refresh(evidence)
        logger.info(
            "Ingested evidence event %s for incident %s (source=%s, type=%s)",
            evidence.id,
            incident_id,
            evidence.source_type,
            evidence.event_type,
        )

        # Milestone 3A: Safe evidence embedding generation
        settings = get_settings()
        if settings.EVIDENCE_EMBEDDING_ENABLED:
            try:
                from datetime import UTC, datetime

                from app.services.embeddings.providers import get_embedding_provider
                from app.services.investigations.evidence_embedding import (
                    build_evidence_embedding_text,
                    generate_evidence_embedding,
                )

                embed_text = build_evidence_embedding_text(
                    source_type=evidence.source_type,
                    event_type=evidence.event_type,
                    summary=evidence.summary,
                    normalized_payload=evidence.normalized_payload,
                    source_reference=evidence.source_reference,
                )
                provider = get_embedding_provider()
                vec = await generate_evidence_embedding(embed_text, provider=provider)
                if vec is not None:
                    evidence.embedding = vec
                    evidence.embedding_model = provider.model_name
                    evidence.embedded_at = datetime.now(UTC)
                    await session.commit()
                    await session.refresh(evidence)
            except Exception as exc:
                # An embedding failure must never corrupt or duplicate the evidence event.
                # The evidence record itself remains usable through lexical retrieval.
                logger.warning(
                    "Evidence embedding generation failed for event %s (continuing with lexical-only): %s",
                    evidence.id,
                    type(exc).__name__,
                )
                try:
                    await session.rollback()
                    reloaded = await session.get(EvidenceEvent, evidence.id)
                    if reloaded is not None:
                        evidence = reloaded
                except Exception:
                    pass

        return evidence, True

    @staticmethod
    async def list_evidence(
        session: AsyncSession,
        incident_id: str,
        organization_id: str,
        source_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EvidenceEvent], int]:
        """List raw evidence events attached to an incident with tenant isolation."""
        incident = await IncidentService.get_incident(session, incident_id, organization_id)
        if incident is None:
            raise NotFoundException(message="Incident not found.")

        base_query = select(EvidenceEvent).where(
            EvidenceEvent.incident_id == incident_id,
            EvidenceEvent.organization_id == organization_id,
        )
        if source_type:
            base_query = base_query.where(EvidenceEvent.source_type == source_type)

        count_stmt = select(func.count()).select_from(base_query.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        items_stmt = (
            base_query.order_by(
                EvidenceEvent.event_timestamp.asc(),
                EvidenceEvent.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(items_stmt)
        items = list(result.scalars().all())
        return items, total

    @staticmethod
    async def get_timeline(
        session: AsyncSession,
        incident_id: str,
        organization_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[EvidenceEvent], int]:
        """
        Build the deterministic incident timeline from persisted evidence.
        Ordered strictly chronologically by event_timestamp ASC, tie-breaker id ASC.
        """
        incident = await IncidentService.get_incident(session, incident_id, organization_id)
        if incident is None:
            raise NotFoundException(message="Incident not found.")

        base_query = select(EvidenceEvent).where(
            EvidenceEvent.incident_id == incident_id,
            EvidenceEvent.organization_id == organization_id,
        )

        count_stmt = select(func.count()).select_from(base_query.subquery())
        total = (await session.execute(count_stmt)).scalar() or 0

        # Deterministic chronological order with tie breaker
        timeline_stmt = (
            base_query.order_by(
                EvidenceEvent.event_timestamp.asc(),
                EvidenceEvent.id.asc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await session.execute(timeline_stmt)
        events = list(result.scalars().all())
        return events, total
