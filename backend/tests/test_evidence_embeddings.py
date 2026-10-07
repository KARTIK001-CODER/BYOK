"""Tests for evidence embeddings, text normalization, and backfill service (Milestone 3A)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.evidence import EvidenceEvent
from app.models.incident import Incident
from app.models.organization import Organization
from app.schemas.incidents import EvidenceEventCreate
from app.services.embeddings.base import BaseEmbeddingProvider
from app.services.incidents.service import IncidentService
from app.services.investigations.backfill import EvidenceEmbeddingBackfillService
from app.services.investigations.evidence_embedding import (
    build_evidence_embedding_text,
    generate_evidence_embedding,
    generate_query_embedding,
    is_sensitive_key,
    sanitize_payload,
)


class DummyMockProvider(BaseEmbeddingProvider):
    @property
    def provider_name(self) -> str:
        return "dummy-mock"

    @property
    def model_name(self) -> str:
        return "dummy-model"

    @property
    def dimension(self) -> int:
        return 4

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Deterministic mock vector of dimension 4
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_query(self, query: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


def test_sensitive_key_detection():
    assert is_sensitive_key("authorization") is True
    assert is_sensitive_key("auth_token") is True
    assert is_sensitive_key("api_key") is True
    assert is_sensitive_key("client_secret") is True
    assert is_sensitive_key("cookie") is True
    assert is_sensitive_key("db_password") is True
    assert is_sensitive_key("jwt") is True
    assert is_sensitive_key("service_name") is False
    assert is_sensitive_key("status_code") is False


def test_sanitize_payload_redacts_secrets_and_sorts():
    payload = {
        "service": "billing-service",
        "api_key": "secret-12345",
        "authorization": "Bearer eyJhbGciOi...",
        "status_code": 500,
        "region": "us-east-1",
        "details": {"nested": "value"},  # Non-scalar dropped
    }
    sanitized = sanitize_payload(payload)
    assert "api_key" not in sanitized
    assert "authorization" not in sanitized
    assert "details" not in sanitized
    assert sanitized["service"] == "billing-service"
    assert sanitized["status_code"] == "500"
    assert sanitized["region"] == "us-east-1"


def test_build_evidence_embedding_text_canonical():
    text = build_evidence_embedding_text(
        source_type="log",
        event_type="database.connection_timeout",
        summary="Database pool exhausted after deployment",
        normalized_payload={
            "service": "payment-api",
            "active_connections": 100,
            "secret_token": "leak-attempt",
        },
        source_reference="k8s://pods/payment-123",
    )
    assert "source_type: log" in text
    assert "event_type: database.connection_timeout" in text
    assert "service: payment-api" in text
    assert "summary: Database pool exhausted after deployment" in text
    assert "active_connections=100" in text
    assert "secret_token" not in text
    assert "reference: k8s://pods/payment-123" in text


@pytest.mark.asyncio
async def test_generate_evidence_embedding_safe_fallback():
    # Empty text -> returns None
    assert await generate_evidence_embedding("") is None
    assert await generate_evidence_embedding("   ") is None

    # Working mock provider
    vec = await generate_evidence_embedding("test text", provider=DummyMockProvider())
    assert vec == [0.1, 0.2, 0.3, 0.4]

    # Faulty provider raising exception
    faulty_provider = MagicMock(spec=BaseEmbeddingProvider)
    faulty_provider.embed_documents.side_effect = RuntimeError("Provider down")
    assert await generate_evidence_embedding("test text", provider=faulty_provider) is None

    # Dimension mismatch
    mismatch_provider = MagicMock(spec=BaseEmbeddingProvider)
    mismatch_provider.dimension = 384
    mismatch_provider.embed_documents.return_value = [[0.1, 0.2]]
    assert await generate_evidence_embedding("test text", provider=mismatch_provider) is None


@pytest.mark.asyncio
async def test_generate_query_embedding_safe_fallback():
    assert await generate_query_embedding("") is None
    vec = await generate_query_embedding("query", provider=DummyMockProvider())
    assert vec == [0.1, 0.2, 0.3, 0.4]

    faulty = MagicMock(spec=BaseEmbeddingProvider)
    faulty.embed_query.side_effect = TimeoutError("Embedding timed out")
    assert await generate_query_embedding("query", provider=faulty) is None


@pytest.mark.asyncio
async def test_evidence_ingestion_embedding_generation_success(
    db_session: AsyncSession,
):
    org = Organization(name="Embedding Org", slug="embedding-org")
    db_session.add(org)
    await db_session.flush()

    incident = Incident(
        organization_id=org.id,
        title="Payment Latency Incident",
        severity="high",
        service_name="payment-api",
    )
    db_session.add(incident)
    await db_session.commit()

    provider = DummyMockProvider()
    with patch(
        "app.services.embeddings.providers.get_embedding_provider",
        return_value=provider,
    ):
        event, is_new = await IncidentService.create_evidence_event(
            session=db_session,
            incident_id=incident.id,
            organization_id=org.id,
            payload=EvidenceEventCreate(
                source_type="log",
                event_type="app.error",
                event_timestamp=datetime(2026, 10, 7, 12, 0, 0, tzinfo=UTC),
                summary="Payment connection refused",
                normalized_payload={"service": "payment-api"},
            ),
        )
        assert is_new is True
        assert event.embedding == [0.1, 0.2, 0.3, 0.4]
        assert event.embedding_model == "dummy-model"
        assert event.embedded_at is not None


@pytest.mark.asyncio
async def test_evidence_ingestion_embedding_failure_does_not_corrupt_event(
    db_session: AsyncSession,
):
    org = Organization(name="Fallback Org", slug="fallback-org")
    db_session.add(org)
    await db_session.flush()

    incident = Incident(
        organization_id=org.id,
        title="Cache Failure Incident",
        severity="medium",
    )
    db_session.add(incident)
    await db_session.commit()

    # Provider that raises on embedding
    faulty = MagicMock(spec=BaseEmbeddingProvider)
    faulty.dimension = 384
    faulty.embed_documents.side_effect = ConnectionError("Embed service unavailable")

    with patch(
        "app.services.embeddings.providers.get_embedding_provider",
        return_value=faulty,
    ):
        event, is_new = await IncidentService.create_evidence_event(
            session=db_session,
            incident_id=incident.id,
            organization_id=org.id,
            payload=EvidenceEventCreate(
                source_type="metric",
                event_type="cache.miss_rate",
                event_timestamp=datetime(2026, 10, 7, 12, 5, 0, tzinfo=UTC),
                summary="Cache miss rate spiked to 90%",
            ),
        )
        # Event is safely created and persisted despite embedding error!
        assert is_new is True
        assert event.id is not None
        assert event.summary == "Cache miss rate spiked to 90%"
        assert event.embedding is None


@pytest.mark.asyncio
async def test_evidence_backfill_idempotent_and_tenant_scoped(
    db_session: AsyncSession,
):
    org_a = Organization(name="Backfill Org A", slug="backfill-org-a")
    org_b = Organization(name="Backfill Org B", slug="backfill-org-b")
    db_session.add_all([org_a, org_b])
    await db_session.flush()

    inc_a = Incident(organization_id=org_a.id, title="Incident A", severity="high")
    inc_b = Incident(organization_id=org_b.id, title="Incident B", severity="low")
    db_session.add_all([inc_a, inc_b])
    await db_session.flush()

    # Create un-embedded evidence in both tenants
    ev_a1 = EvidenceEvent(
        incident_id=inc_a.id,
        organization_id=org_a.id,
        source_type="log",
        event_type="app.log",
        event_timestamp=datetime(2026, 10, 7, 10, 0, 0, tzinfo=UTC),
        summary="A1 un-embedded",
        embedding=None,
    )
    ev_a2 = EvidenceEvent(
        incident_id=inc_a.id,
        organization_id=org_a.id,
        source_type="alert",
        event_type="app.alert",
        event_timestamp=datetime(2026, 10, 7, 10, 1, 0, tzinfo=UTC),
        summary="A2 already embedded",
        embedding=[0.9, 0.9, 0.9, 0.9],
    )
    ev_b = EvidenceEvent(
        incident_id=inc_b.id,
        organization_id=org_b.id,
        source_type="log",
        event_type="app.log",
        event_timestamp=datetime(2026, 10, 7, 10, 2, 0, tzinfo=UTC),
        summary="B un-embedded",
        embedding=None,
    )
    db_session.add_all([ev_a1, ev_a2, ev_b])
    await db_session.commit()

    provider = DummyMockProvider()

    # 1. Dry run for Org A: inspects only un-embedded event in Org A, does not mutate
    dry_stats = await EvidenceEmbeddingBackfillService.backfill(
        session=db_session,
        organization_id=org_a.id,
        dry_run=True,
        provider=provider,
    )
    assert dry_stats.dry_run is True
    assert dry_stats.total_eligible == 1  # only ev_a1
    assert dry_stats.embedded == 0

    await db_session.refresh(ev_a1)
    assert ev_a1.embedding is None

    # 2. Real backfill scoped to Org A
    stats = await EvidenceEmbeddingBackfillService.backfill(
        session=db_session,
        organization_id=org_a.id,
        dry_run=False,
        provider=provider,
    )
    assert stats.total_eligible == 1
    assert stats.embedded == 1
    assert stats.processed == 1

    await db_session.refresh(ev_a1)
    await db_session.refresh(ev_a2)
    await db_session.refresh(ev_b)

    assert ev_a1.embedding == [0.1, 0.2, 0.3, 0.4]
    assert ev_a2.embedding == [0.9, 0.9, 0.9, 0.9]  # Existing was preserved
    assert ev_b.embedding is None  # Org B was not touched

    # 3. Running again is idempotent: 0 eligible
    idempotent_stats = await EvidenceEmbeddingBackfillService.backfill(
        session=db_session,
        organization_id=org_a.id,
        dry_run=False,
        provider=provider,
    )
    assert idempotent_stats.total_eligible == 0
    assert idempotent_stats.embedded == 0
