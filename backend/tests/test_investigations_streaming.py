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
    monkeypatch,
):
    """Stream observes state transitions in DB and emits progress events."""
    from app.core.config import get_settings
    from app.services.investigations.service import InvestigationService

    # Fast polling for test determinism
    settings = get_settings()
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_POLL_INTERVAL", 0.05)
    monkeypatch.setattr(settings, "INVESTIGATION_SSE_HEARTBEAT_INTERVAL", 5.0)

    h = _auth_headers(test_user_and_org["user"])
    job = await _create_test_job(
        db_session,
        test_user_and_org["org"].id,
        status=InvestigationStatus.RUNNING,
        stage="retrieving_evidence",
        progress=15,
    )

    async def update_job_concurrently():
        await asyncio.sleep(0.08)
        # Advance to validating
        await InvestigationService.update_progress(db_session, job, "validating_citations", 75)
        await asyncio.sleep(0.08)
        # Complete job
        await InvestigationService.complete_job(
            db_session, job, {"observed_facts": ["Payment timeout confirmed"]}
        )

    # Launch DB updater task concurrently
    update_task = asyncio.create_task(update_job_concurrently())

    resp = await client.get(f"/api/v1/investigations/{job.id}/stream", headers=h)
    await update_task
    assert resp.status_code == 200

    events = parse_sse_events(resp.text)
    event_names = [e[0] for e in events]

    assert "investigation.connected" in event_names
    assert "investigation.snapshot" in event_names
    assert "investigation.progress" in event_names
    assert "investigation.completed" in event_names

    # Check progress update event
    prog_event = next(e[1] for e in events if e[0] == "investigation.progress")
    assert prog_event["stage"] == "validating_citations"
    assert prog_event["progress"] == 75

    # Check completion event
    comp_event = next(e[1] for e in events if e[0] == "investigation.completed")
    assert comp_event["status"] == "completed"
    assert comp_event["result_summary"] == {"observed_facts": ["Payment timeout confirmed"]}


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

    # Launch streaming request as an asyncio task, then cancel it to simulate client aborting/disconnecting
    req_task = asyncio.create_task(client.get(f"/api/v1/investigations/{job.id}/stream", headers=h))
    await asyncio.sleep(0.08)
    req_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await req_task

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
