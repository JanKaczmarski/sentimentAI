"""API integration tests using the application composition root."""

from fastapi.testclient import TestClient

from sentiment_system.application.use_cases.create_account import CreateAccount
from sentiment_system.bootstrap.container import ApplicationContainer
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
    client = TestClient(create_app())

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
