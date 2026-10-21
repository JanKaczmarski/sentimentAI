"""Frozen-cache pipeline/API coverage, with optional full real-cache replay."""

import os
from dataclasses import replace
from datetime import date
from hashlib import sha256

import pytest
from fastapi.testclient import TestClient

from scripts.acquire_corpus import write_corpus
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.bootstrap.container import build_container
from sentiment_system.bootstrap.main import create_app
from sentiment_system.domain.research import FINAL_CORPUS_VERSION, RESEARCH_TICKERS
from tests.unit.scripts.test_acquire_corpus import _record


def _development_env(monkeypatch, root):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SENTIMENT_DATA_ROOT", str(root))
    monkeypatch.setenv("LLM_BACKEND", "deterministic")
    monkeypatch.setenv("EMBEDDING_BACKEND", "mock")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("QDRANT_URL", raising=False)


def _investor(client, suffix, style="passive"):
    account = client.post("/user/account", json={"email": f"{suffix}@example.com", "username": suffix}).json()
    response = client.post(
        "/user/strategy",
        params={"api_key": account["api_key"]},
        json={
            "companies": list(RESEARCH_TICKERS),
            "risk_tolerance": "medium",
            "investment_horizon": "long_term",
            "investment_style": style,
        },
    )
    assert response.status_code == 201
    return account


def _assert_predictions(client, container, run, as_of, investors, tickers):
    assert run["source_scope"] == "frozen"
    for investor in investors:
        for ticker in tickers:
            response = client.get(
                f"/companies/{ticker}/prediction",
                params={
                    "api_key": investor["api_key"],
                    "as_of": as_of,
                    "source_scope": "frozen",
                },
            )
            assert response.status_code == 200, response.text
            prediction = response.json()
            assert prediction["run_id"] == run["run_id"]
            assert prediction["user_id"] == investor["user_id"]
            assert prediction["rule_version"] == "aggregation-personalization-v1"
            config = prediction["run_metadata"]["configuration"]
            assert config["source_scope"] == "frozen"
            assert config["source_manifest_version"] == FINAL_CORPUS_VERSION
            assert all(item["published_at"] < as_of for item in prediction["evidence"])
            assert all(container.chunk_repository.get(item["chunk_id"]) for item in prediction["evidence"])
        history = client.get(f"/user/history/{investor['user_id']}", params={"api_key": investor["api_key"]})
        assert history.status_code == 200
        assert len(history.json()["predictions"]) == len(tickers)
        assert all(item["user_id"] == investor["user_id"] for item in history.json()["predictions"])


def test_frozen_cache_through_composed_api_preserves_scope_lineage_and_shared_scoring(
    tmp_path, sector_bundle, monkeypatch
):
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    records = (
        replace(_record(), source_id="prior", published_at=date(2025, 1, 29), content_group_id="META:prior"),
        replace(_record(), source_id="same-day", published_at=date(2025, 1, 30), content_group_id="META:same-day"),
    )
    corpus = write_corpus(tmp_path, records, sector_review_path=review)
    broad = tmp_path / "data/company_communications/curated/AMAT"
    broad.mkdir(parents=True)
    text = "Revenue increased. Costs declined."
    (broad / "remarks.txt").write_text(text)
    (broad / "manifest.csv").write_text(
        "canonical_filename,ticker,published_at,document_type,sha256\n"
        f"remarks.txt,AMAT,2025-01-29,earnings_call_prepared_remarks,{sha256(text.encode()).hexdigest()}\n"
    )
    _development_env(monkeypatch, tmp_path)
    container = build_container()
    client = TestClient(create_app(container=container))
    investors = (_investor(client, "passive"), _investor(client, "active", "active"))
    calls = 0
    scorer = container.run_batch._scoring._scorer
    original = scorer.score_chunk

    def count(chunk, *, context=""):
        nonlocal calls
        calls += 1
        return original(chunk, context=context)

    monkeypatch.setattr(scorer, "score_chunk", count)
    response = client.post("/batch/run", json={"company": "META", "as_of": "2025-01-30", "source_scope": "frozen"})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["document_count"] == run["scored_chunk_count"] == 1
    assert run["snapshot_count"] == 3
    _assert_predictions(client, container, run, "2025-01-30", investors, ("META",))
    assert calls == 1
    audit = container.provenance_repository.get(run["run_id"])
    assert audit.input_version == FINAL_CORPUS_VERSION
    assert (
        audit.processing_config["source_manifest_sha256"] == sha256((corpus / "manifest.json").read_bytes()).hexdigest()
    )
    assert {source["source_id"] for source in audit.processing_config["source_lineage"]} == {"prior"}
    assert audit.thesis_parameters == {}
    assert audit.model_name == "deterministic-sha256-v1"
    assert audit.processing_config["embedding"]["model"] == "deterministic-sha256-v1"
    assert (
        container.run_batch.execute(company="AMAT", as_of=date(2025, 1, 30), source_scope="frozen").document_count == 0
    )
    assert container.run_batch.execute(company="AMAT", as_of=date(2025, 1, 30)).document_count == 1
    assert client.post("/batch/run", json={"source_scope": "all-cache"}).status_code == 422


def test_frozen_request_without_a_manifest_records_failure_instead_of_using_fixtures(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMBEDDING_BACKEND", "mock")
    monkeypatch.setenv("LLM_BACKEND", "deterministic")
    for key in ("DATABASE_URL", "QDRANT_URL", "SENTIMENT_DATA_ROOT"):
        monkeypatch.delenv(key, raising=False)
    container = build_container()
    client = TestClient(create_app(container=container))
    response = client.post("/batch/run", json={"company": "META", "as_of": "2025-01-30", "source_scope": "frozen"})
    assert response.status_code == 500
    run = container.experiment_run_repository.list_runs()[0]
    assert run.status == "failed"
    assert run.configuration["source_scope"] == "frozen"
    assert container.document_repository.list_documents() == ()
    assert container.provenance_repository.get(run.run_id).processing_config["failed_stage"] == "ingestion"


@pytest.mark.integration
def test_complete_real_frozen_corpus_replays_to_predictions_offline(monkeypatch):
    root = os.getenv("SENTIMENT_DATA_ROOT")
    if not root:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    import httpx

    _development_env(monkeypatch, root)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda *a, **kw: pytest.fail("pipeline replay must remain offline")
    )

    # Load the actual 363-record frozen publication. Development-only deterministic
    # providers verify orchestration; these outputs are never thesis results.
    class FrozenOnlySource(CachedCorpusDocumentSource):
        def __init__(self, root, **kwargs):
            super().__init__(root, scope="frozen")

    monkeypatch.setattr("sentiment_system.bootstrap.container.CachedCorpusDocumentSource", FrozenOnlySource)
    container = build_container()
    client = TestClient(create_app(container=container))
    investors = (_investor(client, "real-cache-passive"), _investor(client, "real-cache-active", "active"))
    response = client.post("/batch/run", json={"as_of": "2026-08-28", "source_scope": "frozen"})
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["document_count"] == 363
    assert run["snapshot_count"] == 18
    assert set(run["companies"]) == set(RESEARCH_TICKERS)
    _assert_predictions(client, container, run, "2026-08-28", investors, RESEARCH_TICKERS)
    audit = container.provenance_repository.get(run["run_id"])
    assert len(audit.parsed_output) == run["scored_chunk_count"]
    assert len(audit.processing_config["source_lineage"]) == 363
