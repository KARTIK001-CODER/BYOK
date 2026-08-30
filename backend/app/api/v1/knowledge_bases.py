from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    ROLE_HIERARCHY,
    get_current_active_user,
    get_knowledge_base_or_404,
)
from app.core.exceptions import ForbiddenException, ValidationException
from app.db.session import get_db
from app.models.knowledge_base import KnowledgeBase
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.knowledge_bases import (
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
)
from app.services.knowledge_bases.service import KnowledgeBaseService
from app.services.organizations.service import OrganizationService

router = APIRouter(prefix="/knowledge-bases", tags=["Knowledge Bases"])


@router.post(
    "",
    response_model=KnowledgeBaseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create Knowledge Base",
    description="Creates a new knowledge base in target organization (requires ADMIN or OWNER).",
)
async def create_knowledge_base(
    payload: KnowledgeBaseCreate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    # 1. Resolve Target Organization
    org_id = payload.organization_id
    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise ValidationException(message="User does not belong to any organization.")
        org_id = memberships[0].organization_id

    # 2. Check RBAC (ADMIN or OWNER)
    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException(message="Access denied: You do not belong to this organization.")

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.ADMIN]:
        raise ForbiddenException(
            message="Insufficient permissions: Creating KB requires ADMIN or OWNER role."
        )

    # 3. Create Knowledge Base
    kb = await KnowledgeBaseService.create_knowledge_base(
        session=session,
        organization_id=org_id,
        name=payload.name,
        description=payload.description,
        created_by=current_user.id,
    )
    return KnowledgeBaseResponse.model_validate(kb)


@router.get(
    "",
    response_model=PaginatedResponse[KnowledgeBaseResponse],
    summary="List Knowledge Bases",
    description="Lists knowledge bases in organizations the current user is a member of.",
)
async def list_knowledge_bases(
    limit: int = Query(20, ge=1, le=100, description="Items per page"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    search: str | None = Query(None, description="Search by knowledge base name"),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> PaginatedResponse[KnowledgeBaseResponse]:
    memberships = await OrganizationService.get_user_memberships(session, current_user.id)
    org_ids = [m.organization_id for m in memberships]

    items, total = await KnowledgeBaseService.list_knowledge_bases(
        session=session,
        organization_ids=org_ids,
        limit=limit,
        offset=offset,
        search=search,
    )

    return PaginatedResponse(
        items=[KnowledgeBaseResponse.model_validate(kb) for kb in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="Get Knowledge Base",
    description="Retrieves knowledge base details if user is a member of the owning organization.",
)
async def get_knowledge_base(
    kb_and_membership: tuple[KnowledgeBase, OrganizationMembership] = Depends(
        get_knowledge_base_or_404
    ),
) -> KnowledgeBaseResponse:
    kb, _ = kb_and_membership
    return KnowledgeBaseResponse.model_validate(kb)


@router.patch(
    "/{kb_id}",
    response_model=KnowledgeBaseResponse,
    summary="Update Knowledge Base",
    description="Updates knowledge base metadata (requires ADMIN or OWNER role).",
)
async def update_knowledge_base(
    payload: KnowledgeBaseUpdate,
    kb_and_membership: tuple[KnowledgeBase, OrganizationMembership] = Depends(
        get_knowledge_base_or_404
    ),
    session: AsyncSession = Depends(get_db),
) -> KnowledgeBaseResponse:
    kb, membership = kb_and_membership

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.ADMIN]:
        raise ForbiddenException(
            message="Insufficient permissions: Updating KB requires ADMIN or OWNER role."
        )

    updated_kb = await KnowledgeBaseService.update_knowledge_base(
        session=session,
        kb=kb,
        name=payload.name,
        description=payload.description,
        is_active=payload.is_active,
    )
    return KnowledgeBaseResponse.model_validate(updated_kb)


@router.delete(
    "/{kb_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete Knowledge Base",
    description="Deletes a knowledge base and cascades to documents (requires OWNER role).",
)
async def delete_knowledge_base(
    kb_and_membership: tuple[KnowledgeBase, OrganizationMembership] = Depends(
        get_knowledge_base_or_404
    ),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    kb, membership = kb_and_membership

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.OWNER]:
        raise ForbiddenException(
            message="Insufficient permissions: Deleting knowledge base requires OWNER role."
        )

    await KnowledgeBaseService.delete_knowledge_base(session, kb)
    return {"message": "Knowledge base deleted successfully."}
