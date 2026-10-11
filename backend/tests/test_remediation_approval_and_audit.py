"""TracePilot Milestone 5B tests: human approval, policy enforcement & audit trail."""


import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService


def _headers(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
async def tenant_members(db_session: AsyncSession, test_user_and_org: dict) -> dict:
    """Fixture providing additional members in test organization with distinct roles."""
    org: Organization = test_user_and_org["org"]
    owner_user: User = test_user_and_org["user"]

    pwd_hash = PasswordService.hash("StrongPassword123!")

    # Member user
    member_user = User(
        email="regular-member@example.com",
        password_hash=pwd_hash,
        full_name="Regular Member",
        is_active=True,
        is_verified=True,
    )
    db_session.add(member_user)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=member_user.id,
            role=OrganizationRole.MEMBER,
        )
    )

    # Admin user
    admin_user = User(
        email="sre-admin@example.com",
        password_hash=pwd_hash,
        full_name="SRE Admin",
        is_active=True,
        is_verified=True,
    )
    db_session.add(admin_user)
    await db_session.flush()
    db_session.add(
        OrganizationMembership(
            organization_id=org.id,
            user_id=admin_user.id,
            role=OrganizationRole.ADMIN,
        )
    )

    await db_session.commit()

    return {
        "org": org,
        "owner": owner_user,
        "admin": admin_user,
        "member": member_user,
    }


