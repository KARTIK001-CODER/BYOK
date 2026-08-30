import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService


@pytest.mark.asyncio
async def test_cross_tenant_ingestion_and_chunk_access_denied(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """
    Mandatory Phase 4 Tenant Isolation Test:
    User A in Org A creates and ingests Document A.
    User B in Org B attempts to trigger ingestion, view jobs, or read chunks for Doc A.
    Expected: REJECTED (404 / 403).
    """
    # 1. Setup User A (Org A), upload Doc A and ingest it
    user_a: User = test_user_and_org["user"]
    token_a = create_access_token(user_a.id)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    md_content = b"# Tenant A Confidential\n\nProprietary intellectual property."
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers_a,
        files={"file": ("tenant_a_confidential.md", md_content, "text/markdown")},
    )
    doc_a_id = upload_res.json()["document"]["id"]

    ingest_res = await client.post(f"/api/v1/documents/{doc_a_id}/ingest", headers=headers_a)
    assert ingest_res.status_code == status.HTTP_200_OK
    job_id = ingest_res.json()["job_id"]

    # 2. Setup User B in an isolated Organization B
    pwd_b = PasswordService.hash("UserBSecretPass123!")
    user_b = User(
        email="user_b_phase4@tenant-b.com",
        password_hash=pwd_b,
        full_name="User B Phase 4",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user_b)
    await db_session.flush()

    org_b = Organization(name="Tenant B Org", slug="tenant-b-org")
    db_session.add(org_b)
    await db_session.flush()

    membership_b = OrganizationMembership(
        organization_id=org_b.id,
        user_id=user_b.id,
        role=OrganizationRole.OWNER,
    )
    db_session.add(membership_b)
    await db_session.commit()

    token_b = create_access_token(user_b.id)
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 3. User B attempts to trigger ingestion for Doc A -> 404
    res_cross_ingest = await client.post(f"/api/v1/documents/{doc_a_id}/ingest", headers=headers_b)
    assert res_cross_ingest.status_code == status.HTTP_404_NOT_FOUND

    # 4. User B attempts to view IngestionJob A -> 404
    res_cross_job = await client.get(f"/api/v1/ingestion-jobs/{job_id}", headers=headers_b)
    assert res_cross_job.status_code == status.HTTP_404_NOT_FOUND

    # 5. User B attempts to list chunks for Doc A -> 404
    res_cross_chunks = await client.get(f"/api/v1/documents/{doc_a_id}/chunks", headers=headers_b)
    assert res_cross_chunks.status_code == status.HTTP_404_NOT_FOUND
