"""TracePilot Milestone 6: Operational Readiness, Sandbox Validation & Audit Export Tests."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.models.evidence import EvidenceEvent, EvidenceSourceType
from app.models.incident import Incident, IncidentSeverity, IncidentStatus
from app.models.investigation import (
    HypothesisEvidenceLink,
    HypothesisStatus,
    InvestigationErrorCategory,
    InvestigationJob,
    InvestigationStatus,
    RootCauseHypothesis,
)
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.remediation import (
    ApprovalDecision,
    RemediationProposal,
    RemediationRiskLevel,
    RemediationStatus,
)
from app.models.user import User
from app.models.worker import WorkerHeartbeat
from app.services.auth.password import PasswordService
from app.services.health import HealthService
from app.services.investigations.service import InvestigationService
from app.services.remediation.sandbox import TracePilotSandboxSimulator
from app.services.remediation.service import RemediationService


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
async def setup_org_and_users(db_session: AsyncSession) -> dict[str, Any]:
    pwd = PasswordService.hash("StrongSecret123!")

    org = Organization(name="Pilot Org", slug="pilot-org")
    foreign_org = Organization(name="Foreign Org", slug="foreign-org")
    db_session.add_all([org, foreign_org])
    await db_session.flush()

    author_user = User(email="author@pilot.test", password_hash=pwd, full_name="Author Alice")
    admin_user = User(email="admin@pilot.test", password_hash=pwd, full_name="Admin Bob")
    member_user = User(email="member@pilot.test", password_hash=pwd, full_name="Member Charlie")
    foreign_user = User(email="intruder@foreign.test", password_hash=pwd, full_name="Foreign Dan")
    db_session.add_all([author_user, admin_user, member_user, foreign_user])
    await db_session.flush()

    mem_author = OrganizationMembership(
        organization_id=org.id, user_id=author_user.id, role=OrganizationRole.MEMBER
    )
    mem_admin = OrganizationMembership(
        organization_id=org.id, user_id=admin_user.id, role=OrganizationRole.ADMIN
    )
    mem_member = OrganizationMembership(
        organization_id=org.id, user_id=member_user.id, role=OrganizationRole.MEMBER
    )
    mem_foreign = OrganizationMembership(
        organization_id=foreign_org.id, user_id=foreign_user.id, role=OrganizationRole.ADMIN
    )
    db_session.add_all([mem_author, mem_admin, mem_member, mem_foreign])
    await db_session.commit()

    return {
        "org": org,
        "foreign_org": foreign_org,
        "author": author_user,
        "admin": admin_user,
        "member": member_user,
        "foreign_user": foreign_user,
    }


# =============================================================================
# Phase 1: Operational Health and Readiness Tests
# =============================================================================


@pytest.mark.asyncio
async def test_health_liveness_endpoints(client: AsyncClient) -> None:
    """Verify /health and /health/live return 200 without database overhead."""
    for path in ["/health", "/health/live", "/api/v1/health"]:
        res = await client.get(path)
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_health_readiness_healthy_and_degraded(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify readiness probes report dependencies and worker status boundedly."""
    # Record fresh worker heartbeat
    await HealthService.record_worker_heartbeat(
        session=db_session,
        worker_id="worker-test-alpha",
        status="active",
        metadata={"queue": "investigations"},
    )

    res = await client.get("/health/ready")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["status"] in ("ready", "degraded")
    assert "dependencies" in data
    assert data["dependencies"]["database"]["status"] == "ok"
    assert "worker" in data
    assert data["worker"]["status"] == "active"
    assert data["check_duration_ms"] is not None and data["check_duration_ms"] >= 0.0


@pytest.mark.asyncio
async def test_health_readiness_db_failure_returns_503(client: AsyncClient) -> None:
    """Verify readiness returns 503 Service Unavailable when DB is unreachable."""
    failing_db = AsyncMock(spec=AsyncSession)
    failing_db.execute.side_effect = Exception("Database connection timeout")
    app.dependency_overrides[get_db] = lambda: failing_db

    try:
        res = await client.get("/health/ready")
        assert res.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = res.json()
        assert data["status"] == "unhealthy"
        assert data["dependencies"]["database"]["status"] == "error"
    finally:
        app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_worker_status_endpoint(client: AsyncClient, db_session: AsyncSession) -> None:
    """Verify /health/worker returns worker status without secrets."""
    res = await client.get("/health/worker")
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["status"] in ("active", "idle", "stale")
    assert "last_heartbeat_at" in data


