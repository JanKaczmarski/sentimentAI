"""Durable pipeline composition and populated prediction-schema upgrade checks."""

import os
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo
from qdrant_client import QdrantClient
from qdrant_client import models as qdrant_models

from scripts.acquire_corpus import write_corpus
from sentiment_system.adapters.outbound.persistence.postgres import PostgresDatabase, PostgresPredictionRepository
from sentiment_system.application.ports.vector_store import VectorQuery
from sentiment_system.bootstrap.container import build_container
from sentiment_system.bootstrap.main import create_app
from sentiment_system.domain.investment_thesis import InvestmentStyle
from tests.integration.test_frozen_pipeline import _assert_predictions, _development_env, _investor
from tests.unit.scripts.test_acquire_corpus import _record


@pytest.fixture
def isolated_database():
    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")
    schema = "pipeline_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-csearch_path={schema}")
    try:
        yield isolated
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.integration
@pytest.mark.parametrize("vector_backend", ("memory", "qdrant"))
def test_durable_frozen_pipeline_keeps_multiple_investors_and_thesis_versions(
    isolated_database,
    tmp_path,
    sector_bundle,
    monkeypatch,
    vector_backend,
):
    qdrant_url = os.getenv("QDRANT_TEST_URL")
    if vector_backend == "qdrant" and not qdrant_url:
        pytest.skip("QDRANT_TEST_URL is not configured")
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    write_corpus(
        tmp_path, (_record(cleaned_content="Revenue growth increased. Costs declined."),), sector_review_path=review
    )
    _development_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_URL", isolated_database)
    collection = "pipeline_" + uuid4().hex
    if vector_backend == "qdrant":
        monkeypatch.setenv("QDRANT_URL", qdrant_url)
        monkeypatch.setenv("QDRANT_COLLECTION", collection)
    container = build_container()
    try:
        client = TestClient(create_app(container=container))
        investors = (_investor(client, "first"), _investor(client, "second", "active"))
        response = client.post("/batch/run", json={"company": "META", "as_of": "2025-01-31", "source_scope": "frozen"})
        assert response.status_code == 200, response.text
        run = response.json()
        _assert_predictions(client, container, run, "2025-01-31", investors, ("META",))
        original = container.prediction_repository.list_for_user(investors[0]["user_id"])
        assert len(original) == 1
        # A thesis change creates a new auditable personalization of the same scores.
        thesis = container.investment_thesis_repository.list_for_user(investors[0]["user_id"])[0]
        container.manage_investment_theses.update(
            api_key=investors[0]["api_key"],
            thesis_id=thesis.thesis_id,
            companies=thesis.companies,
            risk_tolerance=thesis.risk_tolerance,
            investment_horizon=thesis.investment_horizon,
            investment_style=InvestmentStyle.ACTIVE,
            description="Explanation only",
        )
        response = client.get(
            "/companies/META/prediction",
            params={
                "api_key": investors[0]["api_key"],
                "as_of": "2025-01-31",
                "source_scope": "frozen",
            },
        )
        assert response.status_code == 200
        history = container.prediction_repository.list_for_user(investors[0]["user_id"])
        assert len(history) == 2
        assert original[0] in history
        assert len({prediction.prediction_id for prediction in history}) == 2
        assert len(container.prediction_repository.list_for_user(investors[1]["user_id"])) == 1
        # Rebuild from the database: metadata/history survive a process restart.
        restarted = PostgresPredictionRepository(PostgresDatabase(isolated_database))
        assert restarted.list_for_user(investors[0]["user_id"]) == history
        audit = container.provenance_repository.get(run["run_id"])
        assert audit.processing_config["status"] == "completed"
        assert audit.processing_config["stages"]["exclusion_sync"]["status"] == "completed"
        chunk = container.chunk_repository.get(history[0].evidence[0].chunk_id)
        matches = container.vector_store.search(
            VectorQuery(
                embedding=container.embedding_provider.embed(chunk.content),
                company="META",
                as_of=date(2025, 1, 31),
            )
        )
        assert matches[0].chunk == chunk
        assert (
            container.run_batch.execute(company="META", as_of=date(2025, 1, 31), source_scope="frozen").document_count
            == 1
        )
        assert len(container.document_repository.list_documents(company="META")) == 1
        assert restarted.list_for_user(investors[0]["user_id"]) == history
    finally:
        if vector_backend == "qdrant":
            client = QdrantClient(url=qdrant_url)
            client.delete_collection(collection)
            client.close()


