"""API integration tests using the application composition root."""

import os
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryInvestmentThesisRepository,
    InMemoryUserAccountRepository,
)
from sentiment_system.application.use_cases.create_account import CreateAccount
from sentiment_system.application.use_cases.manage_investment_theses import ManageInvestmentTheses
from sentiment_system.bootstrap.container import ApplicationContainer, build_container
from sentiment_system.bootstrap.main import create_app
from sentiment_system.domain.accounts import UserAccount


class ApiUserAccountRepository:
    """Minimal repository substitute for testing the account HTTP boundary."""

    def __init__(self) -> None:
        self.accounts: list[UserAccount] = []

    def save(self, account: UserAccount) -> None:
        self.accounts.append(account)

    def get_by_email(self, email: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.email == email), None)

    def get_by_username(self, username: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.username == username), None)

    def get_by_api_key_digest(self, api_key_digest: str) -> UserAccount | None:
        return next((account for account in self.accounts if account.api_key_digest == api_key_digest), None)


def test_app_exposes_health_and_retains_its_injected_container() -> None:
    container = ApplicationContainer()
    app = create_app(container=container)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert app.state.container is container


def test_account_endpoint_creates_an_account_and_reports_identity_conflicts() -> None:
    app = create_app(container=ApplicationContainer(create_account=CreateAccount(ApiUserAccountRepository())))
    client = TestClient(app)

    created = client.post(
        "/user/account",
        json={"email": "investor@example.com", "username": "investor"},
    )
    duplicate_email = client.post(
        "/user/account",
        json={"email": "investor@example.com", "username": "different"},
    )
    duplicate_username = client.post(
        "/user/account",
        json={"email": "different@example.com", "username": "investor"},
    )
    invalid_email = client.post(
        "/user/account",
        json={"email": "not-an-email", "username": "valid-user"},
    )

    assert created.status_code == 201
    assert created.json()["status"] == "success"
    assert created.json()["user_id"]
    assert created.json()["api_key"]
    assert duplicate_email.status_code == 409
    assert duplicate_email.json() == {"detail": "email in use"}
    assert duplicate_username.status_code == 409
    assert duplicate_username.json() == {"detail": "username in use"}
    assert invalid_email.status_code == 422


def test_default_app_retains_created_accounts_for_its_process_lifetime() -> None:
    container = build_container()
    client = TestClient(create_app(container=container))

    created = client.post(
        "/user/account",
        json={"email": "investor@example.com", "username": "investor"},
    )
    duplicate = client.post(
        "/user/account",
        json={"email": "investor@example.com", "username": "different"},
    )

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json() == {"detail": "email in use"}
    assert container.account_repository is not None

    account = container.account_repository.get_by_api_key_digest(
        sha256(created.json()["api_key"].encode("utf-8")).hexdigest()
    )

    assert account is not None
    assert str(account.user_id) == created.json()["user_id"]


def test_strategy_endpoints_scope_crud_to_the_account_selected_by_api_key() -> None:
    accounts = InMemoryUserAccountRepository()
    app = create_app(
        container=ApplicationContainer(
            account_repository=accounts,
            create_account=CreateAccount(accounts, api_key_factory=lambda: "api-key"),
            manage_investment_theses=ManageInvestmentTheses(accounts, InMemoryInvestmentThesisRepository()),
        )
    )
    client = TestClient(app)
    account = client.post("/user/account", json={"email": "investor@example.com", "username": "investor"})
    api_key = account.json()["api_key"]
    payload = {
        "companies": ["aapl", "MSFT"],
        "risk_tolerance": "medium",
        "investment_horizon": "long_term",
        "investment_style": "passive",
        "description": "Prefer durable compounders.",
    }

    created = client.post("/user/strategy", params={"api_key": api_key}, json=payload)
    thesis_id = created.json()["thesis_id"]
    listed = client.get("/user/strategy", params={"api_key": api_key})
    by_company = client.get("/user/strategy/AAPL", params={"api_key": api_key})
    updated = client.put(
        f"/user/strategy/{thesis_id}",
        params={"api_key": api_key},
        json={**payload, "companies": ["AMD"], "description": None},
    )
    listed_after_update = client.get("/user/strategy", params={"api_key": api_key})
    missing = client.put("/user/strategy/missing", params={"api_key": api_key}, json=payload)
    invalid = client.post("/user/strategy", params={"api_key": api_key}, json={**payload, "companies": ["UNKNOWN"]})
    unknown_account = client.get("/user/strategy", params={"api_key": "unknown"})

    assert account.status_code == 201
    assert created.status_code == 201
    assert created.json() == {"status": "success", "thesis_id": thesis_id}
    assert listed.status_code == 200
    assert listed.json()["theses"] == [{"thesis_id": thesis_id, **payload, "companies": ["AAPL", "MSFT"]}]
    assert by_company.status_code == 200
    assert by_company.json() == listed.json()
    assert updated.status_code == 200
    assert updated.json() == {"status": "success", "thesis_id": thesis_id}
    assert listed_after_update.status_code == 200
    assert listed_after_update.json()["theses"] == [
        {
            "thesis_id": thesis_id,
            "companies": ["AMD"],
            "risk_tolerance": "medium",
            "investment_horizon": "long_term",
            "investment_style": "passive",
            "description": None,
        }
    ]
    assert missing.status_code == 404
    assert invalid.status_code == 422
    assert unknown_account.status_code == 404


@pytest.mark.integration
def test_postgres_container_wires_account_and_thesis_api(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")

    monkeypatch.setenv("DATABASE_URL", dsn)
    suffix = uuid4().hex
    client = TestClient(create_app(container=build_container()))
    account = client.post(
        "/user/account",
        json={"email": f"{suffix}@example.com", "username": suffix},
    )
    api_key = account.json()["api_key"]
    payload = {
        "companies": ["AAPL", "MSFT"],
        "risk_tolerance": "medium",
        "investment_horizon": "long_term",
        "investment_style": "passive",
        "description": "Persisted explanation.",
    }

    created = client.post("/user/strategy", params={"api_key": api_key}, json=payload)
    thesis_id = created.json()["thesis_id"]
    listed = client.get("/user/strategy", params={"api_key": api_key})
    updated = client.put(
        f"/user/strategy/{thesis_id}",
        params={"api_key": api_key},
        json={**payload, "companies": ["AMD"], "description": None},
    )
    by_company = client.get("/user/strategy/AMD", params={"api_key": api_key})

    assert account.status_code == 201
    assert created.status_code == 201
    assert listed.status_code == 200
    assert listed.json()["theses"][0]["description"] == payload["description"]
    assert updated.status_code == 200
    assert by_company.status_code == 200
    assert by_company.json()["theses"][0]["companies"] == ["AMD"]
