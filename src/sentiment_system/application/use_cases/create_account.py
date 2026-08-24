"""Use case for creating unauthenticated investor accounts."""

from dataclasses import dataclass
from hashlib import sha256
from secrets import token_urlsafe
from typing import Callable
from uuid import UUID, uuid4

from sentiment_system.application.ports.repositories import UserAccountRepository
from sentiment_system.domain.accounts import UserAccount, normalize_email, normalize_username


class AccountEmailInUseError(Exception):
    """Raised when an email address already belongs to an account."""


class AccountUsernameInUseError(Exception):
    """Raised when a username already belongs to an account."""


@dataclass(frozen=True, slots=True)
class CreatedAccount:
    """The only result that includes the newly generated raw API key."""

    user_id: UUID
    api_key: str


class CreateAccount:
    """Create an account after enforcing its unique identity fields."""

    def __init__(
        self,
        repository: UserAccountRepository,
        *,
        user_id_factory: Callable[[], UUID] = uuid4,
        api_key_factory: Callable[[], str] = lambda: token_urlsafe(32),
    ) -> None:
        self._repository = repository
        self._user_id_factory = user_id_factory
        self._api_key_factory = api_key_factory

    def execute(self, *, email: str, username: str) -> CreatedAccount:
        """Create and persist an account, returning its raw key exactly once."""
        normalized_email = normalize_email(email)
        normalized_username = normalize_username(username)

        if self._repository.get_by_email(normalized_email) is not None:
            raise AccountEmailInUseError("email in use")
        if self._repository.get_by_username(normalized_username) is not None:
            raise AccountUsernameInUseError("username in use")

        api_key = self._api_key_factory()
        account = UserAccount(
            user_id=self._user_id_factory(),
            email=normalized_email,
            username=normalized_username,
            api_key_digest=sha256(api_key.encode("utf-8")).hexdigest(),
        )
        self._repository.save(account)
        return CreatedAccount(user_id=account.user_id, api_key=api_key)
