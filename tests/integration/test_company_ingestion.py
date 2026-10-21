"""API composition for independent ingestion and backwards-compatible combined batches."""

import hashlib
import json
import os

import pytest
from fastapi.testclient import TestClient

from sentiment_system.bootstrap.container import build_container
from sentiment_system.bootstrap.main import create_app


@pytest.fixture
def container(tmp_path, monkeypatch):
    source = tmp_path / "data/sec/earnings_releases/AAPL_acc.txt"
    source.parent.mkdir(parents=True)
    source.write_text("<DOCUMENT><TYPE>8-K<TEXT><p>Revenue grew. Costs fell.</p></TEXT></DOCUMENT>")
    manifest = tmp_path / "data/sec/manifests/previous_calendar_quarter_earnings_releases.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "releases": [
                    {
                        "ticker": "AAPL",
                        "accession_number": "acc",
                        "published_at": "2025-01-01",
                        "raw_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                    }
                ]
            }
        )
    )
    for key in ("DATABASE_URL", "QDRANT_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("SENTIMENT_DATA_ROOT", str(tmp_path))
    monkeypatch.setenv("LLM_BACKEND", "deterministic")
    monkeypatch.setenv("EMBEDDING_BACKEND", "mock")
    return build_container()


def test_cached_company_ingestion_reuses_vectors_and_batch_contract_remains_compatible(container, monkeypatch):
    client = TestClient(create_app(container=container))
    calls = []
    original = container.embedding_provider.embed
    monkeypatch.setattr(container.embedding_provider, "embed", lambda text: (calls.append(text), original(text))[1])
    payload = {"as_of": "2025-01-02"}
    first = client.post("/companies/aapl/ingest", json=payload)
    assert first.status_code == 200
    response = first.json()
    assert response["company"] == "AAPL" and response["source_scope"] == "operational"
    assert response["status"] == "completed"
    assert response["document_count"] == response["chunk_count"] == response["indexed_chunk_count"] == 1
    assert response["embedded_chunk_count"] == 1 and response["reused_chunk_count"] == 0
    assert container.snapshot_repository.list_for_company("AAPL") == ()
    chunks = container.chunk_repository.list_for_document(container.document_repository.list_documents()[0].document_id)
    assert container.chunk_score_repository.list_for_chunk(chunks[0].chunk_id) == ()
    second = client.post("/companies/AAPL/ingest", json=payload).json()
    assert second["run_id"] != response["run_id"]
    assert second["embedded_chunk_count"] == 0 and second["reused_chunk_count"] == 1
    batch = client.post("/batch/run", json={"company": "AAPL", **payload})
    assert batch.status_code == 200
    assert batch.json() == {
        "status": "completed",
        "run_id": batch.json()["run_id"],
        "document_count": 1,
        "chunk_count": 1,
        "indexed_chunk_count": 1,
        "scored_chunk_count": 1,
        "snapshot_count": 3,
        "companies": ["AAPL"],
        "source_scope": "operational",
    }
    assert len(calls) == 1


def test_ingestion_validation_empty_results_and_missing_frozen_failure(container):
    client = TestClient(create_app(container=container))
    invalid = client.post("/companies/UNSUPPORTED/ingest", json={"as_of": "2025-01-02"})
    batch_invalid = client.post("/batch/run", json={"company": "UNSUPPORTED", "as_of": "2025-01-02"})
    assert invalid.status_code == batch_invalid.status_code == 422
    assert invalid.json()["detail"][0]["msg"] == batch_invalid.json()["detail"][0]["msg"]
    assert container.experiment_run_repository.list_runs() == ()
    for payload in ({"source_scope": "invalid"}, {"as_of": "bad-date"}, {"extra": True}):
        assert client.post("/companies/AAPL/ingest", json=payload).status_code == 422
    empty = client.post("/companies/CRM/ingest", json={"as_of": "2025-01-02"})
    assert empty.status_code == 200 and empty.json()["indexed_chunk_count"] == 0
    failure = client.post("/companies/AAPL/ingest", json={"as_of": "2025-01-02", "source_scope": "frozen"})
    assert failure.status_code == 500
    failed = [run for run in container.experiment_run_repository.list_runs() if run.status == "failed"][0]
    assert failure.json() == {"detail": f"ingestion run failed: {failed.run_id}"}
    assert container.provenance_repository.get(failed.run_id).processing_config["failed_stage"] == "ingestion"


@pytest.mark.integration
def test_real_frozen_company_preparation_reuses_all_vectors_offline(monkeypatch):
    root = os.getenv("SENTIMENT_DATA_ROOT")
    if not root:
        pytest.skip("SENTIMENT_DATA_ROOT is not configured")
    import httpx

    from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
    from tests.integration.test_frozen_pipeline import _development_env

    class FrozenOnlySource(CachedCorpusDocumentSource):
        def __init__(self, root, **kwargs):
            super().__init__(root, scope="frozen")

    _development_env(monkeypatch, root)
    monkeypatch.setattr("sentiment_system.bootstrap.container.CachedCorpusDocumentSource", FrozenOnlySource)
    monkeypatch.setattr(
        httpx.HTTPTransport, "handle_request", lambda *args, **kwargs: pytest.fail("offline replay only")
    )
    services = build_container()
    client = TestClient(create_app(container=services))
    payload = {"as_of": "2026-08-28", "source_scope": "frozen"}
    first = client.post("/companies/WHR/ingest", json=payload)
    assert first.status_code == 200, first.text
    counts = first.json()
    assert counts["document_count"] > 0 and counts["embedded_chunk_count"] == counts["chunk_count"] > 0
    monkeypatch.setattr(services.embedding_provider, "embed", lambda text: pytest.fail("repeat must reuse all vectors"))
    second = client.post("/companies/WHR/ingest", json=payload)
    assert second.status_code == 200, second.text
    assert second.json()["document_count"] == counts["document_count"]
    assert second.json()["embedded_chunk_count"] == 0
    assert second.json()["reused_chunk_count"] == second.json()["indexed_chunk_count"] == counts["chunk_count"]
    assert services.snapshot_repository.list_for_company("WHR") == ()
    assert all(document.company == "WHR" for document in services.document_repository.list_documents())