# =============================================================================
# Phase 3: Investigation Reliability and Worker Recovery Tests
# =============================================================================


@pytest.mark.asyncio
async def test_worker_reclaims_abandoned_job(
    db_session: AsyncSession, setup_org_and_users: dict[str, Any]
) -> None:
    """Verify abandoned running jobs older than stale threshold are safely re-queued."""
    org = setup_org_and_users["org"]
    job = InvestigationJob(
        organization_id=org.id,
        incident_id=f"inc-{uuid.uuid4().hex[:6]}",
        status=InvestigationStatus.RUNNING.value,
        stage="generating_hypotheses",
        progress=45,
        attempt_count=1,
        max_attempts=3,
        started_at=datetime.now(UTC) - timedelta(seconds=700),
    )
    db_session.add(job)
    await db_session.commit()

    requeued = await InvestigationService.requeue_stale_running(
        session=db_session,
        stale_seconds=600,
        organization_id=org.id,
    )
    assert requeued == 1

    await db_session.refresh(job)
    assert job.status == InvestigationStatus.QUEUED.value
    assert job.stage == "queued"
    assert job.progress == 0
    assert job.started_at is None


@pytest.mark.asyncio
async def test_worker_fails_job_when_retries_exhausted(
    db_session: AsyncSession, setup_org_and_users: dict[str, Any]
) -> None:
    """Verify stale jobs at max attempts transition to FAILED with safe error summary."""
    org = setup_org_and_users["org"]
    job = InvestigationJob(
        organization_id=org.id,
        incident_id=f"inc-{uuid.uuid4().hex[:6]}",
        status=InvestigationStatus.RUNNING.value,
        stage="synthesizing",
        progress=70,
        attempt_count=3,
        max_attempts=3,
        started_at=datetime.now(UTC) - timedelta(seconds=700),
    )
    db_session.add(job)
    await db_session.commit()

    requeued = await InvestigationService.requeue_stale_running(
        session=db_session,
        stale_seconds=600,
        organization_id=org.id,
    )
    assert requeued == 0

    await db_session.refresh(job)
    assert job.status == InvestigationStatus.FAILED.value
    assert job.error_category == InvestigationErrorCategory.INTERNAL_ERROR.value
    assert "retry budget exhausted" in job.error_summary


# =============================================================================
# Phase 4: Deterministic Sandbox Simulation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_sandbox_simulator_all_scenarios(client: AsyncClient, setup_org_and_users: dict[str, Any]) -> None:
    """Verify all 8 deterministic sandbox simulation scenarios execute locally and pass."""
    admin = setup_org_and_users["admin"]
    res = await client.get("/api/v1/remediations/sandbox/scenarios", headers=_headers(admin))
    assert res.status_code == status.HTTP_200_OK
    scenarios = res.json()
    assert len(scenarios) == 8

    # Run simulation via API
    sim_res = await client.post("/api/v1/remediations/sandbox/simulate", headers=_headers(admin))
    assert sim_res.status_code == status.HTTP_200_OK
    sim_data = sim_res.json()
    assert sim_data["all_passed"] is True
    assert sim_data["total_scenarios"] == 8
    assert sim_data["passed_scenarios"] == 8
    assert sim_data["is_simulation"] is True

    # Validate non-execution boundary
    for r in sim_data["results"]:
        assert r["execution_performed"] is False
        assert "observed_fixture_data" in r
        assert "simulated_conditions" in r
        assert "policy_validation_results" in r
        assert "disclaimer" in r


