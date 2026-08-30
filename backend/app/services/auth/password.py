from app.core.exceptions import ValidationException
from app.core.security import hash_password, verify_password


class PasswordService:
    """Password hashing and validation service."""

    @staticmethod
    def validate_password_strength(password: str) -> None:
        """Enforce password security policy."""
        if not password or len(password) < 8:
            raise ValidationException(message="Password must be at least 8 characters long.")

    @staticmethod
    def hash(password: str) -> str:
        """Validate and hash password using Argon2id."""
        PasswordService.validate_password_strength(password)
        return hash_password(password)

    @staticmethod
    def verify(password: str, password_hash: str) -> bool:
        """Verify plaintext password against stored hash."""
        return verify_password(password, password_hash)
