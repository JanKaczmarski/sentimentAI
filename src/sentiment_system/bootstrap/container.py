"""Composition root that wires ports to concrete adapters."""

from dataclasses import dataclass

from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryUserAccountRepository
from sentiment_system.application.ports.repositories import UserAccountRepository
from sentiment_system.application.use_cases.create_account import CreateAccount


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Runtime services supplied to inbound adapters by the composition root."""

    account_repository: UserAccountRepository | None = None
    create_account: CreateAccount | None = None


def build_container() -> ApplicationContainer:
    """Build the runtime service container.

    Services are added here as their application use cases are implemented.
    """
    account_repository = InMemoryUserAccountRepository()
    return ApplicationContainer(
        account_repository=account_repository,
        create_account=CreateAccount(account_repository),
    )
