from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_HIERARCHY, get_current_active_user
from app.core.exceptions import ForbiddenException, ValidationException
from app.db.session import get_db
from app.models.membership import OrganizationRole
from app.models.user import User
from app.services.organizations.service import OrganizationService
from app.services.rag.conversations import ConversationService
from app.services.rag.schemas import (
    ConversationCreate,
    ConversationRead,
    ConversationWithMessagesRead,
    MessageRead,
)

router = APIRouter(prefix="/conversations", tags=["Conversations & Chat History"])


async def _resolve_organization(
    session: AsyncSession,
    current_user: User,
    x_organization_id: str | None,
) -> str:
    """Resolve target organization ID and verify membership."""
    org_id = x_organization_id
    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise ValidationException(message="User does not belong to any organization.")
        org_id = memberships[0].organization_id

    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException(message="Access denied: You do not belong to this organization.")

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.MEMBER]:
        raise ForbiddenException(
            message="Insufficient permissions: Conversation operations require at least MEMBER role."
        )

    return org_id


@router.get(
    "",
    response_model=list[ConversationRead],
    status_code=status.HTTP_200_OK,
    summary="List Organization Conversations",
    description="Lists recent conversation threads for the caller's organization.",
)
async def list_conversations(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> list[ConversationRead]:
    org_id = await _resolve_organization(session, current_user, x_organization_id)
    conversations, _ = await ConversationService.list_conversations(
        session=session,
        organization_id=org_id,
        user_id=current_user.id,
        limit=limit,
        offset=offset,
    )

    items: list[ConversationRead] = []
    for conv in conversations:
        items.append(
            ConversationRead(
                id=conv.id,
                organization_id=conv.organization_id,
                user_id=conv.user_id,
                title=conv.title,
                knowledge_base_ids=conv.knowledge_base_ids,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                message_count=len(conv.messages),
            )
        )
    return items


@router.post(
    "",
    response_model=ConversationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create Conversation Thread",
    description="Explicitly create a new conversation thread.",
)
async def create_conversation(
    payload: ConversationCreate,
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> ConversationRead:
    org_id = await _resolve_organization(session, current_user, x_organization_id)
    conv = await ConversationService.create_conversation(
        session=session,
        organization_id=org_id,
        user_id=current_user.id,
        title=payload.title,
        knowledge_base_ids=payload.knowledge_base_ids,
    )
    await session.commit()
    return ConversationRead(
        id=conv.id,
        organization_id=conv.organization_id,
        user_id=conv.user_id,
        title=conv.title,
        knowledge_base_ids=conv.knowledge_base_ids,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=0,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationWithMessagesRead,
    status_code=status.HTTP_200_OK,
    summary="Get Conversation Thread with Messages",
    description="Retrieves a conversation thread and full message history with citations and metadata.",
)
async def get_conversation(
    conversation_id: str,
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> ConversationWithMessagesRead:
    org_id = await _resolve_organization(session, current_user, x_organization_id)
    conv = await ConversationService.get_conversation(
        session=session,
        organization_id=org_id,
        conversation_id=conversation_id,
        load_messages=True,
    )

    messages = [
        MessageRead(
            id=m.id,
            conversation_id=m.conversation_id,
            role=m.role.value if hasattr(m.role, "value") else str(m.role),
            content=m.content,
            message_metadata=m.message_metadata,
            created_at=m.created_at,
        )
        for m in conv.messages
    ]

    return ConversationWithMessagesRead(
        id=conv.id,
        organization_id=conv.organization_id,
        user_id=conv.user_id,
        title=conv.title,
        knowledge_base_ids=conv.knowledge_base_ids,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        message_count=len(messages),
        messages=messages,
    )


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete Conversation Thread",
    description="Deletes a conversation thread and its associated message history.",
)
async def delete_conversation(
    conversation_id: str,
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> None:
    org_id = await _resolve_organization(session, current_user, x_organization_id)
    # Check existence and tenant isolation
    await ConversationService.get_conversation(
        session=session,
        organization_id=org_id,
        conversation_id=conversation_id,
        load_messages=False,
    )
    await ConversationService.delete_conversation(
        session=session,
        organization_id=org_id,
        conversation_id=conversation_id,
    )