@pytest.mark.integration
def test_prediction_upgrade_keeps_existing_values_and_evidence(isolated_database, tmp_path):
    migrations = Path(__file__).parents[2] / "src/sentiment_system/adapters/outbound/persistence/migrations"
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    for path in migrations.glob("*.sql"):
        if path.name[:4] < "0012":
            (legacy / path.name).write_bytes(path.read_bytes())
    database = PostgresDatabase(isolated_database, migrations_dir=legacy)
    database.migrate()
    now = datetime.now(timezone.utc)
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO experiment_runs (run_id,run_type,status,started_at) VALUES ('legacy','batch','completed',%s)",
            (now,),
        )
        connection.execute("""
            INSERT INTO predictions (company,as_of,lookback_days,forecast_horizon_days,base_score,base_label,
                base_confidence,personalized_score,personalized_label,personalized_confidence,confidence,reasoning,run_id)
            VALUES ('META','2025-01-31',365,20,0.7,'POSITIVE',0.8,0.6,'NEUTRAL',0.8,0.8,'Original reasoning','legacy')
        """)
        connection.execute("""
            INSERT INTO prediction_evidence (company,as_of,lookback_days,forecast_horizon_days,run_id,evidence_rank,
                chunk_id,published_at,importance_score,excerpt,sentiment_score,sentiment_label,sentiment_confidence)
            VALUES ('META','2025-01-31',365,20,'legacy',1,'original-chunk','2025-01-30',0.9,'Original evidence',0.7,'POSITIVE',0.8)
        """)
        before = connection.execute("SELECT * FROM predictions").fetchone()
        evidence_before = connection.execute("SELECT * FROM prediction_evidence").fetchone()
    upgraded = PostgresDatabase(isolated_database)
    upgraded.migrate()
    upgraded.migrate()
    with upgraded.connect() as connection:
        after = connection.execute("SELECT * FROM predictions").fetchone()
        evidence_after = connection.execute("SELECT * FROM prediction_evidence").fetchone()
    assert {key: after[key] for key in before} == before
    assert {key: evidence_after[key] for key in evidence_before} == evidence_before
    prediction = PostgresPredictionRepository(upgraded).list_for_company("META")[0]
    assert prediction.rule_version is None
    assert prediction.run_metadata == prediction.thesis_parameters == {}
    assert prediction.evidence[0].excerpt == "Original evidence"


@pytest.mark.integration
def test_durable_ingestion_reuses_vectors_after_restart_and_repairs_missing_points(
    isolated_database, tmp_path, sector_bundle, monkeypatch
):
    qdrant_url = os.getenv("QDRANT_TEST_URL")
    if not qdrant_url:
        pytest.skip("QDRANT_TEST_URL is not configured")
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    write_corpus(tmp_path, (_record(cleaned_content="Revenue grew. Costs fell."),), sector_review_path=review)
    _development_env(monkeypatch, tmp_path)
    monkeypatch.setenv("DATABASE_URL", isolated_database)
    collection = "ingestion_" + uuid4().hex
    monkeypatch.setenv("QDRANT_URL", qdrant_url)
    monkeypatch.setenv("QDRANT_COLLECTION", collection)
    vectors = QdrantClient(url=qdrant_url)
    payload = {"as_of": "2025-01-31", "source_scope": "frozen"}
    try:
        container = build_container()
        first = TestClient(create_app(container=container)).post("/companies/META/ingest", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["embedded_chunk_count"] == 1
        audit = container.provenance_repository.get(first.json()["run_id"])
        restarted = build_container()
        original = restarted.embedding_provider.embed
        monkeypatch.setattr(
            restarted.embedding_provider, "embed", lambda text: pytest.fail("restart must reuse vectors")
        )
        client = TestClient(create_app(container=restarted))
        second = client.post("/companies/META/ingest", json=payload)
        assert second.status_code == 200, second.text
        assert second.json()["embedded_chunk_count"] == 0 and second.json()["reused_chunk_count"] == 1
        assert restarted.provenance_repository.get(first.json()["run_id"]) == audit
        assert len(restarted.document_repository.list_documents()) == 1
        assert vectors.count(collection_name=collection, exact=True).count == 1
        chunk_id = audit.processing_config["source_lineage"][0]["chunk_ids"][0]
        vectors.delete(
            collection_name=collection,
            points_selector=qdrant_models.PointIdsList(
                points=[str(uuid5(NAMESPACE_URL, f"sentiment-system/chunk/{chunk_id}"))]
            ),
            wait=True,
        )
        monkeypatch.setattr(restarted.embedding_provider, "embed", original)
        repaired = client.post("/companies/META/ingest", json=payload)
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()["embedded_chunk_count"] == 1 and repaired.json()["reused_chunk_count"] == 0
        assert vectors.count(collection_name=collection, exact=True).count == 1
        assert restarted.snapshot_repository.list_for_company("META") == ()
        assert restarted.chunk_score_repository.list_for_chunk(chunk_id) == ()
    finally:
        if vectors.collection_exists(collection):
            vectors.delete_collection(collection)
        vectors.close()
