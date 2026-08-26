"""Tests for authenticated Investment Thesis CRUD orchestration."""

from hashlib import sha256
from uuid import UUID

import pytest

from sentiment_system.application.use_cases.manage_investment_theses import (
    AccountNotFoundError,
    ManageInvestmentTheses,
    ThesisNotFoundError,
    UnsupportedCompanyError,
)
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.investment_thesis import InvestmentHorizon, InvestmentStyle, RiskTolerance


class StubUserAccountRepository:
    """Minimal account store for application-unit tests."""

    def __init__(self, accounts: tuple[UserAccount, ...]) -> None:
        self.accounts = accounts

    def get_by_api_key_digest(self, api_key_digest: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.api_key_digest == api_key_digest), None)


class StubInvestmentThesisRepository:
    """Minimal thesis store for application-unit tests."""

    def __init__(self) -> None:
        self.theses = {}

    def save(self, thesis: object) -> None:
        self.theses[thesis.thesis_id] = thesis

    def get(self, thesis_id: str) -> object | None:
        return self.theses.get(thesis_id)

    def list_for_user(self, user_id: str) -> tuple[object, ...]:
        return tuple(thesis for thesis in self.theses.values() if thesis.user_id == user_id)


def test_manage_theses_authenticates_and_persists_a_registry_validated_group() -> None:
    account = UserAccount(
        user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
        email="investor@example.com",
        username="investor",
        api_key_digest=sha256(b"api-key").hexdigest(),
    )
    theses = StubInvestmentThesisRepository()
    use_case = ManageInvestmentTheses(
        StubUserAccountRepository((account,)),
        theses,
        thesis_id_factory=lambda: "thesis-1",
    )

    created = use_case.create(
        api_key="api-key",
        companies=(" aapl ", "msft"),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
        description="Prefer durable compounders.",
    )

    assert created.thesis_id == "thesis-1"
    assert created.user_id == str(account.user_id)
    assert created.companies == ("AAPL", "MSFT")
    assert created.description == "Prefer durable compounders."
    assert use_case.list_for_user(api_key="api-key") == (created,)
    assert use_case.list_for_company(api_key="api-key", company="AAPL") == (created,)

    updated = use_case.update(
        api_key="api-key",
        thesis_id="thesis-1",
        companies=("AMD",),
        risk_tolerance=RiskTolerance.HIGH,
        investment_horizon=InvestmentHorizon.SHORT_TERM,
        investment_style=InvestmentStyle.ACTIVE,
        description=None,
    )

    assert updated.thesis_id == "thesis-1"
    assert updated.companies == ("AMD",)
    assert updated.risk_tolerance is RiskTolerance.HIGH
    assert updated.description is None


def test_manage_theses_rejects_unknown_accounts_companies_and_theses() -> None:
    account = UserAccount(
        user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
        email="investor@example.com",
        username="investor",
        api_key_digest=sha256(b"api-key").hexdigest(),
    )
    use_case = ManageInvestmentTheses(StubUserAccountRepository((account,)), StubInvestmentThesisRepository())

    with pytest.raises(AccountNotFoundError):
        use_case.list_for_user(api_key="wrong-key")
    with pytest.raises(UnsupportedCompanyError):
        use_case.list_for_company(api_key="api-key", company="UNKNOWN")
    with pytest.raises(ThesisNotFoundError):
        use_case.update(
            api_key="api-key",
            thesis_id="missing",
            companies=("AAPL",),
            risk_tolerance=RiskTolerance.LOW,
            investment_horizon=InvestmentHorizon.LONG_TERM,
            investment_style=InvestmentStyle.PASSIVE,
            description=None,
        )
