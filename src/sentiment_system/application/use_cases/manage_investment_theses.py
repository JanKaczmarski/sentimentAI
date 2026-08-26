"""Use case for authenticated Investment Thesis CRUD."""

from hashlib import sha256
from typing import Callable
from uuid import uuid4

from sentiment_system.application.ports.repositories import InvestmentThesisRepository, UserAccountRepository
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.companies import APPROVED_COMPANY_REGISTRY, CompanyRegistry
from sentiment_system.domain.investment_thesis import (
    InvestmentHorizon,
    InvestmentStyle,
    InvestmentThesis,
    RiskTolerance,
)


class AccountNotFoundError(Exception):
    """Raised when an API key does not identify an account."""


class ThesisNotFoundError(Exception):
    """Raised when a user cannot access the requested thesis."""


class UnsupportedCompanyError(Exception):
    """Raised when a thesis contains a ticker outside the approved registry."""


class ManageInvestmentTheses:
    """Create, update, and retrieve one account's structured theses."""

    def __init__(
        self,
        accounts: UserAccountRepository,
        theses: InvestmentThesisRepository,
        *,
        registry: CompanyRegistry = APPROVED_COMPANY_REGISTRY,
        thesis_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._accounts = accounts
        self._theses = theses
        self._registry = registry
        self._thesis_id_factory = thesis_id_factory

    def create(
        self,
        *,
        api_key: str,
        companies: tuple[str, ...],
        risk_tolerance: RiskTolerance,
        investment_horizon: InvestmentHorizon,
        investment_style: InvestmentStyle,
        description: str | None,
    ) -> InvestmentThesis:
        """Create a registry-validated thesis for the account identified by its key."""
        account = self._account_for_api_key(api_key)
        thesis = self._new_thesis(
            thesis_id=self._thesis_id_factory(),
            user_id=str(account.user_id),
            companies=companies,
            risk_tolerance=risk_tolerance,
            investment_horizon=investment_horizon,
            investment_style=investment_style,
            description=description,
        )
        self._theses.save(thesis)
        return thesis

    def update(
        self,
        *,
        api_key: str,
        thesis_id: str,
        companies: tuple[str, ...],
        risk_tolerance: RiskTolerance,
        investment_horizon: InvestmentHorizon,
        investment_style: InvestmentStyle,
        description: str | None,
    ) -> InvestmentThesis:
        """Replace one account-owned thesis without changing its stable identifier."""
        account = self._account_for_api_key(api_key)
        self._owned_thesis(thesis_id, str(account.user_id))
        thesis = self._new_thesis(
            thesis_id=thesis_id,
            user_id=str(account.user_id),
            companies=companies,
            risk_tolerance=risk_tolerance,
            investment_horizon=investment_horizon,
            investment_style=investment_style,
            description=description,
        )
        self._theses.save(thesis)
        return thesis

    def list_for_user(self, *, api_key: str) -> tuple[InvestmentThesis, ...]:
        """List the authenticated account's theses in repository-defined order."""
        account = self._account_for_api_key(api_key)
        return self._theses.list_for_user(str(account.user_id))

    def list_for_company(self, *, api_key: str, company: str) -> tuple[InvestmentThesis, ...]:
        """List the authenticated account's theses that include one approved company."""
        account = self._account_for_api_key(api_key)
        ticker = self._ticker(company)
        return tuple(
            thesis for thesis in self._theses.list_for_user(str(account.user_id)) if ticker in thesis.companies
        )

    def _account_for_api_key(self, api_key: str) -> UserAccount:
        digest = sha256(api_key.encode("utf-8")).hexdigest()
        account = self._accounts.get_by_api_key_digest(digest)
        if account is None:
            raise AccountNotFoundError("account not found")
        return account

    def _owned_thesis(self, thesis_id: str, user_id: str) -> InvestmentThesis:
        thesis = self._theses.get(thesis_id)
        if thesis is None or thesis.user_id != user_id:
            raise ThesisNotFoundError("thesis not found")
        return thesis

    def _new_thesis(
        self,
        *,
        thesis_id: str,
        user_id: str,
        companies: tuple[str, ...],
        risk_tolerance: RiskTolerance,
        investment_horizon: InvestmentHorizon,
        investment_style: InvestmentStyle,
        description: str | None,
    ) -> InvestmentThesis:
        return InvestmentThesis(
            thesis_id=thesis_id,
            user_id=user_id,
            companies=tuple(self._ticker(company) for company in companies),
            risk_tolerance=risk_tolerance,
            investment_horizon=investment_horizon,
            investment_style=investment_style,
            description=description,
        )

    def _ticker(self, company: str) -> str:
        try:
            return self._registry.lookup(company).ticker
        except ValueError as error:
            raise UnsupportedCompanyError(str(error)) from error
