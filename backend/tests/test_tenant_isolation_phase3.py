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
async def test_cross_tenant_knowledge_base_and_document_access_denied(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """
    Mandatory Phase 3 Tenant Isolation Test:
    User A belongs to Org A (owning test_kb).
    User B belongs to Org B.
    Verify User B cannot view, update, delete, or upload into Org A's KB or Documents.
    """
    # 1. Setup User A (Org A) and upload Document A
    user_a: User = test_user_and_org["user"]
    token_a = create_access_token(user_a.id)
    headers_a = {"Authorization": f"Bearer {token_a}"}

    pdf_bytes = b"%PDF-1.7\nTenant A Secret Document\n%%EOF"
    upload_res = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers_a,
        files={"file": ("tenant_a_doc.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == status.HTTP_201_CREATED
    doc_a_id = upload_res.json()["document"]["id"]

    # 2. Setup User B in an isolated Organization B
    pwd_b = PasswordService.hash("UserBSecretPass123!")
    user_b = User(
        email="user_b@tenant-b.com",
        password_hash=pwd_b,
        full_name="User B Tenant",
        is_active=True,
        is_verified=True,
    )
    db_session.add(user_b)
    await db_session.flush()

    org_b = Organization(name="Tenant B Workspace", slug="tenant-b-workspace")
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

    # 3. User B attempts to read KB A -> 404 (Not Found)
    res_get_kb = await client.get(f"/api/v1/knowledge-bases/{test_kb.id}", headers=headers_b)
    assert res_get_kb.status_code == status.HTTP_404_NOT_FOUND

    # 4. User B attempts to update KB A -> 404
    res_patch_kb = await client.patch(
        f"/api/v1/knowledge-bases/{test_kb.id}",
        headers=headers_b,
        json={"name": "Hacked KB Name"},
    )
    assert res_patch_kb.status_code == status.HTTP_404_NOT_FOUND

    # 5. User B attempts to delete KB A -> 404
    res_del_kb = await client.delete(f"/api/v1/knowledge-bases/{test_kb.id}", headers=headers_b)
    assert res_del_kb.status_code == status.HTTP_404_NOT_FOUND

    # 6. User B attempts to upload into KB A -> 404
    fake_pdf = b"%PDF-1.7\nInjected Cross-Tenant Payload\n%%EOF"
    res_upload_b = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers_b,
        files={"file": ("injected.pdf", fake_pdf, "application/pdf")},
    )
    assert res_upload_b.status_code == status.HTTP_404_NOT_FOUND

    # 7. User B attempts to get Document A -> 404
    res_get_doc = await client.get(f"/api/v1/documents/{doc_a_id}", headers=headers_b)
    assert res_get_doc.status_code == status.HTTP_404_NOT_FOUND

    # 8. User B attempts to patch Document A -> 404
    res_patch_doc = await client.patch(
        f"/api/v1/documents/{doc_a_id}",
        headers=headers_b,
        json={"name": "Hacked Doc Name"},
    )
    assert res_patch_doc.status_code == status.HTTP_404_NOT_FOUND

    # 9. User B attempts to delete Document A -> 404
    res_del_doc = await client.delete(f"/api/v1/documents/{doc_a_id}", headers=headers_b)
    assert res_del_doc.status_code == status.HTTP_404_NOT_FOUND
