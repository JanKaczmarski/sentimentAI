"""API integration tests using the application composition root."""

from fastapi.testclient import TestClient

from sentiment_system.bootstrap.container import ApplicationContainer
from sentiment_system.bootstrap.main import create_app


def test_app_exposes_health_and_retains_its_injected_container() -> None:
    container = ApplicationContainer()
    app = create_app(container=container)

    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert app.state.container is container
