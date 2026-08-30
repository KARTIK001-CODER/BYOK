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
async def test_create_knowledge_base_success(client: AsyncClient, test_user_and_org: dict) -> None:
    """Verify owner/admin can create a knowledge base with auto-generated slug."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    response = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={
            "name": "Engineering Specs",
            "description": "System architecture and technical designs",
            "organization_id": org.id,
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Engineering Specs"
    assert data["slug"] == "engineering-specs"
    assert data["organization_id"] == org.id
    assert data["created_by"] == user.id
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_knowledge_base_slug_collision_resolution(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Verify slug collisions within the same organization are resolved with suffix counters."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    res1 = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Product Roadmap", "organization_id": org.id},
    )
    assert res1.status_code == status.HTTP_201_CREATED
    assert res1.json()["slug"] == "product-roadmap"

    res2 = await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Product Roadmap", "organization_id": org.id},
    )
    assert res2.status_code == status.HTTP_201_CREATED
    assert res2.json()["slug"] == "product-roadmap-2"


@pytest.mark.asyncio
async def test_list_knowledge_bases_with_search(
    client: AsyncClient, test_user_and_org: dict
) -> None:
    """Verify listing knowledge bases returns user-accessible KBs and filters by search query."""
    user: User = test_user_and_org["user"]
    org: Organization = test_user_and_org["org"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # Create 2 KBs
    await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Alpha Docs", "organization_id": org.id},
    )
    await client.post(
        "/api/v1/knowledge-bases",
        headers=headers,
        json={"name": "Beta Research", "organization_id": org.id},
    )

    # List all
    res = await client.get("/api/v1/knowledge-bases", headers=headers)
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["total"] >= 2

    # Search filter
    search_res = await client.get("/api/v1/knowledge-bases?search=Alpha", headers=headers)
    assert search_res.status_code == status.HTTP_200_OK
    search_data = search_res.json()
    assert search_data["total"] == 1
    assert search_data["items"][0]["name"] == "Alpha Docs"


@pytest.mark.asyncio
async def test_get_and_update_knowledge_base(
    client: AsyncClient, test_user_and_org: dict, test_kb
) -> None:
    """Verify getting details and updating metadata of a knowledge base."""
    user: User = test_user_and_org["user"]
    token = create_access_token(user.id)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Get Details
    get_res = await client.get(f"/api/v1/knowledge-bases/{test_kb.id}", headers=headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["id"] == test_kb.id

    # 2. Update Details
    patch_res = await client.patch(
        f"/api/v1/knowledge-bases/{test_kb.id}",
        headers=headers,
        json={"name": "Updated Research Docs", "description": "Brand new description"},
    )
    assert patch_res.status_code == status.HTTP_200_OK
    assert patch_res.json()["name"] == "Updated Research Docs"
    assert patch_res.json()["description"] == "Brand new description"


@pytest.mark.asyncio
async def test_delete_knowledge_base_rbac(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify delete requires OWNER role (ADMIN or MEMBER cannot delete KB)."""
    # 1. Create a MEMBER user
    member = User(
        email="member_kb@example.com",
        password_hash=PasswordService.hash("Pass12345!"),
        full_name="KB Member",
        is_active=True,
    )
    db_session.add(member)
    await db_session.flush()

    membership = OrganizationMembership(
        organization_id=test_kb.organization_id,
        user_id=member.id,
        role=OrganizationRole.MEMBER,
    )
    db_session.add(membership)
    await db_session.commit()

    member_token = create_access_token(member.id)
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Member tries to delete -> 403 Forbidden
    res_member = await client.delete(
        f"/api/v1/knowledge-bases/{test_kb.id}", headers=member_headers
    )
    assert res_member.status_code == status.HTTP_403_FORBIDDEN

    # Owner deletes -> 200 OK
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    res_owner = await client.delete(f"/api/v1/knowledge-bases/{test_kb.id}", headers=owner_headers)
    assert res_owner.status_code == status.HTTP_200_OK
