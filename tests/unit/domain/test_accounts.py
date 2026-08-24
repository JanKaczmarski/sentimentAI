"""Tests for investor account domain entities."""

from hashlib import sha256
from uuid import UUID

import pytest

from sentiment_system.domain.accounts import UserAccount


def test_user_account_preserves_normalized_identity_and_api_key_digest() -> None:
    account = UserAccount(
        user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
        email="investor@example.com",
        username="investor",
        api_key_digest=sha256(b"raw-api-key").hexdigest(),
    )

    assert account.email == "investor@example.com"
    assert account.username == "investor"
    assert account.api_key_digest == sha256(b"raw-api-key").hexdigest()


@pytest.mark.parametrize(
    ("email", "username", "api_key_digest"),
    [
        ("Investor@Example.com", "investor", sha256(b"raw-api-key").hexdigest()),
        ("investor@example.com", " investor ", sha256(b"raw-api-key").hexdigest()),
        ("investor@example.com", "investor", "not-a-digest"),
    ],
)
def test_user_account_rejects_non_canonical_or_invalid_values(email: str, username: str, api_key_digest: str) -> None:
    with pytest.raises(ValueError):
        UserAccount(
            user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
            email=email,
            username=username,
            api_key_digest=api_key_digest,
        )
