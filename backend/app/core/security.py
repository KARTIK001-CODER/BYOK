import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedException

# Initialize Argon2id password hasher
_ph = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id."""
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, Exception):
        return False


def create_access_token(
    user_id: str,
    expires_delta: timedelta | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Claims:
        - sub: User UUID
        - type: "access"
        - jti: Unique Token ID
        - iat: Issued at UTC timestamp
        - exp: Expiration UTC timestamp
    """
    settings = get_settings()
    now = datetime.now(UTC)

    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    payload: dict[str, Any] = {
        "sub": user_id,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }

    token = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return token


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Decode and validate a JWT access token.

    Raises:
        UnauthorizedException: If token is expired, invalid, or malformed.
    """
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )

        if payload.get("type") != "access":
            raise UnauthorizedException(message="Invalid token type")

        return payload
    except jwt.ExpiredSignatureError:
        raise UnauthorizedException(message="Access token has expired") from None
    except jwt.PyJWTError:
        raise UnauthorizedException(message="Could not validate credentials") from None


def generate_refresh_token() -> tuple[str, str]:
    """
    Generate a cryptographically secure random refresh token.

    Returns:
        tuple[raw_token, token_hash]
    """
    raw_token = secrets.token_urlsafe(64)
    token_hash = hash_refresh_token(raw_token)
    return raw_token, token_hash


def hash_refresh_token(raw_token: str) -> str:
    """Calculate the SHA-256 hash of a raw refresh token string."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
