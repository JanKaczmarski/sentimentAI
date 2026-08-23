"""Composition root that wires ports to concrete adapters."""

from dataclasses import dataclass

from sentiment_system.application.use_cases.create_account import CreateAccount


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Runtime services supplied to inbound adapters by the composition root."""

    create_account: CreateAccount | None = None


def build_container() -> ApplicationContainer:
    """Build the runtime service container.

    Services are added here as their application use cases are implemented.
    """
    return ApplicationContainer()
