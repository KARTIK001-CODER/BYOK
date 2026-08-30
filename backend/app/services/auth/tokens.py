import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException
from app.core.security import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.models.refresh_token import RefreshToken

logger = logging.getLogger("app.services.auth.tokens")


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime object is timezone-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


class TokenService:
    """Service managing access tokens, refresh tokens, rotation, and reuse detection."""

    @staticmethod
    async def create_refresh_token(
        session: AsyncSession,
        user_id: str,
    ) -> tuple[str, RefreshToken]:
        """Generate and persist a new refresh token hash for a user."""
        settings = get_settings()
        raw_token, token_hash = generate_refresh_token()
        expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        db_token = RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            expires_at=expires_at,
        )
        session.add(db_token)
        await session.flush()
        return raw_token, db_token

    @staticmethod
    async def rotate_refresh_token(
        session: AsyncSession,
        raw_refresh_token: str,
    ) -> tuple[str, str, int]:
        """
        Validate and rotate a refresh token.

        Returns:
            (access_token, new_raw_refresh_token, expires_in_seconds)

        Security:
            If a revoked token is presented, trigger reuse detection:
            Log security event and revoke all active refresh tokens for the user.
        """
        settings = get_settings()
        token_hash = hash_refresh_token(raw_refresh_token)

        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await session.execute(stmt)
        token_record = result.scalar_one_or_none()

        if token_record is None:
            raise UnauthorizedException(message="Invalid refresh token.")

        now = datetime.now(UTC)

        # 1. Check for Token Reuse (Revoked Token Presented)
        if token_record.revoked_at is not None:
            logger.warning(
                "[SECURITY_EVENT] Token reuse detected for user_id=%s. Revoking all tokens.",
                token_record.user_id,
            )
            # Revoke all active tokens for this user as a safeguard
            revoke_all_stmt = (
                update(RefreshToken)
                .where(
                    RefreshToken.user_id == token_record.user_id,
                    RefreshToken.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
            await session.execute(revoke_all_stmt)
            await session.commit()
            raise UnauthorizedException(message="Invalid refresh token. Token reuse detected.")

        # 2. Check Expiration (Timezone safe)
        if ensure_utc(token_record.expires_at) <= now:
            raise UnauthorizedException(message="Refresh token has expired.")

        # 3. Create New Refresh Token & Link Replacement
        new_raw_token, new_db_token = await TokenService.create_refresh_token(
            session=session,
            user_id=token_record.user_id,
        )

        token_record.revoked_at = now
        token_record.replaced_by_token_id = new_db_token.id

        # 4. Generate New Access Token
        access_token = create_access_token(user_id=token_record.user_id)
        expires_in = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

        await session.commit()
        return access_token, new_raw_token, expires_in

    @staticmethod
    async def revoke_refresh_token(
        session: AsyncSession,
        raw_refresh_token: str,
    ) -> bool:
        """Revoke a refresh token on user logout. Idempotent operation."""
        token_hash = hash_refresh_token(raw_refresh_token)
        stmt = select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        result = await session.execute(stmt)
        token_record = result.scalar_one_or_none()

        if token_record and token_record.revoked_at is None:
            token_record.revoked_at = datetime.now(UTC)
            await session.commit()
            logger.info("Revoked refresh token for user_id=%s", token_record.user_id)
            return True
        return False
