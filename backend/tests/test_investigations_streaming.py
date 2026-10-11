"""Tests for Milestone 3B: Real-time Server-Sent Events (SSE) investigation streaming."""

import asyncio
import json
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.incident import Incident
from app.models.investigation import (
    InvestigationErrorCategory,
    InvestigationJob,
    InvestigationStatus,
)
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService


@pytest.fixture
async def other_tenant_user_and_org(db_session: AsyncSession) -> dict:
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="sse-other-tenant@example.com",
        password_hash=pwd_hash,
        full_name="SSE Other Tenant",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(name="Other Tenant Org", slug="other-tenant-org")
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
    )
    await db_session.commit()
    return {"user": user, "org": org, "token": create_access_token(user.id)}


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


async def _create_test_job(
    db_session: AsyncSession,
    org_id: str,
    status: InvestigationStatus = InvestigationStatus.QUEUED,
    stage: str = "queued",
    progress: int = 0,
    result_summary: dict | None = None,
    error_category: str = InvestigationErrorCategory.NONE.value,
    error_summary: str | None = None,
) -> InvestigationJob:
    incident = Incident(
        organization_id=org_id,
        title="Payment Service Degradation",
        severity="high",
        service_name="payment-api",
    )
    db_session.add(incident)
    await db_session.flush()

    job = InvestigationJob(
        incident_id=incident.id,
        organization_id=org_id,
        status=status.value,
        stage=stage,
        progress=progress,
        attempt_count=1,
        max_attempts=3,
        error_category=error_category,
        error_summary=error_summary,
        result_summary=result_summary,
        requested_at=datetime.now(UTC),
    )
    if status == InvestigationStatus.COMPLETED:
        job.completed_at = datetime.now(UTC)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)
    return job


def parse_sse_events(raw_text: str) -> list[tuple[str, dict | str]]:
    """Parse raw SSE stream text into (event_type, data) pairs."""
    blocks = raw_text.strip().split("\n\n")
    events = []
    for block in blocks:
        if not block.strip():
            continue
        event_name = "message"
        data_str = ""
        is_heartbeat = False
        for line in block.split("\n"):
            line = line.strip()
            if line.startswith(":"):
                if "heartbeat" in line:
                    is_heartbeat = True
                continue
            if line.startswith("event:"):
                event_name = line.replace("event:", "").strip()
            elif line.startswith("data:"):
                part = line.replace("data:", "").strip()
                data_str = f"{data_str}\n{part}" if data_str else part

        if is_heartbeat:
            events.append(("heartbeat", {}))
        elif data_str:
            try:
                events.append((event_name, json.loads(data_str)))
            except Exception:
                events.append((event_name, data_str))
    return events


# ─── 1. Authentication & Tenant Authorization Tests ─────────────────────────


@pytest.mark.asyncio
async def test_stream_unauthenticated_rejected(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
):
    """Unauthenticated GET /investigations/{id}/stream must return 401."""
    job = await _create_test_job(db_session, test_user_and_org["org"].id)
    resp = await client.get(f"/api/v1/investigations/{job.id}/stream")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_stream_cross_tenant_returns_404_no_leak(
    client: AsyncClient,
    test_user_and_org: dict,
    other_tenant_user_and_org: dict,
    db_session: AsyncSession,
):
    """Organization B querying Organization A's job must return 404 without leaking state."""
    job = await _create_test_job(db_session, test_user_and_org["org"].id)
    h_other = {"Authorization": f"Bearer {other_tenant_user_and_org['token']}"}

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h_other)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stream_nonexistent_job_returns_404(
    client: AsyncClient,
    test_user_and_org: dict,
):
    """Non-existent job ID returns 404."""
    h = _auth_headers(test_user_and_org["user"])
    resp = await client.get(
        "/api/v1/investigations/00000000-0000-0000-0000-000000000000/stream", headers=h
    )
    assert resp.status_code == 404


# ─── 2. Initial Snapshot & Terminal States ──────────────────────────────────