@pytest.fixture
async def foreign_tenant(db_session: AsyncSession) -> dict:
    """Fixture providing an entirely distinct tenant for isolation checks."""
    pwd_hash = PasswordService.hash("StrongPassword123!")
    user = User(
        email="foreign-tenant@example.com",
        password_hash=pwd_hash,
        full_name="Foreign Tenant",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    org = Organization(name="Foreign Org", slug="foreign-org")
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
    return {"user": user, "org": org}


async def _create_test_incident(client: AsyncClient, headers: dict) -> str:
    payload = {
        "title": "Database Read Replicas Failing",
        "severity": "high",
        "service_name": "db-proxy",
        "environment": "production",
    }
    resp = await client.post("/api/v1/incidents", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    return resp.json()["id"]


async def _create_proposal(
    client: AsyncClient,
    headers: dict,
    incident_id: str,
    title: str = "Restart DB Replicas",
    risk_level: str = "medium",
    is_high_risk: bool = False,
) -> dict:
    actions = [
        {
            "step_number": 1,
            "action_type": "service_restart" if not is_high_risk else "rollback",
            "description": "Restart or rollback service",
            "target_system": "database-replica",
            "command": "kubectl rollout restart deployment/replica" if not is_high_risk else "drop table tmp_old",
            "risk_level": "medium" if not is_high_risk else "critical",
            "reversible": not is_high_risk,
            "requires_human_approval": True,
            "is_executable": False,
        }
    ]
    payload = {
        "title": title,
        "description": "Remediation plan description",
        "actions": actions,
        "is_executable": False,
    }
    resp = await client.post(f"/api/v1/incidents/{incident_id}/remediations", headers=headers, json=payload)
    assert resp.status_code == status.HTTP_201_CREATED
    return resp.json()


# ─── 1. Successful Approval by Authorized Reviewer ────────────────────────────


@pytest.mark.asyncio
async def test_successful_approval_by_authorized_reviewer(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    # Owner creates proposal
    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Medium Risk Mitigation")
    prop_id = prop["id"]

    # Admin approves with rationale
    appr_resp = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Reviewed changes against telemetry; approved for manual rollout."},
    )
    assert appr_resp.status_code == status.HTTP_200_OK
    data = appr_resp.json()
    assert data["decision"] == "approved"
    assert data["reviewer_user_id"] == admin.id
    assert data["proposal_version"] == 1
    assert "snapshot" in data
    assert data["snapshot"]["title"] == "Medium Risk Mitigation"

    # Verify proposal status transitioned to approved
    get_resp = await client.get(f"/api/v1/remediations/{prop_id}", headers=_headers(admin))
    assert get_resp.status_code == status.HTTP_200_OK
    assert get_resp.json()["status"] == "approved"
    assert get_resp.json()["approved_by_user_id"] == admin.id
    assert get_resp.json()["approved_at"] is not None


# ─── 2. Successful Rejection with Rationale ───────────────────────────────────


@pytest.mark.asyncio
async def test_successful_rejection_with_rationale(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Faulty Mitigation")
    prop_id = prop["id"]

    rej_resp = await client.post(
        f"/api/v1/remediations/{prop_id}/reject",
        headers=_headers(admin),
        json={"rationale": "Proposed restart is insufficient without schema migration."},
    )
    assert rej_resp.status_code == status.HTTP_200_OK
    data = rej_resp.json()
    assert data["decision"] == "rejected"
    assert data["reviewer_user_id"] == admin.id

    # Verify proposal status is rejected and terminal
    get_resp = await client.get(f"/api/v1/remediations/{prop_id}", headers=_headers(admin))
    assert get_resp.status_code == status.HTTP_200_OK
    assert get_resp.json()["status"] == "rejected"
    assert get_resp.json()["rejection_reason"] == "Proposed restart is insufficient without schema migration."


# ─── 3. Creator Self-Approval Rejection (Separation of Duties) ────────────────


@pytest.mark.asyncio
async def test_creator_self_approval_rejected(client: AsyncClient, tenant_members: dict):
    owner = tenant_members["owner"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Self Approval Attempt")
    prop_id = prop["id"]

    # Owner attempts to approve their own proposal -> 403 Forbidden
    appr_resp = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(owner),
        json={"rationale": "I created this and I approve it myself."},
    )
    assert appr_resp.status_code == status.HTTP_403_FORBIDDEN
    err = appr_resp.json()
    assert "Separation of duties violation" in err["error"]["message"]


# ─── 4. High / Critical Risk Role Restriction ─────────────────────────────────


@pytest.mark.asyncio
async def test_high_risk_proposal_requires_admin_or_owner(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    member = tenant_members["member"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    # Create high-risk proposal (contains destructive keywords)
    prop = await _create_proposal(
        client, _headers(owner), inc_id, title="Critical DB Truncate", is_high_risk=True
    )
    prop_id = prop["id"]
    assert prop["risk_level"] in ("high", "critical")

    # Regular member tries to approve high-risk proposal -> 403 Forbidden
    mem_resp = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(member),
        json={"rationale": "Member approval attempt on high risk."},
    )
    assert mem_resp.status_code == status.HTTP_403_FORBIDDEN
    assert "Insufficient authorization" in mem_resp.json()["error"]["details"]["violations"][0]

    # Admin approves -> 200 OK
    admin_resp = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Admin sign-off on critical operation."},
    )
    assert admin_resp.status_code == status.HTTP_200_OK
    assert admin_resp.json()["decision"] == "approved"


# ─── 5. Tenant Isolation Protection ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_cross_tenant_approval_and_audit_blocked(
    client: AsyncClient, tenant_members: dict, foreign_tenant: dict
):
    owner = tenant_members["owner"]
    foreign_user = foreign_tenant["user"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Tenant Confidential Plan")
    prop_id = prop["id"]

    # Foreign tenant tries to approve -> 404 Not Found (no existence leak)
    foreign_appr = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(foreign_user),
        json={"rationale": "Cross-tenant intrusion attempt."},
    )
    assert foreign_appr.status_code == status.HTTP_404_NOT_FOUND

    # Foreign tenant tries to list approvals -> 404 Not Found
    foreign_list = await client.get(
        f"/api/v1/remediations/{prop_id}/approvals", headers=_headers(foreign_user)
    )
    assert foreign_list.status_code == status.HTTP_404_NOT_FOUND

    # Foreign tenant tries to view audit events -> 404 Not Found
    foreign_audit = await client.get(
        f"/api/v1/remediations/{prop_id}/audit", headers=_headers(foreign_user)
    )
    assert foreign_audit.status_code == status.HTTP_404_NOT_FOUND


# ─── 6. Terminal State Transition Conflict ────────────────────────────────────


@pytest.mark.asyncio
async def test_terminal_proposals_cannot_be_approved(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Cancelled Plan")
    prop_id = prop["id"]

    # Cancel proposal
    await client.patch(
        f"/api/v1/remediations/{prop_id}/status",
        headers=_headers(owner),
        json={"target_status": "cancelled"},
    )

    # Attempt to approve cancelled proposal -> 409 Conflict
    appr_resp = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Approval after cancellation."},
    )
    assert appr_resp.status_code == status.HTTP_409_CONFLICT
    assert "cannot be approved in its current status: 'cancelled'" in appr_resp.json()["error"]["message"]


# ─── 7. Proposal Mutation Invalidates Approval ────────────────────────────────


@pytest.mark.asyncio
async def test_proposal_mutation_invalidates_approval(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Plan to Modify")
    prop_id = prop["id"]

    # 1. Admin approves version 1
    await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Approved version 1."},
    )

    # Verify approved
    p1 = (await client.get(f"/api/v1/remediations/{prop_id}", headers=_headers(admin))).json()
    assert p1["status"] == "approved"
    assert p1["version"] == 1

    # 2. Recalculate risk on approved proposal (mutation)
    recalc = await client.post(
        f"/api/v1/remediations/{prop_id}/risk-assessment", headers=_headers(admin)
    )
    assert recalc.status_code == status.HTTP_200_OK

    # 3. Verify approval was invalidated: version incremented, status reverted to proposed
    p2 = (await client.get(f"/api/v1/remediations/{prop_id}", headers=_headers(admin))).json()
    assert p2["version"] == 2
    assert p2["status"] == "proposed"
    assert p2["approved_by_user_id"] is None
    assert p2["approved_at"] is None

    # 4. Check audit log has 'approval_invalidated' event
    audit_resp = await client.get(f"/api/v1/remediations/{prop_id}/audit", headers=_headers(admin))
    assert audit_resp.status_code == status.HTTP_200_OK
    event_types = [e["event_type"] for e in audit_resp.json()["items"]]
    assert "approval_invalidated" in event_types


# ─── 8. Append-Only Audit History and Provenance ──────────────────────────────


@pytest.mark.asyncio
async def test_append_only_audit_log_and_approvals_history(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Audit Trail Test")
    prop_id = prop["id"]

    # Transition to reviewed
    await client.patch(
        f"/api/v1/remediations/{prop_id}/status",
        headers=_headers(owner),
        json={"target_status": "reviewed", "review_notes": "First pass review done."},
    )

    # Approve
    await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Audit check approval."},
    )

    # Fetch audit events
    audit_resp = await client.get(f"/api/v1/remediations/{prop_id}/audit", headers=_headers(admin))
    assert audit_resp.status_code == status.HTTP_200_OK
    audit_items = audit_resp.json()["items"]
    assert audit_resp.json()["total"] >= 3

    event_types = [e["event_type"] for e in audit_items]
    assert "proposal_created" in event_types
    assert "status_changed" in event_types
    assert "proposal_approved" in event_types

    # Fetch approvals history
    appr_resp = await client.get(f"/api/v1/remediations/{prop_id}/approvals", headers=_headers(admin))
    assert appr_resp.status_code == status.HTTP_200_OK
    assert appr_resp.json()["total"] == 1
    assert appr_resp.json()["items"][0]["decision"] == "approved"
    assert appr_resp.json()["items"][0]["rationale"] == "Audit check approval."


# ─── 9. Safe Deterministic Dry-Run Validation ─────────────────────────────────


@pytest.mark.asyncio
async def test_policy_dry_run_validation(client: AsyncClient, tenant_members: dict):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]
    member = tenant_members["member"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(
        client, _headers(owner), inc_id, title="Dry Run Test Plan", is_high_risk=True
    )
    prop_id = prop["id"]

    # 1. Creator runs dry-run: shows separation of duties violation
    creator_dry_run = await client.post(
        f"/api/v1/remediations/{prop_id}/dry-run", headers=_headers(owner)
    )
    assert creator_dry_run.status_code == status.HTTP_200_OK
    cr_data = creator_dry_run.json()
    assert cr_data["dry_run_type"] == "local_policy_validation"
    assert cr_data["allowed"] is False
    assert cr_data["separation_of_duties_passed"] is False

    # 2. Member runs dry-run: shows insufficient role violation for critical risk
    member_dry_run = await client.post(
        f"/api/v1/remediations/{prop_id}/dry-run", headers=_headers(member)
    )
    assert member_dry_run.status_code == status.HTTP_200_OK
    mem_data = member_dry_run.json()
    assert mem_data["allowed"] is False
    assert any("Insufficient authorization" in v for v in mem_data["violations"])

    # 3. Admin runs dry-run: allowed is True
    admin_dry_run = await client.post(
        f"/api/v1/remediations/{prop_id}/dry-run", headers=_headers(admin)
    )
    assert admin_dry_run.status_code == status.HTTP_200_OK
    ad_data = admin_dry_run.json()
    assert ad_data["allowed"] is True
    assert ad_data["separation_of_duties_passed"] is True
    assert ad_data["lifecycle_eligible"] is True
    assert len(ad_data["violations"]) == 0
    assert "local, deterministic policy validation only" in ad_data["disclaimer"]


# ─── 10. Forbidden Execution Remains Forbidden After Approval ──────────────────


@pytest.mark.asyncio
async def test_forbidden_execution_remains_forbidden_after_approval(
    client: AsyncClient, tenant_members: dict
):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Plan to Execute")
    prop_id = prop["id"]

    # Approve proposal
    await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Approved for human review."},
    )

    # Calling execute MUST still return HTTP 403 Forbidden
    exec_resp = await client.post(f"/api/v1/remediations/{prop_id}/execute", headers=_headers(admin))
    assert exec_resp.status_code == status.HTTP_403_FORBIDDEN
    assert "Automated execution of remediation actions is strictly forbidden" in exec_resp.json()["error"]["message"]
    assert "Approval only confirms organizational policy compliance" in exec_resp.json()["error"]["message"]


# ─── 11. Concurrent / Duplicate Approval Conflict ─────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_approval_conflict(client: AsyncClient, tenant_members: dict):
    owner = tenant_members["owner"]
    admin = tenant_members["admin"]

    inc_id = await _create_test_incident(client, _headers(owner))
    prop = await _create_proposal(client, _headers(owner), inc_id, title="Duplicate Approval Test")
    prop_id = prop["id"]

    # First approval succeeds
    r1 = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Initial approval."},
    )
    assert r1.status_code == status.HTTP_200_OK

    # Repeated approval on the same version yields 409 Conflict
    r2 = await client.post(
        f"/api/v1/remediations/{prop_id}/approve",
        headers=_headers(admin),
        json={"rationale": "Duplicate approval attempt."},
    )
    assert r2.status_code == status.HTTP_409_CONFLICT
    assert "already approved" in r2.json()["error"]["message"]
