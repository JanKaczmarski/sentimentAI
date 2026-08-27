"""Integration tests for the local browser testing UI."""

from fastapi.testclient import TestClient

from sentiment_system.bootstrap.container import ApplicationContainer
from sentiment_system.bootstrap.main import create_app


def test_ui_serves_page_and_same_origin_assets() -> None:
    app = create_app(container=ApplicationContainer())
    client = TestClient(app)

    redirect = client.get("/ui", follow_redirects=False)
    page = client.get("/ui/")
    script = client.get("/ui/app.js")
    stylesheet = client.get("/ui/styles.css")

    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/ui/"
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert 'id="account-form"' in page.text
    assert 'src="/ui/app.js"' in page.text
    assert script.status_code == 200
    assert "sessionStorage" in script.text
    assert "/user/account" in script.text
    assert "/user/strategy" in script.text
    assert "/user/strategy/" in script.text
    assert 'id="batch-form"' in page.text
    assert 'id="batch-company"' in page.text
    assert 'id="research-companies"' in page.text
    for ticker in ("AAPL", "MSFT", "NVDA", "JPM", "XOM", "JNJ", "AMAT"):
        assert f'value="{ticker}"' in page.text
    assert 'id="batch-as-of"' in page.text
    assert 'id="prediction-card"' in page.text
    assert "/batch/run" in script.text
    assert "/companies/" in script.text
    assert "renderPrediction" in script.text
    assert "Show more" in script.text
    assert "Show less" in script.text
    assert "slice(0, 5)" in script.text
    assert "sentiment.label" in script.text
    assert 'classList.toggle("ready"' in script.text
    assert stylesheet.status_code == 200
    assert "--ink" in stylesheet.text