@pytest.mark.asyncio
async def test_sandbox_simulator_individual_scenarios() -> None:
    """Verify specific sandbox scenario expectations directly."""
    # Scenario 1: Healthy policy validation succeeds
    s1 = TracePilotSandboxSimulator.simulate_scenario("SCENARIO-HEALTHY-01")
    assert s1.passed is True
    assert s1.policy_validation_results["allowed"] is True

    # Scenario 4: Unauthorized reviewer is rejected
    s4 = TracePilotSandboxSimulator.simulate_scenario("SCENARIO-UNAUTHORIZED-REVIEWER-04")
    assert s4.passed is True
    assert s4.policy_validation_results["allowed"] is False

    # Scenario 5: Creator self-approval is blocked by separation of duties
    s5 = TracePilotSandboxSimulator.simulate_scenario("SCENARIO-CREATOR-SELF-APPROVAL-05")
    assert s5.passed is True
    assert s5.policy_validation_results["separation_of_duties_passed"] is False

    # Scenario 6: Expired proposal is rejected
    s6 = TracePilotSandboxSimulator.simulate_scenario("SCENARIO-EXPIRED-PROPOSAL-06")
    assert s6.passed is True
    assert s6.policy_validation_results["lifecycle_eligible"] is False

    # Scenario 7: Conflicting approval on already approved proposal
    s7 = TracePilotSandboxSimulator.simulate_scenario("SCENARIO-CONFLICTING-APPROVAL-07")
    assert s7.passed is True

    # Scenario 8: Investigation recovery safely re-queues
    s8 = TracePilotSandboxSimulator.simulate_scenario("SCENARIO-INVESTIGATION-RECOVERY-08")
    assert s8.passed is True
    assert s8.policy_validation_results["resulting_status"] == "queued"