@pytest.mark.asyncio
async def test_stream_terminal_completed_closes_cleanly(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
):
    """Connecting to an already-completed job emits snapshot + completed and closes."""
    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.COMPLETED,
        stage="completed",
        progress=100,
        result_summary={"hypotheses": [{"claim": "DB deadlock"}]},
    )

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    events = parse_sse_events(resp.text)
    event_names = [e[0] for e in events]

    assert "investigation.connected" in event_names
    assert "investigation.snapshot" in event_names
    assert "investigation.completed" in event_names

    # Check payload contents
    completed_event = next(e[1] for e in events if e[0] == "investigation.completed")
    assert completed_event["job_id"] == job.id
    assert completed_event["status"] == "completed"
    assert completed_event["progress"] == 100
    assert completed_event["result_summary"] == {"hypotheses": [{"claim": "DB deadlock"}]}


@pytest.mark.asyncio
async def test_stream_terminal_failed_closes_cleanly(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
):
    """Connecting to a failed job emits snapshot + failed and closes."""
    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.FAILED,
        stage="failed",
        progress=55,
        error_category=InvestigationErrorCategory.PROVIDER_TIMEOUT.value,
        error_summary="Provider request timed out after 60s.",
    )

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    assert resp.status_code == 200

    events = parse_sse_events(resp.text)
    event_names = [e[0] for e in events]

    assert "investigation.connected" in event_names
    assert "investigation.snapshot" in event_names
    assert "investigation.failed" in event_names

    failed_event = next(e[1] for e in events if e[0] == "investigation.failed")
    assert failed_event["job_id"] == job.id
    assert failed_event["status"] == "failed"
    assert failed_event["error_category"] == "provider_timeout"
    assert failed_event["error_summary"] == "Provider request timed out after 60s."


@pytest.mark.asyncio
async def test_stream_terminal_cancelled_closes_cleanly(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
):
    """Connecting to a cancelled job emits snapshot + cancelled and closes."""
    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.CANCELLED,
        stage="cancelled",
        progress=0,
    )

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    assert resp.status_code == 200

    events = parse_sse_events(resp.text)
    event_names = [e[0] for e in events]

    assert "investigation.connected" in event_names
    assert "investigation.snapshot" in event_names
    assert "investigation.cancelled" in event_names


# ─── 3. State Transitions & Live Progress Streaming ─────────────────────────


@pytest.mark.asyncio
async def test_stream_emits_progress_and_completion_transitions(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
    db_engine,
):
    """Stream observes state transitions in DB and emits progress events deterministically."""
    from app.services.investigations.service import InvestigationService
    from app.services.investigations.streaming import stream_investigation_events
    from unittest.mock import AsyncMock, MagicMock
    from sqlalchemy.ext.asyncio import async_sessionmaker

    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.RUNNING,
        stage="retrieving_evidence",
        progress=15,
    )

    session_maker = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    mock_req = MagicMock()
    mock_req.is_disconnected = AsyncMock(return_value=False)

    gen = stream_investigation_events(
        request=mock_req,
        job_id=job.id,
        organization_id=test_user_and_org["org"].id,
        session_factory=session_maker,
        poll_interval=0.001,
        heartbeat_interval=10.0,
        timeout_seconds=5.0,
    )

    # 1. Connected
    raw_connected = await anext(gen)
    events_conn = parse_sse_events(raw_connected)
    assert events_conn[0][0] == "investigation.connected"

    # 2. Initial Snapshot
    raw_snapshot = await anext(gen)
    events_snap = parse_sse_events(raw_snapshot)
    assert events_snap[0][0] == "investigation.snapshot"

    # 3. Step DB to progress transition
    async with session_maker() as s1:
        j1 = await InvestigationService.get_job(s1, job.id, test_user_and_org["org"].id)
        await InvestigationService.update_progress(s1, j1, "validating_citations", 75)

    raw_prog = await anext(gen)
    events_prog = parse_sse_events(raw_prog)
    assert events_prog[0][0] == "investigation.progress"
    assert events_prog[0][1]["stage"] == "validating_citations"
    assert events_prog[0][1]["progress"] == 75

    # 4. Step DB to completion transition
    async with session_maker() as s2:
        j2 = await InvestigationService.get_job(s2, job.id, test_user_and_org["org"].id)
        await InvestigationService.complete_job(
            s2, j2, {"observed_facts": ["Payment timeout confirmed"]}
        )

    raw_comp = await anext(gen)
    events_comp = parse_sse_events(raw_comp)
    assert events_comp[0][0] == "investigation.completed"
    assert events_comp[0][1]["status"] == "completed"
    assert events_comp[0][1]["result_summary"] == {"observed_facts": ["Payment timeout confirmed"]}

    # 5. Generator closes cleanly on terminal state
    with pytest.raises(StopAsyncIteration):
        await anext(gen)


