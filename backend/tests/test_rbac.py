import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User


@pytest.mark.asyncio
async def test_rbac_role_hierarchy_permissions(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Test RBAC Role hierarchy:
    OWNER > ADMIN > MEMBER.
    - Owner can access admin & owner endpoints.
    - Admin can access admin endpoint, denied owner endpoint.
    - Member is denied admin and owner endpoints.
    """
    # 1. Create Organization
    org = Organization(name="RBAC Org", slug="rbac-org")
    db_session.add(org)
    await db_session.flush()

    # 2. Create Owner, Admin, Member Users
    owner = User(email="owner@test.com", password_hash="hash", full_name="Owner", is_active=True)
    admin = User(email="admin@test.com", password_hash="hash", full_name="Admin", is_active=True)
    member = User(email="member@test.com", password_hash="hash", full_name="Member", is_active=True)
    db_session.add_all([owner, admin, member])
    await db_session.flush()

    # 3. Create Memberships
    m_owner = OrganizationMembership(
        organization_id=org.id, user_id=owner.id, role=OrganizationRole.OWNER
    )
    m_admin = OrganizationMembership(
        organization_id=org.id, user_id=admin.id, role=OrganizationRole.ADMIN
    )
    m_member = OrganizationMembership(
        organization_id=org.id, user_id=member.id, role=OrganizationRole.MEMBER
    )
    db_session.add_all([m_owner, m_admin, m_member])
    await db_session.commit()

    owner_token = create_access_token(owner.id)
    admin_token = create_access_token(admin.id)
    member_token = create_access_token(member.id)

    # 4. Test OWNER permissions
    res = await client.get(
        f"/api/v1/organizations/{org.id}/admin-only",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res.status_code == status.HTTP_200_OK

    res = await client.get(
        f"/api/v1/organizations/{org.id}/owner-only",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert res.status_code == status.HTTP_200_OK

    # 5. Test ADMIN permissions
    res = await client.get(
        f"/api/v1/organizations/{org.id}/admin-only",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == status.HTTP_200_OK

    res = await client.get(
        f"/api/v1/organizations/{org.id}/owner-only",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
    assert "Insufficient permissions" in res.json()["error"]["message"]

    # 6. Test MEMBER permissions
    res = await client.get(
        f"/api/v1/organizations/{org.id}/admin-only",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN

    res = await client.get(
        f"/api/v1/organizations/{org.id}/owner-only",
        headers={"Authorization": f"Bearer {member_token}"},
    )
    assert res.status_code == status.HTTP_403_FORBIDDEN
