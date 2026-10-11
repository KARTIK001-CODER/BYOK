"""TracePilot Stage D: Reliable Evidence Ingestion, Batch Telemetry & Service Context tests."""

import pytest
from datetime import UTC, datetime
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService
from app.services.investigations.backfill import EvidenceEmbeddingBackfillService
from app.services.investigations.retrieval import InvestigationRetrievalService


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
async def tenant2(db_session: AsyncSession) -> dict:
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="stage-d-tenant2@example.com",
        password_hash=pwd_hash,
        full_name="Stage D Tenant 2",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    org = Organization(name="Stage D Tenant 2 Org", slug="stage-d-tenant-2-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
    )
    await db_session.commit()
    return {"user": user, "org": org, "token": create_access_token(user.id)}


async def _make_incident(client: AsyncClient, headers: dict) -> str:
    payload = {
        "title": "Kafka Consumer Lag Surge",
        "severity": "critical",
        "service_name": "checkout-worker",
        "environment": "production",
    }
    resp = await client.post("/api/v1/incidents", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_single_evidence_ingestion_and_deduplication(
    client: AsyncClient, test_user_and_org: dict
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    incident_id = await _make_incident(client, headers)

    payload = {
        "source_type": "alert",
        "event_type": "alert.fired",
        "event_timestamp": "2026-10-11T12:00:00Z",
        "summary": "Consumer lag threshold exceeded 500k",
        "source_reference": "https://prometheus.internal/alerts/1001",
        "deduplication_key": "lag-alert-1001",
        "normalized_payload": {"consumer_group": "checkout", "lag": 524000},
    }

    # First ingestion -> HTTP 201 Created
    resp1 = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence", headers=headers, json=payload
    )
    assert resp1.status_code == status.HTTP_201_CREATED
    data1 = resp1.json()
    assert data1["id"] is not None
    assert data1["deduplication_key"] == "lag-alert-1001"

    # Second ingestion with same deduplication key -> HTTP 200 OK + Duplicate header
    resp2 = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence", headers=headers, json=payload
    )
    assert resp2.status_code == status.HTTP_200_OK
    assert resp2.headers.get("X-TracePilot-Duplicate") == "true"
    data2 = resp2.json()
    assert data2["id"] == data1["id"]


@pytest.mark.asyncio
async def test_batch_evidence_ingestion_success_and_duplicates(
    client: AsyncClient, test_user_and_org: dict
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    incident_id = await _make_incident(client, headers)

    batch_payload = {
        "items": [
            {
                "source_type": "alert",
                "event_type": "alert.fired",
                "event_timestamp": "2026-10-11T12:00:00Z",
                "summary": "Kafka Lag Critical",
                "deduplication_key": "batch-alert-1",
                "normalized_payload": {"lag": 500000},
            },
            {
                "source_type": "deployment",
                "event_type": "deployment.rollout",
                "event_timestamp": "2026-10-11T12:02:00Z",
                "summary": "Rollout checkout-worker revision v2.8.0",
                "deduplication_key": "batch-deploy-1",
                "normalized_payload": {"revision": "v2.8.0"},
            },
            {
                "source_type": "log",
                "event_type": "log.error",
                "event_timestamp": "2026-10-11T12:03:00Z",
                "summary": "CommitFailedException: Timeout awaiting partition rebalance",
                "deduplication_key": "batch-log-1",
                "normalized_payload": {"exception": "CommitFailedException"},
            },
        ]
    }

    # Submit batch -> 3 accepted
    resp1 = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence/batch",
        headers=headers,
        json=batch_payload,
    )
    assert resp1.status_code == status.HTTP_200_OK
    data1 = resp1.json()
    assert data1["total_submitted"] == 3
    assert data1["accepted_count"] == 3
    assert data1["duplicate_count"] == 0
    assert len(data1["results"]) == 3
    assert all(r["status"] == "accepted" for r in data1["results"])

    # Re-submit identical batch -> 3 duplicates
    resp2 = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence/batch",
        headers=headers,
        json=batch_payload,
    )
    assert resp2.status_code == status.HTTP_200_OK
    data2 = resp2.json()
    assert data2["total_submitted"] == 3
    assert data2["accepted_count"] == 0
    assert data2["duplicate_count"] == 3
    assert all(r["status"] == "duplicate" for r in data2["results"])


@pytest.mark.asyncio
async def test_batch_evidence_ingestion_max_limit_enforced(
    client: AsyncClient, test_user_and_org: dict
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    incident_id = await _make_incident(client, headers)

    # 101 items exceeds max limit of 100
    oversized_items = [
        {
            "source_type": "log",
            "event_type": "log.info",
            "event_timestamp": "2026-10-11T12:00:00Z",
            "summary": f"Telemetry probe #{i}",
            "normalized_payload": {"i": i},
        }
        for i in range(101)
    ]

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence/batch",
        headers=headers,
        json={"items": oversized_items},
    )
    assert resp.status_code in (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        422,
    )


@pytest.mark.asyncio
async def test_batch_evidence_tenant_isolation(
    client: AsyncClient, test_user_and_org: dict, tenant2: dict
):
    user1: User = test_user_and_org["user"]
    headers1 = _headers(user1)
    incident_id = await _make_incident(client, headers1)

    # Tenant 2 tries to post evidence to Tenant 1's incident
    user2: User = tenant2["user"]
    headers2 = _headers(user2)

    batch_payload = {
        "items": [
            {
                "source_type": "alert",
                "event_type": "alert.fired",
                "event_timestamp": "2026-10-11T12:00:00Z",
                "summary": "Cross-tenant intrusion attempt",
            }
        ]
    }

    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence/batch",
        headers=headers2,
        json=batch_payload,
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_evidence_retrieval_freshness(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    headers = _headers(user)
    incident_id = await _make_incident(client, headers)

    # Ingest distinctive evidence event
    distinctive_summary = "CassandraOutOfMemoryCrash node-03 heap dump generated"
    payload = {
        "source_type": "log",
        "event_type": "log.crash",
        "event_timestamp": datetime.now(UTC).isoformat(),
        "summary": distinctive_summary,
        "deduplication_key": "distinctive-heap-crash-99",
        "normalized_payload": {"cluster": "cassandra", "node": "node-03"},
    }
    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence", headers=headers, json=payload
    )
    assert resp.status_code == status.HTTP_201_CREATED
    ev_id = resp.json()["id"]

    # Verify timeline reflects the new event
    tl_resp = await client.get(
        f"/api/v1/incidents/{incident_id}/timeline", headers=headers
    )
    assert tl_resp.status_code == status.HTTP_200_OK
    tl_events = tl_resp.json()["events"]
    assert any(e["summary"] == distinctive_summary for e in tl_events)

    # Query hybrid retrieval engine directly for incident context
    retrieved = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=incident_id,
        query="Cassandra node heap crash",
        limit=10,
    )
    assert len(retrieved) > 0
    matched_ids = [r.event.id for r in retrieved]
    assert ev_id in matched_ids
    # Verify provenance
    top_match = next(r for r in retrieved if r.event.id == ev_id)
    assert top_match.source_type == "log"
    assert top_match.summary == distinctive_summary


@pytest.mark.asyncio
async def test_evidence_embedding_backfill_dry_run(
    test_user_and_org: dict, db_session: AsyncSession
):
    org: Organization = test_user_and_org["org"]
    stats = await EvidenceEmbeddingBackfillService.backfill(
        session=db_session,
        batch_size=20,
        organization_id=org.id,
        dry_run=True,
    )
    assert stats.dry_run is True
    assert stats.failed == 0
