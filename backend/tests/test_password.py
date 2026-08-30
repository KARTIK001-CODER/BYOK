import pytest

from app.core.exceptions import ValidationException
from app.services.auth.password import PasswordService


def test_password_hashing_and_verification() -> None:
    """Verify password hashing generates unique hashes and verifies correctly."""
    password = "SuperSecretPassword123!"
    pwd_hash = PasswordService.hash(password)

    assert pwd_hash != password
    assert pwd_hash.startswith("$argon2id$")
    assert PasswordService.verify(password, pwd_hash) is True
    assert PasswordService.verify("WrongPassword123!", pwd_hash) is False


def test_password_min_length_validation() -> None:
    """Verify passwords shorter than 8 characters are rejected."""
    with pytest.raises(ValidationException):
        PasswordService.hash("short")


def test_password_empty_validation() -> None:
    """Verify empty passwords are rejected."""
    with pytest.raises(ValidationException):
        PasswordService.hash("")
