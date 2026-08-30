import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User


@pytest.mark.asyncio
async def test_tenant_isolation_cross_access_denied(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """
    Mandatory Tenant Isolation Regression Test:
    User A (member of Org A only) attempts to access Org B -> Access Denied (403 Forbidden).
    User B (member of Org B only) attempts to access Org A -> Access Denied (403 Forbidden).
    """
    # 1. Create Organization A and User A
    org_a = Organization(name="Organization Alpha", slug="org-alpha")
    user_a = User(
        email="user.a@alpha.com",
        password_hash="hash_a",
        full_name="User Alpha",
        is_active=True,
    )
    db_session.add_all([org_a, user_a])
    await db_session.flush()

    mem_a = OrganizationMembership(
        organization_id=org_a.id,
        user_id=user_a.id,
        role=OrganizationRole.OWNER,
    )
    db_session.add(mem_a)

    # 2. Create Organization B and User B
    org_b = Organization(name="Organization Beta", slug="org-beta")
    user_b = User(
        email="user.b@beta.com",
        password_hash="hash_b",
        full_name="User Beta",
        is_active=True,
    )
    db_session.add_all([org_b, user_b])
    await db_session.flush()

    mem_b = OrganizationMembership(
        organization_id=org_b.id,
        user_id=user_b.id,
        role=OrganizationRole.OWNER,
    )
    db_session.add(mem_b)

    await db_session.commit()

    token_a = create_access_token(user_a.id)
    token_b = create_access_token(user_b.id)

    # 3. User A can access Org A
    res_a_a = await client.get(
        f"/api/v1/organizations/{org_a.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a_a.status_code == status.HTTP_200_OK
    assert res_a_a.json()["id"] == org_a.id

    # 4. User A attempts to access Org B -> MUST BE DENIED (403)
    res_a_b = await client.get(
        f"/api/v1/organizations/{org_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert res_a_b.status_code == status.HTTP_403_FORBIDDEN
    assert "Access denied" in res_a_b.json()["error"]["message"]

    # 5. User B can access Org B
    res_b_b = await client.get(
        f"/api/v1/organizations/{org_b.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_b.status_code == status.HTTP_200_OK
    assert res_b_b.json()["id"] == org_b.id

    # 6. User B attempts to access Org A -> MUST BE DENIED (403)
    res_b_a = await client.get(
        f"/api/v1/organizations/{org_a.id}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert res_b_a.status_code == status.HTTP_403_FORBIDDEN
    assert "Access denied" in res_b_a.json()["error"]["message"]

    # 7. List endpoint only returns current user's organizations
    list_res_a = await client.get(
        "/api/v1/organizations",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert list_res_a.status_code == status.HTTP_200_OK
    org_ids_a = [m["organization_id"] for m in list_res_a.json()]
    assert org_a.id in org_ids_a
    assert org_b.id not in org_ids_a
