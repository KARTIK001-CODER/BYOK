import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

logger = logging.getLogger("app.services.users")


def normalize_email(email: str) -> str:
    """Normalize email to lowercase stripped string."""
    return email.strip().lower()


class UserService:
    """Service handling user account operations."""

    @staticmethod
    async def get_by_email(session: AsyncSession, email: str) -> User | None:
        """Fetch user by normalized email."""
        norm_email = normalize_email(email)
        stmt = select(User).where(User.email == norm_email)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(session: AsyncSession, user_id: str) -> User | None:
        """Fetch user by UUID primary key."""
        stmt = select(User).where(User.id == user_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    async def create(
        session: AsyncSession,
        email: str,
        password_hash: str,
        full_name: str,
    ) -> User:
        """Create a new user record in the active session."""
        norm_email = normalize_email(email)
        user = User(
            email=norm_email,
            password_hash=password_hash,
            full_name=full_name.strip(),
            is_active=True,
            is_verified=False,
        )
        session.add(user)
        await session.flush()
        logger.info("Created user id=%s with email=%s", user.id, user.email)
        return user

    @staticmethod
    async def update_last_login(session: AsyncSession, user_id: str) -> None:
        """Update last login timestamp."""
        now = datetime.now(UTC)
        stmt = update(User).where(User.id == user_id).values(last_login_at=now)
        await session.execute(stmt)
