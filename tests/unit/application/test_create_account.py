"""Tests for account creation orchestration."""

from hashlib import sha256
from uuid import UUID

import pytest

from sentiment_system.application.use_cases.create_account import (
    AccountEmailInUseError,
    AccountUsernameInUseError,
    CreateAccount,
)
from sentiment_system.domain.accounts import UserAccount


class StubUserAccountRepository:
    """Minimal account repository substitute for application-unit tests."""

    def __init__(self, accounts: tuple[UserAccount, ...] = ()) -> None:
        self.accounts = list(accounts)

    def save(self, account: UserAccount) -> None:
        self.accounts.append(account)

    def get_by_email(self, email: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.email == email), None)

    def get_by_username(self, username: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.username == username), None)

    def get_by_api_key_digest(self, api_key_digest: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.api_key_digest == api_key_digest), None)


def test_create_account_normalizes_identity_and_returns_raw_key_only_in_result() -> None:
    repository = StubUserAccountRepository()
    create_account = CreateAccount(
        repository,
        user_id_factory=lambda: UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
        api_key_factory=lambda: "raw-api-key",
    )

    result = create_account.execute(email=" Investor@Example.com ", username=" investor ")

    assert result.user_id == UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624")
    assert result.api_key == "raw-api-key"
    assert repository.accounts == [
        UserAccount(
            user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
            email="investor@example.com",
            username="investor",
            api_key_digest=sha256(b"raw-api-key").hexdigest(),
        )
    ]
    assert not hasattr(repository.accounts[0], "api_key")
    assert "raw-api-key" not in repr(repository.accounts[0])


@pytest.mark.parametrize(
    ("email", "username", "expected_error"),
    [
        ("investor@example.com", "different", AccountEmailInUseError),
        ("different@example.com", "investor", AccountUsernameInUseError),
    ],
)
def test_create_account_rejects_duplicate_identity(email: str, username: str, expected_error: type[Exception]) -> None:
    account = UserAccount(
        user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
        email="investor@example.com",
        username="investor",
        api_key_digest=sha256(b"existing-api-key").hexdigest(),
    )
    create_account = CreateAccount(StubUserAccountRepository((account,)))

    with pytest.raises(expected_error):
        create_account.execute(email=email, username=username)
