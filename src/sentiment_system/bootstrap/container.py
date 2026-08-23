"""Composition root that wires ports to concrete adapters."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApplicationContainer:
    """Runtime services supplied to inbound adapters by the composition root."""


def build_container() -> ApplicationContainer:
    """Build the runtime service container.

    Services are added here as their application use cases are implemented.
    """
    return ApplicationContainer()