@pytest.mark.asyncio
async def test_stream_no_duplicate_events_when_state_unchanged(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
    monkeypatch,
):
    """When job state does not change, progress events must not be duplicated endlessly."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_HEARTBEAT_INTERVAL", 5.0)
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_TIMEOUT_SECONDS", 0.25)

    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.RUNNING,
        stage="generating_hypotheses",
        progress=55,
    )

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    assert resp.status_code == 200

    events = parse_sse_events(resp.text)
    # Since state did not change during streaming, only connected & snapshot should be emitted
    progress_events = [e for e in events if e[0] == "investigation.progress"]
    assert len(progress_events) == 0


@pytest.mark.asyncio
async def test_stream_emits_heartbeat_periodically(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
    monkeypatch,
):
    """Heartbeat comments (: heartbeat) are emitted to prevent connection idle termination."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_POLL_INTERVAL", 0.03)
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_HEARTBEAT_INTERVAL", 0.08)
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_TIMEOUT_SECONDS", 0.25)

    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.RUNNING,
        stage="retrieving_evidence",
        progress=15,
    )

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    assert resp.status_code == 200

    events = parse_sse_events(resp.text)
    heartbeats = [e for e in events if e[0] == "heartbeat"]
    assert len(heartbeats) >= 1


@pytest.mark.asyncio
async def test_disconnect_does_not_mutate_or_fail_job(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
):
    """Client disconnect must not fail, cancel, or modify the investigation job."""
    from app.services.investigations.service import InvestigationService

    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.RUNNING,
        stage="generating_hypotheses",
        progress=55,
    )

    from unittest.mock import MagicMock
    from app.services.investigations.streaming import stream_investigation_events

    mock_request = MagicMock()
    disconnect_counter = 0

    async def mock_is_disconnected():
        nonlocal disconnect_counter
        disconnect_counter += 1
        return disconnect_counter > 1

    mock_request.is_disconnected = mock_is_disconnected

    class MockSessionFactory:
        def __call__(self):
            class SessionCtx:
                async def __aenter__(self):
                    return db_session
                async def __aexit__(self, exc_type, exc_val, exc_tb):
                    pass
            return SessionCtx()

    events = [
        e async for e in stream_investigation_events(
            request=mock_request,
            job_id=job.id,
            organization_id=test_user_and_org["org"].id,
            session_factory=MockSessionFactory(),
            poll_interval=0.01,
            heartbeat_interval=1.0,
            timeout_seconds=5.0,
        )
    ]
    assert len(events) >= 2

    # Verify job state in database is completely intact and still running
    await db_session.refresh(job)
    current = await InvestigationService.get_job(db_session, job.id, test_user_and_org["org"].id)
    assert current is not None
    assert current.status == InvestigationStatus.RUNNING.value
    assert current.stage == "generating_hypotheses"
    assert current.progress == 55


@pytest.mark.asyncio
async def test_reconnect_recovers_authoritative_state(
    client: AsyncClient,
    test_user_and_org: dict,
    db_session: AsyncSession,
    monkeypatch,
):
    """A newly connecting/reconnecting client immediately receives authoritative DB state."""
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_TIMEOUT_SECONDS", 0.15)

    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.RUNNING,
        stage="validating_citations",
        progress=75,
    )

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    assert resp.status_code == 200

    events = parse_sse_events(resp.text)
    snapshot = next(e[1] for e in events if e[0] == "investigation.snapshot")

    assert snapshot["job_id"] == job.id
    assert snapshot["status"] == "running"
    assert snapshot["stage"] == "validating_citations"
    assert snapshot["progress"] == 75
