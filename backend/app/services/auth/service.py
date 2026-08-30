import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import ConflictException, UnauthorizedException
from app.core.security import create_access_token
from app.models.membership import OrganizationRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.auth import LoginRequest, RegisterRequest
from app.services.auth.password import PasswordService
from app.services.auth.tokens import TokenService
from app.services.organizations.service import OrganizationService
from app.services.users.service import UserService

logger = logging.getLogger("app.services.auth")


class AuthService:
    """High-level authentication workflows orchestrating users, orgs, and tokens."""

    @staticmethod
    async def register(
        session: AsyncSession,
        payload: RegisterRequest,
    ) -> tuple[User, Organization, str, str, int]:
        """
        Register a new user, create their default workspace, assign OWNER role,
        and issue initial JWT access & rotating refresh tokens within a single transaction.
        """
        settings = get_settings()

        # 1. Check for duplicate email
        existing_user = await UserService.get_by_email(session, payload.email)
        if existing_user is not None:
            raise ConflictException(message="A user with this email already exists.")

        # 2. Hash password with Argon2id
        password_hash = PasswordService.hash(payload.password)

        # 3. Create User record
        user = await UserService.create(
            session=session,
            email=payload.email,
            password_hash=password_hash,
            full_name=payload.full_name,
        )

        # 4. Determine default organization name
        org_name = payload.organization_name or f"{user.full_name}'s Workspace"

        # 5. Create default Organization with unique slug
        org = await OrganizationService.create_organization(
            session=session,
            name=org_name,
        )

        # 6. Assign user as OWNER of the new organization
        await OrganizationService.create_membership(
            session=session,
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
        )

        # 7. Generate initial refresh and access tokens
        raw_refresh_token, _ = await TokenService.create_refresh_token(
            session=session,
            user_id=user.id,
        )
        access_token = create_access_token(user_id=user.id)
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        # Commit atomic registration transaction
        await session.commit()
        await session.refresh(user)
        await session.refresh(org)

        logger.info(
            "Completed registration for user_id=%s with default org_id=%s",
            user.id,
            org.id,
        )
        return user, org, access_token, raw_refresh_token, expires_in

    @staticmethod
    async def login(
        session: AsyncSession,
        payload: LoginRequest,
    ) -> tuple[User, str, str, int]:
        """
        Authenticate user credentials and issue new tokens.
        Uses generic error messaging to protect against user enumeration.
        """
        settings = get_settings()

        # 1. Look up user by normalized email
        user = await UserService.get_by_email(session, payload.email)
        if user is None:
            raise UnauthorizedException(message="Invalid email or password.")

        # 2. Verify password with constant-time comparison
        if not PasswordService.verify(payload.password, user.password_hash):
            raise UnauthorizedException(message="Invalid email or password.")

        # 3. Verify user active status
        if not user.is_active:
            raise UnauthorizedException(message="User account is inactive.")

        # 4. Update last login timestamp
        await UserService.update_last_login(session, user.id)

        # 5. Issue tokens
        raw_refresh_token, _ = await TokenService.create_refresh_token(
            session=session,
            user_id=user.id,
        )
        access_token = create_access_token(user_id=user.id)
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        await session.commit()
        await session.refresh(user)

        logger.info("Successful login for user_id=%s", user.id)
        return user, access_token, raw_refresh_token, expires_in

    @staticmethod
    async def refresh_tokens(
        session: AsyncSession,
        raw_refresh_token: str,
    ) -> tuple[str, str, int]:
        """Rotate refresh token and issue a fresh access token."""
        return await TokenService.rotate_refresh_token(session, raw_refresh_token)

    @staticmethod
    async def logout(
        session: AsyncSession,
        raw_refresh_token: str,
    ) -> bool:
        """Revoke user refresh token."""
        return await TokenService.revoke_refresh_token(session, raw_refresh_token)
