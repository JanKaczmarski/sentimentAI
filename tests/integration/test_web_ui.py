"""Integration tests for the local browser testing UI."""

import re

from bs4 import BeautifulSoup
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
    assert 'class="terminal-header"' in page.text
    assert 'class="terminal-layout"' in page.text
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
    for ticker in ("META", "CRM", "V", "DIS", "WHR", "T", "AMAT"):
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
    assert "--terminal-lime" in stylesheet.text


def test_terminal_preserves_current_company_selection_and_form_bindings() -> None:
    client = TestClient(create_app(container=ApplicationContainer()))
    page = BeautifulSoup(client.get("/ui/").text, "html.parser")
    script = client.get("/ui/app.js").text
    companies = ("META", "CRM", "V", "DIS", "WHR", "T", "AMAT")

    assert page.select_one("#batch-company")["value"] == "META"
    assert tuple(option["value"] for option in page.select("#research-companies option")) == companies
    assert tuple(ticker.get_text() for ticker in page.select(".terminal-ticker strong")) == companies

    ids = [element["id"] for element in page.select("[id]")]
    assert len(ids) == len(set(ids)), "Each script binding must resolve to a unique element"
    for element_id in re.findall(r'querySelector\("#([^"]+)"\)', script):
        assert page.select_one(f"#{element_id}") is not None, element_id

    for form_id, control_ids in {
        "account-form": ("account-email", "account-username"),
        "thesis-form": (
            "thesis-companies",
            "risk-tolerance",
            "investment-horizon",
            "investment-style",
            "thesis-description",
            "thesis-submit",
            "cancel-edit",
        ),
        "batch-form": ("batch-company", "batch-as-of", "batch-submit"),
    }.items():
        form = page.select_one(f"#{form_id}")
        assert form.find_parent("form") is None
        for control_id in control_ids:
            assert page.select_one(f"#{control_id}").find_parent("form") is form, control_id

    assert page.select_one("#prediction-card").has_attr("hidden")
    assert not page.select_one("#prediction-placeholder").has_attr("hidden")
    assert page.select_one("#api-key-panel").has_attr("hidden")


def test_ui_serves_interface_studies() -> None:
    app = create_app(container=ApplicationContainer())
    client = TestClient(app)

    gallery = client.get("/ui/sketches/")
    stylesheet = client.get("/ui/sketches/sketches.css")

    assert gallery.status_code == 200
    assert 'href="analyst-dossier.html"' in gallery.text
    assert 'href="market-terminal.html"' in gallery.text
    assert 'href="signal-journal.html"' in gallery.text
    assert stylesheet.status_code == 200
    for study in ("analyst-dossier", "market-terminal", "signal-journal"):
        page = client.get(f"/ui/sketches/{study}.html")
        assert page.status_code == 200
        assert 'href="sketches.css"' in page.text