# =============================================================================
# Phase 5 & 6: End-to-End Reliability, Audit Export & Isolation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_end_to_end_investigation_remediation_and_audit_export(
    client: AsyncClient, db_session: AsyncSession, setup_org_and_users: dict[str, Any]
) -> None:
    """Exercise full incident investigation, proposal, approval, audit export, and execution block."""
    org = setup_org_and_users["org"]
    author = setup_org_and_users["author"]
    admin = setup_org_and_users["admin"]
    member = setup_org_and_users["member"]
    foreign_user = setup_org_and_users["foreign_user"]

    # 1. Create Incident
    inc_res = await client.post(
        "/api/v1/incidents",
        headers=_headers(author),
        json={
            "title": "Payment Ingress Elevated 502 Errors",
            "description": "Upstream timeout spikes on payment gateway",
            "severity": IncidentSeverity.HIGH.value,
        },
    )
    assert inc_res.status_code == status.HTTP_201_CREATED
    inc_id = inc_res.json()["id"]

    # 2. Ingest Evidence
    ev_res = await client.post(
        f"/api/v1/incidents/{inc_id}/evidence",
        headers=_headers(author),
        json={
            "source_type": EvidenceSourceType.LOG.value,
            "event_type": "ingress_error_log",
            "event_timestamp": datetime.now(UTC).isoformat(),
            "summary": "connect() failed (111: Connection refused) while connecting to upstream redis",
            "normalized_payload": {"status_code": 502, "service": "payment-ingress"},
        },
    )
    assert ev_res.status_code == status.HTTP_201_CREATED
    ev_id = ev_res.json()["id"]

    # 3. Create Investigation Job and Root Cause Hypothesis linked to evidence
    job = InvestigationJob(
        incident_id=inc_id,
        organization_id=org.id,
        status=InvestigationStatus.COMPLETED.value,
        stage="completed",
        progress=100,
    )
    db_session.add(job)
    await db_session.flush()

    hyp = RootCauseHypothesis(
        investigation_job_id=job.id,
        incident_id=inc_id,
        organization_id=org.id,
        claim="Session Redis Connection Saturation",
        rationale="Redis cluster connection limit reached causing upstream 502s.",
        status=HypothesisStatus.SUPPORTED.value,
        groundedness_score=0.91,
        confidence="high",
        system_confidence="high",
    )
    db_session.add(hyp)
    await db_session.flush()

    link = HypothesisEvidenceLink(
        hypothesis_id=hyp.id,
        evidence_event_id=ev_id,
        organization_id=org.id,
        link_type="supports",
    )
    db_session.add(link)
    await db_session.commit()
    await db_session.refresh(hyp)

    # 4. Generate Remediation Proposal
    prop_res = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations/generate",
        headers=_headers(author),
        json={"hypothesis_id": hyp.id},
    )
    assert prop_res.status_code == status.HTTP_201_CREATED
    proposal = prop_res.json()
    prop_id = proposal["id"]
    assert proposal["is_executable"] is False
    assert proposal["status"] == RemediationStatus.PROPOSED.value

    # 5. Local Dry-Run Policy Evaluation
    dry_run_res = await client.post(
        f"/api/v1/remediations/{prop_id}/dry-run",
        headers=_headers(admin),
    )
    assert dry_run_res.status_code == status.HTTP_200_OK
    dry_run_data = dry_run_res.json()
    assert dry_run_data["dry_run_type"] == "local_policy_validation"
    assert dry_run_data["allowed"] is True
    assert dry_run_data["separation_of_duties_passed"] is True

    # 6. Verify Creator Self-Approval is Rejected (Separation of Duties)
    self_app_res = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(author),
        json={"rationale": "Self approval attempt"},
    )
    assert self_app_res.status_code in (
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_403_FORBIDDEN,
    )

    # 7. Complete Valid Approval by Authorized Admin
    app_res = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Validated against Redis metrics and runbook. Approved."},
    )
    assert app_res.status_code == status.HTTP_200_OK
    app_data = app_res.json()
    assert app_data["decision"] == ApprovalDecision.APPROVED.value
    assert app_data["reviewer_user_id"] == admin.id

    # 8. Verify Execution Endpoint Remains Forbidden (403)
    exec_res = await client.post(
        f"/api/v1/remediations/{prop_id}/execute",
        headers=_headers(admin),
    )
    assert exec_res.status_code == status.HTTP_403_FORBIDDEN
    assert "strictly forbidden" in exec_res.json()["error"]["message"]

    # 9. Verify Exportable Audit Report
    export_res = await client.get(
        f"/api/v1/remediations/{prop_id}/export",
        headers=_headers(admin),
    )
    assert export_res.status_code == status.HTTP_200_OK
    export_data = export_res.json()
    assert export_data["audit_export_version"] == "1.0.0"
    assert export_data["proposal_id"] == prop_id
    assert export_data["incident_id"] == inc_id
    assert export_data["organization_id"] == org.id
    assert export_data["execution_prohibited"] is True
    assert len(export_data["decisions"]) == 1
    assert export_data["decisions"][0]["decision"] == "approved"
    assert len(export_data["audit_events"]) >= 2
    assert ev_id in export_data["evidence_reference_ids"]
    assert export_data["groundedness_metadata"]["groundedness_score"] == 0.91

    # 10. Verify Cross-Tenant Isolation on Audit Export
    foreign_export_res = await client.get(
        f"/api/v1/remediations/{prop_id}/export",
        headers=_headers(foreign_user),
    )
    assert foreign_export_res.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# Phase 7: Configuration Hardening Tests
# =============================================================================


def test_production_mode_configuration_hardening() -> None:
    """Verify production mode rejects mock LLM, debug mode, and default JWT secret."""
    with pytest.raises(ValueError, match="DEFAULT_LLM_PROVIDER cannot be 'mock' in production"):
        Settings(
            APP_ENV="production",
            DEFAULT_LLM_PROVIDER="mock",
            DEBUG=False,
            JWT_SECRET_KEY="12345678901234567890123456789012",
            API_KEY_ENCRYPTION_KEY="12345678901234567890123456789012",
        )

    with pytest.raises(ValueError, match="DEBUG must be False in production"):
        Settings(
            APP_ENV="production",
            DEFAULT_LLM_PROVIDER="groq",
            DEBUG=True,
            JWT_SECRET_KEY="12345678901234567890123456789012",
            API_KEY_ENCRYPTION_KEY="12345678901234567890123456789012",
        )

    with pytest.raises(ValueError, match="JWT_SECRET_KEY must be overridden in production"):
        Settings(
            APP_ENV="production",
            DEFAULT_LLM_PROVIDER="groq",
            DEBUG=False,
            JWT_SECRET_KEY="change-this-secret-key-too-short",
            API_KEY_ENCRYPTION_KEY="12345678901234567890123456789012",
        )
