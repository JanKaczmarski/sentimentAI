"""Investor account entities and identity normalization."""

from dataclasses import dataclass
from string import hexdigits
from uuid import UUID


@dataclass(frozen=True, slots=True)
class UserAccount:
    """An investor account with a one-way API-key digest."""

    user_id: UUID
    email: str
    username: str
    api_key_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.user_id, UUID):
            raise ValueError("user_id must be a UUID")
        if self.email != normalize_email(self.email):
            raise ValueError("email must be normalized")
        if self.username != normalize_username(self.username):
            raise ValueError("username must be normalized")
        if not _is_sha256_digest(self.api_key_digest):
            raise ValueError("api_key_digest must be a SHA-256 digest")


def normalize_email(email: str) -> str:
    """Return the canonical account email address."""
    if not isinstance(email, str):
        raise ValueError("email is required")

    normalized = email.strip().casefold()
    if normalized.count("@") != 1:
        raise ValueError("email must be an email address")

    local_part, domain = normalized.split("@")
    if not local_part or not domain:
        raise ValueError("email must be an email address")
    return normalized


def normalize_username(username: str) -> str:
    """Return the canonical account username."""
    if not isinstance(username, str):
        raise ValueError("username is required")

    normalized = username.strip()
    if not normalized:
        raise ValueError("username is required")
    return normalized


def _is_sha256_digest(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(character in hexdigits for character in value)
