import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.services.auth.password import PasswordService
from app.services.rag.conversations import ConversationService


@pytest.mark.asyncio
async def test_conversation_crud_and_isolation(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user_and_org: dict,
):
    """Test conversation creation, listing, retrieval, and multi-tenant isolation."""
    user1: User = test_user_and_org["user"]
    org1: Organization = test_user_and_org["org"]
    token1 = create_access_token(user1.id)

    # Create Org 2 and User 2
    pwd_hash = PasswordService.hash("Pass12345!")
    user2 = User(email="user2@example.com", password_hash=pwd_hash, full_name="User Two")
    db_session.add(user2)
    await db_session.flush()

    org2 = Organization(name="Org Two", slug="org-two")
    db_session.add(org2)
    await db_session.flush()

    mem2 = OrganizationMembership(
        organization_id=org2.id, user_id=user2.id, role=OrganizationRole.OWNER
    )
    db_session.add(mem2)
    await db_session.commit()

    token2 = create_access_token(user2.id)

    # 1. User 1 creates conversation in Org 1
    resp = await client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token1}", "X-Organization-ID": org1.id},
        json={"title": "Architecture Discussions"},
    )
    assert resp.status_code == 201
    conv_data = resp.json()
    conv1_id = conv_data["id"]
    assert conv_data["title"] == "Architecture Discussions"

    # Add message directly
    await ConversationService.add_message(
        session=db_session,
        conversation_id=conv1_id,
        role="user",
        content="What is the architecture?",
    )
    await db_session.commit()

    # 2. User 1 gets conversation
    resp = await client.get(
        f"/api/v1/conversations/{conv1_id}",
        headers={"Authorization": f"Bearer {token1}", "X-Organization-ID": org1.id},
    )
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["id"] == conv1_id
    assert len(detail["messages"]) == 1

    # 3. User 2 (Org 2) attempts to access User 1's conversation -> 404 / Access Denied
    resp = await client.get(
        f"/api/v1/conversations/{conv1_id}",
        headers={"Authorization": f"Bearer {token2}", "X-Organization-ID": org2.id},
    )
    assert resp.status_code == 404

    # 4. User 2 attempts to delete User 1's conversation -> 404
    resp = await client.delete(
        f"/api/v1/conversations/{conv1_id}",
        headers={"Authorization": f"Bearer {token2}", "X-Organization-ID": org2.id},
    )
    assert resp.status_code == 404

    # 5. User 1 deletes their conversation -> 204
    resp = await client.delete(
        f"/api/v1/conversations/{conv1_id}",
        headers={"Authorization": f"Bearer {token1}", "X-Organization-ID": org1.id},
    )
    assert resp.status_code == 204

    # Verify deleted
    resp = await client.get(
        f"/api/v1/conversations/{conv1_id}",
        headers={"Authorization": f"Bearer {token1}", "X-Organization-ID": org1.id},
    )
    assert resp.status_code == 404
