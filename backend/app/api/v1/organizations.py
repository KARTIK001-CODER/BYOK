from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    get_current_active_user,
    require_organization_membership,
    require_role,
)
from app.db.session import get_db
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.schemas.organizations import (
    MembershipResponse,
    OrganizationCreate,
    OrganizationResponse,
)
from app.services.organizations.service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["Organizations & Multi-Tenancy"])


@router.get(
    "",
    response_model=list[MembershipResponse],
    summary="List User Organizations",
    description="Returns all organizations the authenticated user is a member of.",
)
async def list_user_organizations(
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> list[MembershipResponse]:
    memberships = await OrganizationService.get_user_memberships(session, current_user.id)
    return [MembershipResponse.model_validate(m) for m in memberships]


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create New Organization",
    description="Creates a new tenant organization with the authenticated user as OWNER.",
)
async def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(get_current_active_user),
    session: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    org = await OrganizationService.create_organization(
        session=session,
        name=payload.name,
        slug=payload.slug,
    )
    await OrganizationService.create_membership(
        session=session,
        organization_id=org.id,
        user_id=current_user.id,
        role=OrganizationRole.OWNER,
    )
    await session.commit()
    await session.refresh(org)
    return OrganizationResponse.model_validate(org)


@router.get(
    "/{org_id}",
    response_model=OrganizationResponse,
    summary="Get Organization Details",
    description="Retrieves organization details. Enforces tenant isolation server-side.",
)
async def get_organization(
    org_id: str,
    _membership: OrganizationMembership = Depends(require_organization_membership),
    session: AsyncSession = Depends(get_db),
) -> OrganizationResponse:
    org = await OrganizationService.get_by_id(session, org_id)
    return OrganizationResponse.model_validate(org)


@router.get(
    "/{org_id}/admin-only",
    summary="Admin-restricted action",
    description="Protected endpoint verifying RBAC requirement: ADMIN or OWNER role required.",
)
async def admin_only_action(
    org_id: str,
    membership: OrganizationMembership = Depends(require_role(OrganizationRole.ADMIN)),
) -> dict[str, str]:
    return {
        "message": f"Admin action authorized for organization {org_id}.",
        "user_role": membership.role.value,
    }


@router.get(
    "/{org_id}/owner-only",
    summary="Owner-restricted action",
    description="Protected endpoint verifying RBAC requirement: OWNER role required.",
)
async def owner_only_action(
    org_id: str,
    membership: OrganizationMembership = Depends(require_role(OrganizationRole.OWNER)),
) -> dict[str, str]:
    return {
        "message": f"Owner action authorized for organization {org_id}.",
        "user_role": membership.role.value,
    }
