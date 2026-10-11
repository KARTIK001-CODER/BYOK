"""TracePilot Stage E: End-to-End Hardening, Deployment Readiness & Operational Validation Suite.

Covers:
1. Workstream A: Full end-to-end incident-to-remediation lifecycle with real DB sessions.
2. Workstream B: Multi-tenant security boundary, direct ID substitution, separation of duties, and execution lock.
3. Workstream C: Operational liveness, readiness, worker heartbeat monitoring, and diagnostics.
"""

import json
from datetime import UTC, datetime
import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.investigation import InvestigationStatus
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService
from app.services.investigations.retrieval import InvestigationRetrievalService
from app.services.investigations.service import InvestigationService
from app.services.llm.factory import LLMProviderFactory
from app.services.llm.providers.mock import MockLLMProvider


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def use_mock_llm(monkeypatch):
    """Route the investigation engine to a deterministic Mock provider."""
    mock = MockLLMProvider()
    monkeypatch.setattr(
        LLMProviderFactory,
        "create",
        classmethod(lambda _cls, **_kwargs: (mock, "mock-test-model")),
    )
    return mock


@pytest.fixture
async def second_tenant(db_session: AsyncSession) -> dict:
    """Distinct organization and user to verify tenant isolation boundaries."""
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="stage-e-tenant2@example.com",
        password_hash=pwd_hash,
        full_name="Stage E Tenant 2",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(name="Stage E Tenant 2 Org", slug="stage-e-tenant-2-org")
    db_session.add(org)
    await db_session.flush()

    db_session.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
        )
    )
    await db_session.commit()
    return {"user": user, "org": org, "token": create_access_token(user.id)}


