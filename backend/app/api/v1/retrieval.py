from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ROLE_HIERARCHY, get_current_active_user
from app.core.exceptions import ForbiddenException, ValidationException
from app.db.session import get_db
from app.models.membership import OrganizationRole
from app.models.user import User
from app.services.knowledge_bases.service import KnowledgeBaseService
from app.services.organizations.service import OrganizationService
from app.services.retrieval.schemas import RetrievalRequest, RetrievalResponse
from app.services.retrieval.service import RetrievalService

router = APIRouter(prefix="/retrieval", tags=["Retrieval Engine & Hybrid Search"])


@router.post(
    "/search",
    response_model=RetrievalResponse,
    status_code=status.HTTP_200_OK,
    summary="Search & Retrieve Document Chunks",
    description=(
        "Executes multi-tenant semantic vector search, PostgreSQL full-text search, "
        "or Reciprocal Rank Fusion (RRF) hybrid retrieval over document chunks with "
        "metadata filtering."
    ),
)
async def search(
    payload: RetrievalRequest,
    x_organization_id: str | None = Header(
        default=None,
        alias="X-Organization-ID",
        description="Explicit target Organization ID for multi-tenant isolation.",
    ),
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> RetrievalResponse:
    # 1. Resolve Target Organization ID
    org_id = x_organization_id

    if not org_id and payload.knowledge_base_ids:
        # Resolve from first KB
        kb = await KnowledgeBaseService.get_by_id(session, payload.knowledge_base_ids[0])
        org_id = kb.organization_id

    if not org_id:
        memberships = await OrganizationService.get_user_memberships(session, current_user.id)
        if not memberships:
            raise ValidationException(message="User does not belong to any organization.")
        org_id = memberships[0].organization_id

    # 2. Enforce Multi-Tenant Isolation and RBAC (MEMBER, ADMIN, or OWNER)
    membership = await OrganizationService.get_membership(session, org_id, current_user.id)
    if membership is None:
        raise ForbiddenException(message="Access denied: You do not belong to this organization.")

    user_level = ROLE_HIERARCHY.get(membership.role, 0)
    if user_level < ROLE_HIERARCHY[OrganizationRole.MEMBER]:
        raise ForbiddenException(
            message="Insufficient permissions: Retrieval requires at least MEMBER role."
        )

    # 3. Execute Retrieval
    return await RetrievalService.search(
        session=session,
        organization_id=org_id,
        request=payload,
    )
