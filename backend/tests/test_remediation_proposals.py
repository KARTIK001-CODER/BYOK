"""TracePilot Milestone 5A tests: remediation proposals, risk assessment, lifecycle, safety."""


import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.investigation import (
    GroundednessStatus,
    HypothesisConfidence,
    HypothesisStatus,
    InvestigationJob,
    InvestigationStatus,
    RootCauseHypothesis,
    SystemConfidenceLevel,
)
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.remediation import (
    RemediationActionType,
    RemediationRiskLevel,
)
from app.models.user import User
from app.services.auth.password import PasswordService
from app.services.remediation.risk import RiskEvaluator


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
async def tenant2(db_session: AsyncSession) -> dict:
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="m5-tenant2@example.com",
        password_hash=pwd_hash,
        full_name="M5 Tenant 2",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    org = Organization(name="M5 Tenant 2 Org", slug="m5-tenant-2-org")
    db_session.add(org)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER)
    )
    await db_session.commit()
    return {"user": user, "org": org, "token": create_access_token(user.id)}


async def _make_incident(client: AsyncClient, headers: dict) -> str:
    payload = {
        "title": "Payment Gateway Timeout Surge",
        "severity": "critical",
        "service_name": "payment-api",
        "environment": "production",
    }
    resp = await client.post("/api/v1/incidents", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_create_manual_remediation_proposal(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    payload = {
        "title": "Expand Connection Pool and Cycle Workers",
        "description": "Increase pool headroom and recycle connection leaks.",
        "actions": [
            {
                "step_number": 1,
                "action_type": "config_change",
                "description": "Update pool size from 10 to 50",
                "target_system": "Database Pool",
                "command": "ALTER SYSTEM SET max_connections = 150;",
                "parameters": {"max_connections": 150},
                "risk_level": "medium",
                "reversible": True,
                "requires_human_approval": True,
                "is_executable": False,
            },
            {
                "step_number": 2,
                "action_type": "service_restart",
                "description": "Rolling restart of api servers",
                "target_system": "API Pods",
                "command": "kubectl rollout restart deployment/api",
                "parameters": {},
                "risk_level": "medium",
                "reversible": True,
                "requires_human_approval": True,
                "is_executable": False,
            },
        ],
        "rollback_plan": "Revert pool config and restart pods.",
        "estimated_impact": "Recovers database connectivity within 2 minutes.",
        "is_executable": False,
    }

    resp = await client.post(f"/api/v1/incidents/{inc_id}/remediations", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()

    assert data["incident_id"] == inc_id
    assert data["status"] == "proposed"
    assert data["is_executable"] is False
    assert len(data["actions"]) == 2
    assert data["actions"][0]["is_executable"] is False
    assert data["actions"][0]["requires_human_approval"] is True
    assert data["risk_assessment"]["execution_restricted"] is True
    assert "risk_factors" in data["risk_assessment"]


@pytest.mark.asyncio
async def test_non_executable_restriction_enforcement(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    # 1. Attempting to mark proposal as executable is rejected by schema validator
    payload = {
        "title": "Unsafe automated execution attempt",
        "description": "Should be rejected.",
        "actions": [
            {
                "step_number": 1,
                "action_type": "service_restart",
                "description": "Restart",
                "target_system": "API",
                "is_executable": True,
            }
        ],
        "is_executable": True,
    }
    resp = await client.post(f"/api/v1/incidents/{inc_id}/remediations", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # 2. Creating normal proposal, then calling /execute endpoint is strictly forbidden
    valid_payload = {
        "title": "Advisory proposal",
        "description": "Safe advisory plan.",
        "actions": [],
        "is_executable": False,
    }
    create_resp = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations", headers=headers, json=valid_payload
    )
    assert create_resp.status_code == status.HTTP_201_CREATED
    proposal_id = create_resp.json()["id"]

    exec_resp = await client.post(f"/api/v1/remediations/{proposal_id}/execute", headers=headers)
    assert exec_resp.status_code == status.HTTP_403_FORBIDDEN
    assert "strictly forbidden" in exec_resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_generate_proposal_from_hypothesis(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    # Seed job and hypothesis
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
        claim="Postgres connection pool exhaustion caused cascading 504 gateway timeouts.",
        rationale="Evidence shows connection count exceeded max_connections limit.",
        confidence=HypothesisConfidence.HIGH.value,
        confidence_score=0.92,
        status=HypothesisStatus.SUPPORTED.value,
        groundedness_score=0.88,
        system_confidence_score=0.85,
        system_confidence=SystemConfidenceLevel.HIGH.value,
        groundedness_status=GroundednessStatus.WELL_SUPPORTED.value,
    )
    db_session.add(hyp)
    await db_session.commit()

    # Generate proposal targeting this hypothesis
    gen_resp = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations/generate",
        headers=headers,
        json={"hypothesis_id": hyp.id},
    )
    assert gen_resp.status_code == status.HTTP_201_CREATED
    data = gen_resp.json()

    assert data["hypothesis_id"] == hyp.id
    assert "Connection Pool" in data["title"]
    assert len(data["actions"]) >= 2
    assert data["is_executable"] is False
    assert all(not a["is_executable"] for a in data["actions"])
    assert data["risk_assessment"]["groundedness_alignment"] is not None


@pytest.mark.asyncio
async def test_groundedness_impact_on_remediation_risk(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    # Seed an unsupported/contested hypothesis
    job = InvestigationJob(
        incident_id=inc_id,
        organization_id=org.id,
        status=InvestigationStatus.COMPLETED.value,
        stage="completed",
        progress=100,
    )
    db_session.add(job)
    await db_session.flush()

    weak_hyp = RootCauseHypothesis(
        investigation_job_id=job.id,
        incident_id=inc_id,
        organization_id=org.id,
        claim="Alleged memory leak in background worker.",
        rationale="Speculation without sufficient telemetry.",
        confidence=HypothesisConfidence.LOW.value,
        confidence_score=0.30,
        status=HypothesisStatus.CONTESTED.value,
        groundedness_score=0.20,
        system_confidence_score=0.15,
        system_confidence=SystemConfidenceLevel.LOW.value,
        groundedness_status=GroundednessStatus.WEAKLY_SUPPORTED.value,
    )
    db_session.add(weak_hyp)
    await db_session.commit()

    # Generate proposal
    gen_resp = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations/generate",
        headers=headers,
        json={"hypothesis_id": weak_hyp.id},
    )
    assert gen_resp.status_code == status.HTTP_201_CREATED
    data = gen_resp.json()

    risk_assessment = data["risk_assessment"]
    factors_text = " ".join(risk_assessment["risk_factors"])
    assert "grounding" in factors_text.lower() or "weak" in factors_text.lower() or "elevated" in factors_text.lower()


@pytest.mark.asyncio
async def test_risk_evaluator_destructive_keywords():
    actions = [
        {
            "step_number": 1,
            "action_type": RemediationActionType.CONFIG_CHANGE.value,
            "description": "Purge all records with drop table and rm -rf",
            "target_system": "Database Core",
            "command": "drop table audit_logs; rm -rf /tmp/data",
            "reversible": False,
        }
    ]
    eval_res = RiskEvaluator.evaluate(actions)
    assert eval_res.overall_risk_level in (RemediationRiskLevel.HIGH, RemediationRiskLevel.CRITICAL)
    assert eval_res.risk_score >= 0.80
    assert any("destructive" in f.lower() or "high-impact" in f.lower() for f in eval_res.risk_factors)
    assert any("irreversible" in f.lower() for f in eval_res.risk_factors)


@pytest.mark.asyncio
async def test_lifecycle_transitions(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    create_resp = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations",
        headers=headers,
        json={"title": "Proposal Lifecycle Test", "description": "Testing states", "actions": []},
    )
    p_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "proposed"

    # 1. proposed -> reviewed
    patch_resp1 = await client.patch(
        f"/api/v1/remediations/{p_id}/status",
        headers=headers,
        json={"target_status": "reviewed", "review_notes": "Reviewed and safe."},
    )
    assert patch_resp1.status_code == status.HTTP_200_OK
    assert patch_resp1.json()["status"] == "reviewed"
    assert patch_resp1.json()["review_notes"] == "Reviewed and safe."

    # 2. reviewed -> rejected
    patch_resp2 = await client.patch(
        f"/api/v1/remediations/{p_id}/status",
        headers=headers,
        json={"target_status": "rejected", "rejection_reason": "No longer needed."},
    )
    assert patch_resp2.status_code == status.HTTP_200_OK
    assert patch_resp2.json()["status"] == "rejected"
    assert patch_resp2.json()["rejection_reason"] == "No longer needed."


@pytest.mark.asyncio
async def test_invalid_lifecycle_transition_conflict(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    create_resp = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations",
        headers=headers,
        json={"title": "Terminal Proposal Test", "description": "Testing terminal conflict", "actions": []},
    )
    p_id = create_resp.json()["id"]

    # Reject the proposal (terminal)
    await client.patch(
        f"/api/v1/remediations/{p_id}/status",
        headers=headers,
        json={"target_status": "rejected", "rejection_reason": "Rejected terminal."},
    )

    # Attempting to move rejected back to proposed or reviewed must yield 409 Conflict
    conflict_resp = await client.patch(
        f"/api/v1/remediations/{p_id}/status",
        headers=headers,
        json={"target_status": "proposed"},
    )
    assert conflict_resp.status_code == status.HTTP_409_CONFLICT
    assert "Invalid lifecycle transition" in conflict_resp.json()["error"]["message"]


@pytest.mark.asyncio
async def test_tenant_isolation_cross_tenant_access_blocked(
    client: AsyncClient, test_user_and_org: dict, tenant2: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers1 = _headers(user)
    headers2 = {"Authorization": f"Bearer {tenant2['token']}"}

    inc1_id = await _make_incident(client, headers1)

    # Tenant 1 creates proposal
    p_resp = await client.post(
        f"/api/v1/incidents/{inc1_id}/remediations",
        headers=headers1,
        json={"title": "Tenant 1 Proposal", "description": "T1 confidential", "actions": []},
    )
    assert p_resp.status_code == status.HTTP_201_CREATED
    p1_id = p_resp.json()["id"]

    # Tenant 2 tries to GET proposal -> 404
    get_resp = await client.get(f"/api/v1/remediations/{p1_id}", headers=headers2)
    assert get_resp.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 tries to PATCH proposal -> 404
    patch_resp = await client.patch(
        f"/api/v1/remediations/{p1_id}/status",
        headers=headers2,
        json={"target_status": "cancelled"},
    )
    assert patch_resp.status_code == status.HTTP_404_NOT_FOUND

    # Tenant 2 tries to CREATE proposal on Tenant 1's incident -> 404
    cross_post = await client.post(
        f"/api/v1/incidents/{inc1_id}/remediations",
        headers=headers2,
        json={"title": "Cross Tenant Intrusion", "description": "Should fail", "actions": []},
    )
    assert cross_post.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_list_proposals_filter_and_pagination(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    # Create 3 proposals
    p1 = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations",
        headers=headers,
        json={"title": "Proposal 1", "description": "First", "actions": []},
    )
    p2 = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations",
        headers=headers,
        json={"title": "Proposal 2", "description": "Second", "actions": []},
    )
    p3 = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations",
        headers=headers,
        json={"title": "Proposal 3", "description": "Third", "actions": []},
    )
    assert p1.status_code == status.HTTP_201_CREATED
    assert p2.status_code == status.HTTP_201_CREATED
    assert p3.status_code == status.HTTP_201_CREATED
    p2_id = p2.json()["id"]

    # Transition p2 to reviewed
    await client.patch(
        f"/api/v1/remediations/{p2_id}/status",
        headers=headers,
        json={"target_status": "reviewed"},
    )

    # List all
    list_all = await client.get(f"/api/v1/incidents/{inc_id}/remediations", headers=headers)
    assert list_all.status_code == status.HTTP_200_OK
    assert list_all.json()["total"] == 3

    # Filter by status=reviewed
    list_filtered = await client.get(
        f"/api/v1/incidents/{inc_id}/remediations?status=reviewed", headers=headers
    )
    assert list_filtered.status_code == status.HTTP_200_OK
    assert list_filtered.json()["total"] == 1
    assert list_filtered.json()["items"][0]["id"] == p2_id


@pytest.mark.asyncio
async def test_recalculate_risk_endpoint(
    client: AsyncClient, test_user_and_org: dict, db_session: AsyncSession
):
    user: User = test_user_and_org["user"]
    headers = _headers(user)
    inc_id = await _make_incident(client, headers)

    create_resp = await client.post(
        f"/api/v1/incidents/{inc_id}/remediations",
        headers=headers,
        json={"title": "Recalculate Risk Test", "description": "Assess", "actions": []},
    )
    p_id = create_resp.json()["id"]

    recalc_resp = await client.post(f"/api/v1/remediations/{p_id}/risk-assessment", headers=headers)
    assert recalc_resp.status_code == status.HTTP_200_OK
    data = recalc_resp.json()
    assert "overall_risk_level" in data
    assert "risk_score" in data
    assert data["execution_restricted"] is True