@pytest.mark.asyncio
async def test_stage_e_full_end_to_end_lifecycle(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession, use_mock_llm: MockLLMProvider
):
    """Exercise complete incident investigation and remediation workflow in isolated environment.

    Workflow:
    1. Incident creation with service & environment context
    2. Single evidence ingestion with deduplication key & duplicate check
    3. Batch evidence ingestion with partial outcomes (accepted, duplicate)
    4. Timeline and evidence API persistence check
    5. Retrieval freshness and citation provenance
    6. Investigation job creation and state transitions
    7. Remediation proposal creation with non-executable risk assessment
    8. Separation-of-duties enforcement & human approval decision
    9. Audit trail persistence and export report
    10. Absolute non-executable safety boundary (HTTP 403 Forbidden)
    """
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    h_creator = _headers(user)

    # Setup a distinct admin user in the same org for separation-of-duties review
    reviewer = User(
        email="sre-reviewer-stage-e@example.com",
        password_hash=PasswordService.hash("StrongPassword123!"),
        full_name="SRE Reviewer Stage E",
        is_active=True,
        is_verified=True,
    )
    db_session.add(reviewer)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=reviewer.id,
            role=OrganizationRole.ADMIN,
        )
    )
    await db_session.commit()
    h_reviewer = _headers(reviewer)

    # 1. Create Incident
    inc_payload = {
        "title": "Database Connection Pool Exhaustion",
        "severity": "critical",
        "service_name": "order-service",
        "environment": "production",
        "summary": "Elevated latency and connection timeouts to postgres pool",
    }
    resp = await client.post("/api/v1/incidents", headers=h_creator, json=inc_payload)
    assert resp.status_code == status.HTTP_201_CREATED
    incident_id = resp.json()["id"]
    assert resp.json()["service_name"] == "order-service"
    assert resp.json()["environment"] == "production"

    # 2. Ingest Single Operational Evidence Event
    ev1_payload = {
        "source_type": "metric",
        "event_type": "pool_saturation",
        "summary": "Postgres active connection count reached 100% capacity",
        "deduplication_key": f"e2e-metric-{incident_id}-001",
        "event_timestamp": datetime.now(UTC).isoformat(),
        "normalized_payload": {"active_connections": 100, "max_connections": 100},
    }
    resp_ev1 = await client.post(f"/api/v1/incidents/{incident_id}/evidence", headers=h_creator, json=ev1_payload)
    assert resp_ev1.status_code == status.HTTP_201_CREATED
    ev1_id = resp_ev1.json()["id"]

    # Re-submitting ev1 returns HTTP 200 with X-TracePilot-Duplicate header
    resp_ev1_dup = await client.post(f"/api/v1/incidents/{incident_id}/evidence", headers=h_creator, json=ev1_payload)
    assert resp_ev1_dup.status_code == status.HTTP_200_OK
    assert resp_ev1_dup.headers.get("X-TracePilot-Duplicate") == "true"
    assert resp_ev1_dup.json()["id"] == ev1_id

    # 3. Batch Evidence Ingestion with Partial Outcomes
    batch_payload = {
        "items": [
            # Item 0: Valid new log event
            {
                "source_type": "log",
                "event_type": "timeout_error",
                "summary": "ConnectionTimeout: connection pool exhausted after 30s",
                "deduplication_key": f"e2e-log-{incident_id}-002",
                "event_timestamp": datetime.now(UTC).isoformat(),
                "normalized_payload": {"error": "pool_timeout"},
            },
            # Item 1: Duplicate of ev1 (existing deduplication key)
            {
                "source_type": "metric",
                "event_type": "pool_saturation",
                "summary": "Postgres active connection count reached 100% capacity duplicate",
                "deduplication_key": f"e2e-metric-{incident_id}-001",
                "event_timestamp": datetime.now(UTC).isoformat(),
                "normalized_payload": {"active_connections": 100},
            },
            # Item 2: Valid new deployment event
            {
                "source_type": "deployment",
                "event_type": "deployment.rollout",
                "summary": "Rollout order-service revision v2.1.0",
                "deduplication_key": f"e2e-deploy-{incident_id}-003",
                "event_timestamp": datetime.now(UTC).isoformat(),
                "normalized_payload": {"revision": "v2.1.0"},
            },
        ]
    }
    resp_batch = await client.post(f"/api/v1/incidents/{incident_id}/evidence/batch", headers=h_creator, json=batch_payload)
    assert resp_batch.status_code == status.HTTP_200_OK
    batch_data = resp_batch.json()
    assert batch_data["total_submitted"] == 3
    assert batch_data["accepted_count"] == 2
    assert batch_data["duplicate_count"] == 1
    assert batch_data["results"][0]["status"] == "accepted"
    assert batch_data["results"][1]["status"] == "duplicate"
    assert batch_data["results"][2]["status"] == "accepted"

    # 4. Verify Evidence & Timeline API Persistence
    resp_list = await client.get(f"/api/v1/incidents/{incident_id}/evidence", headers=h_creator)
    assert resp_list.status_code == status.HTTP_200_OK
    persisted_evidence = resp_list.json()["items"]
    assert len(persisted_evidence) == 3  # ev1 + batch item 0 + batch item 2

    resp_timeline = await client.get(f"/api/v1/incidents/{incident_id}/timeline", headers=h_creator)
    assert resp_timeline.status_code == status.HTTP_200_OK
    timeline_events = resp_timeline.json()["events"]
    assert len(timeline_events) == 3

    # 5. Hybrid Retrieval Freshness & Citation Identity
    retrieval_res = await InvestigationRetrievalService.retrieve_evidence(
        session=db_session,
        organization_id=org.id,
        incident_id=incident_id,
        query="connection pool exhausted timeout",
        limit=10,
    )
    assert len(retrieval_res) > 0
    matched_ids = [r.event.id for r in retrieval_res]
    assert any(eid in matched_ids for eid in [e["id"] for e in persisted_evidence])

    # 6. Start Investigation Job & Verify Execution Outcome
    valid_ev_ids = [e["id"] for e in persisted_evidence]
    use_mock_llm._custom_responder = lambda _req: json.dumps(
        {
            "hypotheses": [
                {
                    "claim": "Postgres connection pool saturation caused client connection timeouts.",
                    "rationale": "Saturation metric preceded timeout errors.",
                    "confidence": "high",
                    "confidence_score": 0.85,
                    "supporting_evidence_ids": [valid_ev_ids[0]],
                    "contradicting_evidence_ids": [],
                }
            ],
            "observed_facts": ["Postgres connection pool saturation detected at 100% capacity"],
            "uncertainty_notes": ["No metrics prior to saturation event."],
            "recommended_next_steps": [
                {
                    "action": "Increase DB connection pool size limit.",
                    "requires_human_approval": True,
                    "rationale": "Alleviate pool exhaustion.",
                }
            ],
        }
    )

    job_payload = {
        "provider": "mock",
        "model": "mock-sre",
    }
    resp_job = await client.post(f"/api/v1/incidents/{incident_id}/investigations", headers=h_creator, json=job_payload)
    assert resp_job.status_code == status.HTTP_201_CREATED
    job_data = resp_job.json()
    job_id = job_data["id"]
    assert job_data["status"] == "completed"

    resp_job_status = await client.get(f"/api/v1/investigations/{job_id}", headers=h_creator)
    assert resp_job_status.status_code == status.HTTP_200_OK
    assert resp_job_status.json()["status"] == "completed"

    # Verify hypotheses persisted
    resp_hyps = await client.get(f"/api/v1/investigations/{job_id}/hypotheses", headers=h_creator)
    assert resp_hyps.status_code == status.HTTP_200_OK
    hyps_data = resp_hyps.json()
    assert hyps_data["total"] >= 1
    assert hyps_data["items"][0]["status"] == "supported"

    # 7. Remediation Proposals & Risk Assessment
    prop_payload = {
        "title": "Scale Database Connection Pool Size",
        "description": "Increase max connection pool limit from 100 to 200 to relieve exhaustion.",
        "actions": [
            {
                "step_number": 1,
                "action_type": "config_change",
                "description": "Update pool size from 100 to 200",
                "target_system": "order-service",
                "command": "export DB_POOL_SIZE=200",
                "parameters": {"DB_POOL_SIZE": "200"},
                "risk_level": "medium",
                "reversible": True,
                "requires_human_approval": True,
                "is_executable": False,
            }
        ],
        "rollback_plan": "Revert pool config to 100.",
        "estimated_impact": "Recovers database connectivity within 2 minutes.",
        "is_executable": False,
    }
    resp_prop = await client.post(f"/api/v1/incidents/{incident_id}/remediations", headers=h_creator, json=prop_payload)
    assert resp_prop.status_code == status.HTTP_201_CREATED
    prop_data = resp_prop.json()
    proposal_id = prop_data["id"]
    assert prop_data["status"] == "proposed"
    assert prop_data["is_executable"] is False
    assert prop_data["risk_assessment"]["execution_restricted"] is True

    # 8. Separation of Duties Enforcement & Human Approval
    # Creator attempting self-approval -> strictly forbidden (403)
    resp_self_appr = await client.post(
        f"/api/v1/remediations/{proposal_id}/approve",
        headers=h_creator,
        json={"rationale": "Creator approving self proposal"},
    )
    assert resp_self_appr.status_code == status.HTTP_403_FORBIDDEN
    assert "Separation of duties violation" in resp_self_appr.json()["error"]["message"]

    # Authorized independent reviewer approves
    approval_payload = {
        "rationale": "Verified pool capacity metrics and team lead sign-off.",
    }
    resp_appr = await client.post(
        f"/api/v1/remediations/{proposal_id}/approve",
        headers=h_reviewer,
        json=approval_payload,
    )
    assert resp_appr.status_code == status.HTTP_200_OK
    assert resp_appr.json()["decision"] == "approved"

    # Verify status transitioned to approved
    resp_prop_check = await client.get(f"/api/v1/remediations/{proposal_id}", headers=h_creator)
    assert resp_prop_check.status_code == status.HTTP_200_OK
    assert resp_prop_check.json()["status"] == "approved"

    # 9. Audit Trail & Export Verification
    resp_audit = await client.get(f"/api/v1/remediations/{proposal_id}/audit", headers=h_creator)
    assert resp_audit.status_code == status.HTTP_200_OK
    audit_data = resp_audit.json()
    assert audit_data["total"] >= 2  # created and approved events
    assert any(e["event_type"] == "proposal_approved" for e in audit_data["items"])
    assert any(e["to_status"] == "approved" for e in audit_data["items"])

    resp_export = await client.get(f"/api/v1/remediations/{proposal_id}/export", headers=h_creator)
    assert resp_export.status_code == status.HTTP_200_OK
    export_json = resp_export.json()
    assert export_json["proposal_id"] == proposal_id
    assert export_json["status"] == "approved"
    assert export_json["execution_prohibited"] is True

    # 10. Strict Non-Executable Safety Boundary (HTTP 403 Forbidden)
    resp_exec = await client.post(f"/api/v1/remediations/{proposal_id}/execute", headers=h_reviewer)
    assert resp_exec.status_code == status.HTTP_403_FORBIDDEN
    err_msg = resp_exec.json().get("error", {}).get("message", "") or resp_exec.json().get("detail", "")
    assert "forbidden" in err_msg.lower() or "disabled" in err_msg.lower()


