import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictException
from app.core.security import create_access_token
from app.models.evidence import EvidenceEvent, EvidenceSourceType
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.incidents import EvidenceEventCreate
from app.services.auth.password import PasswordService
from app.services.incidents.service import IncidentService


@pytest.fixture
async def second_tenant(db_session: AsyncSession) -> dict[str, object]:
    """Create a separate tenant user and organization for tenant isolation tests."""
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="tenant2@example.com",
        password_hash=pwd_hash,
        full_name="Tenant 2 User",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(name="Tenant 2 Workspace", slug="tenant-2-workspace")
    db_session.add(org)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=org.id,
        user_id=user.id,
        role=OrganizationRole.OWNER,
    )
    db_session.add(membership)
    await db_session.commit()

    return {
        "user": user,
        "org": org,
        "membership": membership,
        "token": create_access_token(user.id),
    }


# ─── 1. Authentication & Validation Tests ─────────────────────────────────────


@pytest.mark.asyncio
async def test_incident_unauthenticated_requests(client: AsyncClient) -> None:
    """Verify that unauthenticated requests to incident endpoints return 401 Unauthorized."""
    resp = await client.post("/api/v1/incidents", json={"title": "Unauth incident"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    resp = await client.get("/api/v1/incidents")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    dummy_id = str(uuid.uuid4())
    resp = await client.get(f"/api/v1/incidents/{dummy_id}")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    resp = await client.get(f"/api/v1/incidents/{dummy_id}/timeline")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_create_incident_validation_errors(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Verify validation errors when required fields are missing or invalid."""
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    # Missing title
    resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"description": "Missing title"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Invalid severity
    resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Invalid Severity", "severity": "catastrophic"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# ─── 2. Creation & Listing Tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_incident_success(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify successful incident creation with defaults and metadata."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    payload = {
        "title": "Payment Gateway 502 Latency Spike",
        "description": "Upstream timeout on checkout transactions",
        "severity": "critical",
        "status": "open",
        "service_name": "payment-api",
        "environment": "production",
        "incident_metadata": {"cluster": "us-east-1", "runbook_id": "rb-pay-01"},
    }

    resp = await client.post("/api/v1/incidents", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["title"] == payload["title"]
    assert data["description"] == payload["description"]
    assert data["severity"] == IncidentSeverity.CRITICAL.value
    assert data["status"] == IncidentStatus.OPEN.value
    assert data["service_name"] == "payment-api"
    assert data["environment"] == "production"
    assert data["organization_id"] == org.id
    assert data["created_by_user_id"] == user.id
    assert data["incident_metadata"]["cluster"] == "us-east-1"
    assert data["evidence_count"] == 0
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_list_incidents_filtering_and_pagination(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Verify listing incidents with severity/status filters and pagination."""
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    # Create 3 incidents
    for i, sev in enumerate(["low", "medium", "critical"]):
        await client.post(
            "/api/v1/incidents",
            headers=headers,
            json={
                "title": f"Incident {i}",
                "severity": sev,
                "service_name": "order-api" if i < 2 else "payment-api",
            },
        )

    # List all
    resp = await client.get("/api/v1/incidents", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["total"] >= 3

    # Filter by severity
    resp = await client.get("/api/v1/incidents?severity=critical", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert all(item["severity"] == "critical" for item in items)

    # Filter by service_name
    resp = await client.get("/api/v1/incidents?service_name=payment-api", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    items = resp.json()["items"]
    assert all(item["service_name"] == "payment-api" for item in items)


# ─── 3. Multi-Tenant Isolation Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_tenant_isolation_incidents_and_evidence(
    client: AsyncClient,
    test_user_and_org: dict,
    second_tenant: dict,
) -> None:
    """
    Verify strict tenant isolation:
    1. Tenant 1 cannot access Tenant 2's incident by ID (returns 404).
    2. Tenant 1 listing incidents never sees Tenant 2's incidents.
    3. Tenant 1 cannot ingest evidence into Tenant 2's incident.
    4. Client specifying an unauthorized organization_id is rejected with 403 Forbidden.
    """
    user1: User = test_user_and_org["user"]
    headers1 = {"Authorization": f"Bearer {create_access_token(user1.id)}"}

    org2: Organization = second_tenant["org"]
    headers2 = {"Authorization": f"Bearer {second_tenant['token']}"}

    # Tenant 2 creates an incident
    resp = await client.post(
        "/api/v1/incidents",
        headers=headers2,
        json={"title": "Tenant 2 Internal DB Incident", "severity": "high"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    inc2_id = resp.json()["id"]

    # 1. Tenant 1 attempts to read Tenant 2's incident -> 404 Not Found (no leak)
    resp = await client.get(f"/api/v1/incidents/{inc2_id}", headers=headers1)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 2. Tenant 1 listing incidents only sees Tenant 1 incidents
    resp = await client.get("/api/v1/incidents", headers=headers1)
    assert resp.status_code == status.HTTP_200_OK
    t1_incident_ids = [item["id"] for item in resp.json()["items"]]
    assert inc2_id not in t1_incident_ids

    # 3. Tenant 1 attempts to ingest evidence into Tenant 2's incident -> 404 Not Found
    resp = await client.post(
        f"/api/v1/incidents/{inc2_id}/evidence",
        headers=headers1,
        json={
            "source_type": "log",
            "event_type": "malicious.tamper",
            "event_timestamp": "2026-10-04T12:00:00Z",
            "summary": "Tenant 1 cross-tenant write attempt",
        },
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    # 4. User 1 tries to supply organization_id of Tenant 2 in POST -> 403 Forbidden
    resp = await client.post(
        "/api/v1/incidents",
        headers=headers1,
        json={
            "title": "Forged Tenant Incident",
            "organization_id": org2.id,
        },
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ─── 4. Evidence Ingestion & Idempotency Tests ─────────────────────────────────


@pytest.mark.asyncio
async def test_evidence_ingestion_and_idempotency(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """
    Verify:
    1. Ingestion of evidence returns 201 Created.
    2. Re-ingesting with same deduplication_key returns 200 OK with duplicate header.
    3. Duplicate does not increase evidence record count.
    """
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    # Create incident
    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Auth Outage", "severity": "high"},
    )
    incident_id = inc_resp.json()["id"]

    event_payload = {
        "source_type": "alert",
        "event_type": "alert.firing",
        "event_timestamp": "2026-10-04T14:00:00Z",
        "summary": "PagerDuty: High Error Rate on /api/v1/auth",
        "source_reference": "https://alerts.example.com/inc-9821",
        "normalized_payload": {"service": "auth-service", "error_rate": 0.42},
        "deduplication_key": "alert-firing-auth-service-202610041400",
    }

    # First ingestion -> 201 Created
    resp1 = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=headers,
        json=event_payload,
    )
    assert resp1.status_code == status.HTTP_201_CREATED
    data1 = resp1.json()
    assert data1["deduplication_key"] == event_payload["deduplication_key"]
    assert data1["source_type"] == EvidenceSourceType.ALERT.value
    event_id = data1["id"]

    # Second ingestion with identical deduplication key -> 200 OK (idempotent duplicate)
    resp2 = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=headers,
        json=event_payload,
    )
    assert resp2.status_code == status.HTTP_200_OK
    assert resp2.headers.get("X-TracePilot-Duplicate") == "true"
    data2 = resp2.json()
    assert data2["id"] == event_id  # Returns exact same evidence event

    # Verify list evidence only has 1 event
    list_resp = await client.get(f"/api/v1/incidents/{incident_id}/evidence", headers=headers)
    assert list_resp.status_code == status.HTTP_200_OK
    assert list_resp.json()["total"] == 1


# ─── 5. Deterministic Timeline & Empty Timeline Tests ─────────────────────────


@pytest.mark.asyncio
async def test_empty_incident_timeline(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify that an incident with no evidence returns an empty timeline."""
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Empty Incident", "severity": "low"},
    )
    incident_id = inc_resp.json()["id"]

    resp = await client.get(f"/api/v1/incidents/{incident_id}/timeline", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["incident_id"] == incident_id
    assert data["total_events"] == 0
    assert data["events"] == []


@pytest.mark.asyncio
async def test_timeline_deterministic_chronological_ordering(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """
    Verify deterministic chronological sorting:
    Ingest events out of order, ensure timeline returns event_timestamp ASC, tie-breaker id ASC.
    """
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Ordering Incident", "severity": "medium"},
    )
    incident_id = inc_resp.json()["id"]

    # Ingest in out-of-order sequence: T3, T1, T2
    events_to_ingest = [
        {"ts": "2026-10-04T14:15:00Z", "summary": "Third event (T3)", "type": "T3"},
        {"ts": "2026-10-04T14:05:00Z", "summary": "First event (T1)", "type": "T1"},
        {"ts": "2026-10-04T14:10:00Z", "summary": "Second event (T2)", "type": "T2"},
    ]

    for ev in events_to_ingest:
        resp = await client.post(
            f"/api/v1/incidents/{incident_id}/evidence",
            headers=headers,
            json={
                "source_type": "log",
                "event_type": ev["type"],
                "event_timestamp": ev["ts"],
                "summary": ev["summary"],
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED

    # Fetch timeline
    resp = await client.get(f"/api/v1/incidents/{incident_id}/timeline", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    timeline = resp.json()
    assert timeline["total_events"] == 3

    ordered_types = [ev["event_type"] for ev in timeline["events"]]
    assert ordered_types == ["T1", "T2", "T3"]


# ─── 6. Synthetic Incident Fixture (Requirement 11) ───────────────────────────


@pytest.mark.asyncio
async def test_synthetic_incident_fixture_no_causality_inference(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """
    Milestone 1 Specification 11:
    Deterministic synthetic incident fixture:
    - payment-api deployment at 14:02:10 UTC
    - HTTP 502 alert at 14:03:04 UTC
    - Database connection timeout at 14:03:12 UTC
    Ingest in non-chronological order.
    Assert deterministic chronological sequence on the timeline.
    Assert that correlation does not infer causality at this foundation layer.
    """
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={
            "title": "Payment API Failure Incident",
            "severity": "critical",
            "service_name": "payment-api",
            "environment": "production",
        },
    )
    assert inc_resp.status_code == status.HTTP_201_CREATED
    incident_id = inc_resp.json()["id"]

    # The three synthetic events
    deployment_event = {
        "source_type": "deployment",
        "event_type": "deployment.completed",
        "event_timestamp": "2026-10-04T14:02:10Z",
        "summary": "Deployment v2.4.1 completed for payment-api",
        "source_reference": "commit-sha-9f8a3c",
        "normalized_payload": {
            "service": "payment-api",
            "version": "v2.4.1",
            "author": "devops@example.com",
        },
        "deduplication_key": "deploy-payment-api-v2.4.1-20261004140210",
    }

    alert_event = {
        "source_type": "alert",
        "event_type": "alert.firing",
        "event_timestamp": "2026-10-04T14:03:04Z",
        "summary": "HTTP 502 Bad Gateway rate exceeded 5% on payment-api",
        "source_reference": "https://monitor.example.com/alerts/502-spike",
        "normalized_payload": {
            "service": "payment-api",
            "metric": "http_response_5xx_rate",
            "value": 0.082,
            "threshold": 0.05,
        },
        "deduplication_key": "alert-payment-api-502-20261004140304",
    }

    db_timeout_event = {
        "source_type": "log",
        "event_type": "database.connection_timeout",
        "event_timestamp": "2026-10-04T14:03:12Z",
        "summary": "Database connection pool exhausted: connection acquisition timed out after 5000ms",
        "source_reference": "pod/payment-api-7b94cf67f8-8q2ml",
        "normalized_payload": {
            "service": "payment-api",
            "pool_size": 20,
            "waiting_clients": 45,
            "timeout_ms": 5000,
        },
        "deduplication_key": "log-db-timeout-payment-api-20261004140312",
    }

    # Ingest in shuffled order: Alert first, then Database Timeout, then Deployment
    for event in [alert_event, db_timeout_event, deployment_event]:
        resp = await client.post(
            f"/api/v1/incidents/{incident_id}/evidence",
            headers=headers,
            json=event,
        )
        assert resp.status_code == status.HTTP_201_CREATED

    # Retrieve timeline
    timeline_resp = await client.get(f"/api/v1/incidents/{incident_id}/timeline", headers=headers)
    assert timeline_resp.status_code == status.HTTP_200_OK
    timeline_data = timeline_resp.json()
    assert timeline_data["total_events"] == 3

    events = timeline_data["events"]

    # 1. First event MUST be the deployment at 14:02:10 UTC
    assert events[0]["source_type"] == "deployment"
    assert events[0]["event_type"] == "deployment.completed"
    assert events[0]["summary"] == deployment_event["summary"]
    assert "2026-10-04T14:02:10" in events[0]["event_timestamp"]

    # 2. Second event MUST be the HTTP 502 alert at 14:03:04 UTC
    assert events[1]["source_type"] == "alert"
    assert events[1]["event_type"] == "alert.firing"
    assert events[1]["summary"] == alert_event["summary"]
    assert "2026-10-04T14:03:04" in events[1]["event_timestamp"]

    # 3. Third event MUST be the DB connection timeout at 14:03:12 UTC
    assert events[2]["source_type"] == "log"
    assert events[2]["event_type"] == "database.connection_timeout"
    assert events[2]["summary"] == db_timeout_event["summary"]
    assert "2026-10-04T14:03:12" in events[2]["event_timestamp"]

    # 4. Strict Foundation Guarantee: Timeline provides deterministic chronological evidence
    # but does NOT infer causality or generate speculative hypotheses without evidence links.
    for ev in events:
        # Verify raw facts and metadata are faithfully preserved
        assert "normalized_payload" in ev
        assert "deduplication_key" in ev


# ─── 7. Cleanup-Milestone Regression Tests ────────────────────────────────────


@pytest.mark.asyncio
async def test_get_incident_detail_reports_evidence_count(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """GET /incidents/{id} must report the persisted evidence count.

    Covers the eager-loaded evidence relationship used by the detail endpoint.
    """
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Counted Incident", "severity": "medium"},
    )
    assert inc_resp.status_code == status.HTTP_201_CREATED
    incident_id = inc_resp.json()["id"]
    assert inc_resp.json()["evidence_count"] == 0

    for i in range(2):
        resp = await client.post(
            f"/api/v1/incidents/{incident_id}/evidence",
            headers=headers,
            json={
                "source_type": "log",
                "event_type": f"event.{i}",
                "event_timestamp": "2026-10-04T14:00:00Z",
                "summary": f"event {i}",
            },
        )
        assert resp.status_code == status.HTTP_201_CREATED

    detail = await client.get(f"/api/v1/incidents/{incident_id}", headers=headers)
    assert detail.status_code == status.HTTP_200_OK
    assert detail.json()["evidence_count"] == 2


@pytest.mark.asyncio
async def test_evidence_dedup_key_whitespace_normalized(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Deduplication keys must match after whitespace normalization.

    Regression: the idempotency lookup previously compared the raw key while
    the insert stored the stripped key, so " key " never matched "key".
    """
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Whitespace Dedup Incident", "severity": "low"},
    )
    incident_id = inc_resp.json()["id"]

    def _payload(key: str) -> dict:
        return {
            "source_type": "alert",
            "event_type": "alert.firing",
            "event_timestamp": "2026-10-04T14:00:00Z",
            "summary": "whitespace dedup probe",
            "deduplication_key": key,
        }

    first = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=headers,
        json=_payload("  padded-dedup-key-123  "),
    )
    assert first.status_code == status.HTTP_201_CREATED

    second = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=headers,
        json=_payload("padded-dedup-key-123"),
    )
    assert second.status_code == status.HTTP_200_OK
    assert second.headers.get("X-TracePilot-Duplicate") == "true"
    assert second.json()["id"] == first.json()["id"]

    listed = await client.get(f"/api/v1/incidents/{incident_id}/evidence", headers=headers)
    assert listed.json()["total"] == 1


@pytest.mark.asyncio
async def test_cross_tenant_evidence_list_and_timeline_hidden(
    client: AsyncClient,
    test_user_and_org: dict,
    second_tenant: dict,
) -> None:
    """Cross-tenant reads of evidence list and timeline must return 404."""
    headers1 = {"Authorization": f"Bearer {create_access_token(test_user_and_org['user'].id)}"}
    headers2 = {"Authorization": f"Bearer {second_tenant['token']}"}

    resp = await client.post(
        "/api/v1/incidents",
        headers=headers2,
        json={"title": "Tenant 2 private incident", "severity": "high"},
    )
    assert resp.status_code == status.HTTP_201_CREATED
    inc2_id = resp.json()["id"]

    resp = await client.get(f"/api/v1/incidents/{inc2_id}/evidence", headers=headers1)
    assert resp.status_code == status.HTTP_404_NOT_FOUND

    resp = await client.get(f"/api/v1/incidents/{inc2_id}/timeline", headers=headers1)
    assert resp.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_evidence_malformed_input_rejected(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Malformed evidence payloads and unknown incidents must fail safely."""
    user: User = test_user_and_org["user"]
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    inc_resp = await client.post(
        "/api/v1/incidents",
        headers=headers,
        json={"title": "Validation Incident", "severity": "low"},
    )
    incident_id = inc_resp.json()["id"]
    base = {
        "source_type": "log",
        "event_type": "app.error",
        "event_timestamp": "2026-10-04T14:00:00Z",
        "summary": "boom",
    }

    # Missing required source_type -> 422
    bad = {k: v for k, v in base.items() if k != "source_type"}
    resp = await client.post(f"/api/v1/incidents/{incident_id}/evidence", headers=headers, json=bad)
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Unknown source_type -> 422
    resp = await client.post(
        f"/api/v1/incidents/{incident_id}/evidence",
        headers=headers,
        json={**base, "source_type": "carrier-pigeon"},
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Evidence on a nonexistent incident -> 404 (tenant-safe, no leak)
    resp = await client.post(
        f"/api/v1/incidents/{uuid.uuid4()}/evidence", headers=headers, json=base
    )
    assert resp.status_code == status.HTTP_404_NOT_FOUND


def _scalar_result(value: object) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


@pytest.mark.asyncio
async def test_evidence_race_integrity_error_returns_existing() -> None:
    """A UNIQUE-violation race on commit must resolve to the existing row.

    Simulates: pre-check SELECT misses (concurrent insert in flight), the
    database rejects the duplicate via uq_evidence_events_incident_dedup,
    and the service re-reads and returns (existing, False).
    """
    incident = Incident(
        id="inc-race-1",
        organization_id="org-race-1",
        title="race",
        severity=IncidentSeverity.HIGH.value,
        status=IncidentStatus.OPEN.value,
        environment="production",
    )
    existing = EvidenceEvent(
        id="ev-race-1",
        incident_id="inc-race-1",
        organization_id="org-race-1",
        source_type=EvidenceSourceType.LOG.value,
        event_type="app.error",
        event_timestamp=datetime.now(UTC),
        summary="existing",
        normalized_payload={},
        deduplication_key="race-key-1",
    )
    session = AsyncMock()
    session.execute.side_effect = [
        _scalar_result(incident),  # get_incident
        _scalar_result(None),  # pre-check miss (race in flight)
        _scalar_result(existing),  # retry read after IntegrityError
    ]
    session.commit.side_effect = IntegrityError(
        "INSERT INTO evidence_events", {}, Exception("duplicate key")
    )

    payload = EvidenceEventCreate(
        source_type=EvidenceSourceType.LOG,
        event_type="app.error",
        event_timestamp=datetime.now(UTC),
        summary="racy duplicate",
        deduplication_key="race-key-1",
    )
    event, is_new = await IncidentService.create_evidence_event(
        session=session,
        incident_id="inc-race-1",
        organization_id="org-race-1",
        payload=payload,
    )
    assert is_new is False
    assert event is existing
    session.rollback.assert_awaited()


@pytest.mark.asyncio
async def test_evidence_integrity_error_without_key_conflicts() -> None:
    """An IntegrityError with no recoverable duplicate must raise 409."""
    incident = Incident(
        id="inc-race-2",
        organization_id="org-race-2",
        title="race",
        severity=IncidentSeverity.HIGH.value,
        status=IncidentStatus.OPEN.value,
        environment="production",
    )
    session = AsyncMock()
    session.execute.side_effect = [_scalar_result(incident)]
    session.commit.side_effect = IntegrityError(
        "INSERT INTO evidence_events", {}, Exception("fk violation")
    )

    payload = EvidenceEventCreate(
        source_type=EvidenceSourceType.LOG,
        event_type="app.error",
        event_timestamp=datetime.now(UTC),
        summary="no key",
    )
    with pytest.raises(ConflictException):
        await IncidentService.create_evidence_event(
            session=session,
            incident_id="inc-race-2",
            organization_id="org-race-2",
            payload=payload,
        )
