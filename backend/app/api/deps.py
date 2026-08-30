from collections.abc import Callable

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.membership import OrganizationMembership, OrganizationRole
from app.models.user import User
from app.services.organizations.service import OrganizationService
from app.services.users.service import UserService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

ROLE_HIERARCHY = {
    OrganizationRole.OWNER: 3,
    OrganizationRole.ADMIN: 2,
    OrganizationRole.MEMBER: 1,
}


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate JWT access token to retrieve current user."""
    payload = decode_access_token(token)
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise UnauthorizedException(message="Invalid token payload.")

    user = await UserService.get_by_id(session, user_id)
    if user is None:
        raise UnauthorizedException(message="User not found.")

    if not user.is_active:
        raise UnauthorizedException(message="User account is inactive.")

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Dependency ensuring user is active."""
    return current_user


async def require_organization_membership(
    org_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> OrganizationMembership:
    """
    Verify current user has valid membership in target organization.
    Enforces multi-tenant isolation.
    """
    membership = await OrganizationService.get_membership(
        session=session,
        organization_id=org_id,
        user_id=current_user.id,
    )
    if membership is None:
        # Prevent information leakage by returning 404 or 403
        raise ForbiddenException(
            message="Access denied: You are not a member of this organization."
        )
    return membership


def require_role(min_role: OrganizationRole) -> Callable:
    """
    Factory dependency for role-based access control (RBAC).
    Ensures user's role satisfies minimum hierarchy requirement: OWNER > ADMIN > MEMBER.
    """

    async def role_checker(
        membership: OrganizationMembership = Depends(require_organization_membership),
    ) -> OrganizationMembership:
        user_level = ROLE_HIERARCHY.get(membership.role, 0)
        required_level = ROLE_HIERARCHY.get(min_role, 0)

        if user_level < required_level:
            raise ForbiddenException(
                message=f"Insufficient permissions: Requires {min_role.value} role."
            )
        return membership

    return role_checker
