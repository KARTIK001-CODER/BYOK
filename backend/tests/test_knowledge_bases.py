from datetime import UTC, datetime

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.document import Document, DocumentStatus
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


@pytest.mark.asyncio
async def test_rename_knowledge_base_rbac(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify renaming a knowledge base requires ADMIN or OWNER role (MEMBER receives 403)."""
    # 1. Member tries to rename -> 403 Forbidden
    member = User(
        email="rename_member@example.com",
        password_hash=PasswordService.hash("Pass12345!"),
        full_name="Rename Member",
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

    res_member = await client.patch(
        f"/api/v1/knowledge-bases/{test_kb.id}",
        headers=member_headers,
        json={"name": "Member Renamed KB"},
    )
    assert res_member.status_code == status.HTTP_403_FORBIDDEN
    assert "ADMIN or OWNER" in res_member.json()["error"]["message"]

    # 2. Owner renames -> 200 OK with new slug
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    res_owner = await client.patch(
        f"/api/v1/knowledge-bases/{test_kb.id}",
        headers=owner_headers,
        json={"name": "Owner Renamed KB", "description": "New description by owner"},
    )
    assert res_owner.status_code == status.HTTP_200_OK
    data = res_owner.json()
    assert data["name"] == "Owner Renamed KB"
    assert data["slug"] == "owner-renamed-kb"
    assert data["description"] == "New description by owner"


@pytest.mark.asyncio
async def test_knowledge_base_stats_empty_and_tenant_isolation(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify stats on empty knowledge base, member access, and cross-tenant rejection."""
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # 1. Empty KB stats
    res = await client.get(f"/api/v1/knowledge-bases/{test_kb.id}/stats", headers=owner_headers)
    assert res.status_code == status.HTTP_200_OK
    stats = res.json()
    assert stats["knowledge_base_id"] == test_kb.id
    assert stats["total_documents"] == 0
    assert stats["total_chunks"] == 0
    assert stats["total_file_size_bytes"] == 0
    assert stats["ready_documents"] == 0
    assert stats["processing_documents"] == 0
    assert stats["failed_documents"] == 0
    assert stats["pending_embeddings"] == 0
    assert stats["failed_embeddings"] == 0

    # 2. Member of org can view stats
    member = User(
        email="stats_member@example.com",
        password_hash=PasswordService.hash("Pass12345!"),
        full_name="Stats Member",
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

    res_member = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/stats", headers=member_headers
    )
    assert res_member.status_code == status.HTTP_200_OK
    assert res_member.json()["total_documents"] == 0

    # 3. Unauthorized non-member receives 404 (tenant isolation)
    other_user = User(
        email="outsider@example.com",
        password_hash=PasswordService.hash("Pass12345!"),
        full_name="Outsider",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()

    other_token = create_access_token(other_user.id)
    other_headers = {"Authorization": f"Bearer {other_token}"}

    res_other = await client.get(
        f"/api/v1/knowledge-bases/{test_kb.id}/stats", headers=other_headers
    )
    assert res_other.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_knowledge_base_stats_mixed_statuses_and_soft_delete(
    client: AsyncClient, db_session: AsyncSession, test_user_and_org: dict, test_kb
) -> None:
    """Verify stats aggregates across mixed document/embedding states and excludes soft-deleted records."""
    owner: User = test_user_and_org["user"]
    owner_token = create_access_token(owner.id)
    headers = {"Authorization": f"Bearer {owner_token}"}

    # Doc 1: Ingested & Embedded (READY, COMPLETED)
    res_up1 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("doc1.md", b"# Doc 1\n\nFull content paragraph here.", "text/markdown")},
    )
    doc1_id = res_up1.json()["document"]["id"]
    await client.post(f"/api/v1/documents/{doc1_id}/ingest", headers=headers)
    await client.post(f"/api/v1/documents/{doc1_id}/embed", headers=headers)

    # Doc 2: Ingested, Embeddings Pending/None (READY, None)
    res_up2 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("doc2.md", b"# Doc 2\n\nContent awaiting embeddings.", "text/markdown")},
    )
    doc2_id = res_up2.json()["document"]["id"]
    await client.post(f"/api/v1/documents/{doc2_id}/ingest", headers=headers)

    # Doc 3: Failed Ingestion (FAILED)
    res_up3 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("doc3.txt", b"Failed doc", "text/plain")},
    )
    doc3_id = res_up3.json()["document"]["id"]
    doc3_db = await db_session.get(Document, doc3_id)
    doc3_db.status = DocumentStatus.FAILED
    await db_session.commit()

    # Doc 4: Actively Processing (PROCESSING)
    res_up4 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("doc4.txt", b"Processing doc", "text/plain")},
    )
    doc4_id = res_up4.json()["document"]["id"]
    doc4_db = await db_session.get(Document, doc4_id)
    doc4_db.status = DocumentStatus.PROCESSING
    await db_session.commit()

    # Doc 5: Soft-deleted (must be excluded from stats)
    res_up5 = await client.post(
        f"/api/v1/knowledge-bases/{test_kb.id}/documents",
        headers=headers,
        files={"file": ("doc5.txt", b"Deleted doc", "text/plain")},
    )
    doc5_id = res_up5.json()["document"]["id"]
    doc5_db = await db_session.get(Document, doc5_id)
    doc5_db.deleted_at = datetime.now(UTC)
    await db_session.commit()

    # Query statistics
    res_stats = await client.get(f"/api/v1/knowledge-bases/{test_kb.id}/stats", headers=headers)
    assert res_stats.status_code == status.HTTP_200_OK
    stats = res_stats.json()

    # 4 active documents (doc 5 excluded)
    assert stats["total_documents"] == 4
    assert stats["ready_documents"] == 2  # doc 1, doc 2
    assert stats["processing_documents"] == 1  # doc 4
    assert stats["failed_documents"] == 1  # doc 3
    assert stats["pending_embeddings"] == 1  # doc 2
    assert stats["failed_embeddings"] == 0
    assert stats["total_chunks"] > 0
    assert stats["total_file_size_bytes"] > 0