@pytest.mark.asyncio
async def test_stage_e_security_and_tenant_isolation_matrix(
    client: AsyncClient, test_user_and_org: dict, second_tenant: dict
):
    """Verify strict tenant isolation across all primary operational endpoints."""
    user1: User = test_user_and_org["user"]
    user2: User = second_tenant["user"]
    h1 = _headers(user1)
    h2 = _headers(user2)

    # Tenant 1 creates an incident
    resp1 = await client.post(
        "/api/v1/incidents",
        headers=h1,
        json={"title": "Private Tenant 1 Incident", "severity": "high", "service_name": "internal-api"},
    )
    assert resp1.status_code == status.HTTP_201_CREATED
    inc1_id = resp1.json()["id"]

    # Tenant 2 cannot access Tenant 1 incident
    resp_cross_get = await client.get(f"/api/v1/incidents/{inc1_id}", headers=h2)
    assert resp_cross_get.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 cannot ingest evidence to Tenant 1 incident
    resp_cross_ingest = await client.post(
        f"/api/v1/incidents/{inc1_id}/evidence",
        headers=h2,
        json={
            "source_type": "log",
            "event_type": "intrusion",
            "summary": "Should be blocked",
            "deduplication_key": "cross-tenant-ev-01",
            "event_timestamp": datetime.now(UTC).isoformat(),
        },
    )
    assert resp_cross_ingest.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 cannot batch ingest evidence to Tenant 1 incident
    resp_cross_batch = await client.post(
        f"/api/v1/incidents/{inc1_id}/evidence/batch",
        headers=h2,
        json={
            "items": [
                {
                    "source_type": "log",
                    "event_type": "log.error",
                    "event_timestamp": datetime.now(UTC).isoformat(),
                    "summary": "Cross-tenant intrusion attempt",
                }
            ]
        },
    )
    assert resp_cross_batch.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 cannot trigger investigations on Tenant 1 incident
    resp_cross_inv = await client.post(
        f"/api/v1/incidents/{inc1_id}/investigations",
        headers=h2,
        json={"provider": "mock"},
    )
    assert resp_cross_inv.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 1 creates remediation proposal
    resp_prop = await client.post(
        f"/api/v1/incidents/{inc1_id}/remediations",
        headers=h1,
        json={
            "title": "Tenant 1 Action",
            "description": "Private action mitigation proposal",
            "actions": [],
        },
    )
    assert resp_prop.status_code == status.HTTP_201_CREATED
    prop1_id = resp_prop.json()["id"]

    # Tenant 2 cannot view Tenant 1 remediation proposal
    resp_cross_prop = await client.get(f"/api/v1/remediations/{prop1_id}", headers=h2)
    assert resp_cross_prop.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 cannot review or approve Tenant 1 proposal
    resp_cross_appr = await client.post(
        f"/api/v1/remediations/{prop1_id}/approve",
        headers=h2,
        json={"rationale": "Unauthorized cross-tenant attempt"},
    )
    assert resp_cross_appr.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 cannot access audit trail or audit export for Tenant 1 proposal
    resp_cross_audit = await client.get(f"/api/v1/remediations/{prop1_id}/audit", headers=h2)
    assert resp_cross_audit.status_code == status.HTTP_404_NOT_FOUND

    resp_cross_export = await client.get(f"/api/v1/remediations/{prop1_id}/export", headers=h2)
    assert resp_cross_export.status_code == status.HTTP_404_NOT_FOUND

    # Unauthenticated requests are rejected
    assert (await client.get(f"/api/v1/incidents/{inc1_id}")).status_code == status.HTTP_401_UNAUTHORIZED
    assert (await client.post(f"/api/v1/incidents/{inc1_id}/evidence", json={})).status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_stage_e_operational_health_and_readiness(client: AsyncClient):
    """Verify liveness, readiness, and worker health endpoints."""
    # Liveness probes
    r_live = await client.get("/health")
    assert r_live.status_code == status.HTTP_200_OK
    assert r_live.json() == {"status": "ok"}

    r_live_k8s = await client.get("/health/live")
    assert r_live_k8s.status_code == status.HTTP_200_OK

    # Readiness probe
    r_ready = await client.get("/ready")
    assert r_ready.status_code == status.HTTP_200_OK
    ready_data = r_ready.json()
    assert ready_data["status"] == "ready"
    assert "dependencies" in ready_data

    r_ready_alias = await client.get("/health/ready")
    assert r_ready_alias.status_code == status.HTTP_200_OK

    # Worker health endpoint
    r_worker = await client.get("/api/v1/health/worker")
    assert r_worker.status_code == status.HTTP_200_OK
    worker_data = r_worker.json()
    assert "status" in worker_data
    assert "active_jobs_count" in worker_data
    assert "stale_jobs_count" in worker_data

    # System info endpoint
    r_info = await client.get("/api/v1/info")
    assert r_info.status_code == status.HTTP_200_OK
    info_data = r_info.json()
    assert info_data["app_name"] in ("TracePilot", "TracePilot-Test")
    assert "features" in info_data
    assert info_data["features"]["remediation_execution_enabled"] is False
