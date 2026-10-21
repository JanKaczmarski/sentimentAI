"""Upgrade populated legacy databases without rewriting evidence or inventing PDF hashes."""

import csv
import json
import os
from dataclasses import replace
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from sentiment_system.adapters.outbound.persistence.postgres import (
    PostgresChunkRepository,
    PostgresDatabase,
    PostgresDocumentRepository,
)
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.domain.documents import SourceArtifact, SourceDocument, SourceProvenance


@pytest.mark.integration
@pytest.mark.parametrize("last_migration", ["0007", "0008", "0010"])
def test_populated_upgrade_preserves_pdf_identity_scores_and_chunk_lineage(tmp_path, last_migration):
    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")
    schema = "upgrade_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = make_conninfo(dsn, options=f"-csearch_path={schema}")
    migrations = Path(__file__).parents[2] / "src/sentiment_system/adapters/outbound/persistence/migrations"
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    for path in migrations.glob("*.sql"):
        if path.name[:4] <= last_migration:
            (old_migrations / path.name).write_bytes(path.read_bytes())
    database = PostgresDatabase(isolated, old_migrations)
    database.migrate()
    text = "Full call transcript. Guidance remains stable."
    text_hash, pdf_hash = sha256(text.encode()).hexdigest(), sha256(b"%PDF original artifact").hexdigest()
    provenance = {
        "manifest_record_id": "ir:call:original",
        "source_url": "https://investor.atmeta.com/call.pdf",
        "retrieved_at": "2026-10-17T00:00:00+00:00",
        "raw_path": "raw/call.pdf",
        "raw_sha256": pdf_hash,
        "cleaned_path": "cleaned/call.txt",
        "cleaned_sha256": text_hash,
        "parser_version": "source-cleaning-v1",
        "source_type": "investor_relations_transcript",
        "form": None,
        "form_items": [],
        "content_group_id": "META:call",
        "canonical_for_scoring": True,
        "evaluation_member": True,
        "sector": "Communication Services",
        "sector_source_url": "https://example.com/META",
        "sector_retrieved_at": "2026-10-17T00:00:00+00:00",
    }
    try:
        with database.connect() as connection:
            for identity in ("known", "unknown"):
                columns = "document_id, source_id, company, source, published_at, document_type, raw_content, cleaned_content, raw_content_sha256, cleaned_content_sha256, manifest_version"
                values = [
                    identity,
                    identity + ".pdf",
                    "META",
                    "investor_relations",
                    "2025-01-30",
                    "earnings_call_transcript",
                    text,
                    text,
                    text_hash,
                    text_hash,
                    "old-corpus",
                ]
                if last_migration >= "0008":
                    columns += ", manifest_provenance"
                    values.append(json.dumps(provenance if identity == "known" else {}))
                if last_migration >= "0009":
                    columns += ", source_raw_sha256"
                    values.append(text_hash)  # reproduce populated 0009's wrong PDF backfill
                placeholders = ",".join(["%s"] * len(values))
                connection.execute(f"INSERT INTO source_documents ({columns}) VALUES ({placeholders})", values)
                connection.execute(
                    "INSERT INTO chunks VALUES (%s,%s,0,%s,%s,'processing-v1',now())",
                    (identity + ":chunk:0", identity, text, text_hash),
                )
            if last_migration == "0010":
                # 0010 allowed identical derivations under different manifests.
                # Preserve both historical rows but replay only one derivation.
                connection.execute("""INSERT INTO source_documents
                    (document_id,source_id,company,source,published_at,document_type,raw_content,cleaned_content,
                     raw_content_sha256,cleaned_content_sha256,manifest_version,manifest_provenance,source_raw_sha256)
                    SELECT 'known-copy',source_id,company,source,published_at,document_type,raw_content,cleaned_content,
                           raw_content_sha256,cleaned_content_sha256,'old-copy-corpus',manifest_provenance,source_raw_sha256
                    FROM source_documents WHERE document_id='known'""")
                connection.execute(
                    "INSERT INTO chunks VALUES ('known-copy:chunk:0','known-copy',0,%s,%s,'processing-v1',now())",
                    (text, text_hash),
                )
            connection.execute("INSERT INTO experiment_runs VALUES ('old-run','scoring','completed',now(),now(),'{}')")
            connection.execute("""INSERT INTO chunk_scores
                (chunk_id,run_id,sentiment_score,sentiment_label,importance_score,confidence,excluded,prompt,raw_response,parsed_output)
                VALUES ('known:chunk:0','old-run',0.5,'NEUTRAL',0.8,1,false,'old prompt','old response','{}')""")
            connection.execute("""INSERT INTO company_sentiment_snapshots
                (company,as_of,window_days,sentiment_score,sentiment_label,confidence,run_id)
                VALUES ('META','2025-01-30',90,0.5,'NEUTRAL',1,'old-run')""")
            connection.execute("""INSERT INTO company_sentiment_snapshot_evidence
                (company,as_of,window_days,run_id,evidence_rank,chunk_id,published_at,importance_score,excerpt,
                 sentiment_score,sentiment_label,sentiment_confidence)
                VALUES ('META','2025-01-30',90,'old-run',1,'known:chunk:0','2025-01-30',0.8,'Historical excerpt',
                        0.5,'NEUTRAL',1)""")
            connection.execute("""INSERT INTO predictions
                (company,as_of,lookback_days,forecast_horizon_days,base_score,base_label,base_confidence,
                 personalized_score,personalized_label,personalized_confidence,confidence,run_id)
                VALUES ('META','2025-01-30',90,20,0.5,'NEUTRAL',1,0.5,'NEUTRAL',1,1,'old-run')""")
            connection.execute("""INSERT INTO prediction_evidence
                (company,as_of,lookback_days,forecast_horizon_days,run_id,evidence_rank,chunk_id,published_at,importance_score,excerpt,
                 sentiment_score,sentiment_label,sentiment_confidence)
                VALUES ('META','2025-01-30',90,20,'old-run',1,'known:chunk:0','2025-01-30',0.8,'Historical prediction excerpt',
                        0.5,'NEUTRAL',1)""")
            before = connection.execute("SELECT * FROM chunk_scores").fetchall()
            evidence_before = connection.execute("SELECT * FROM prediction_evidence").fetchall()
            snapshots_before = connection.execute("SELECT * FROM company_sentiment_snapshot_evidence").fetchall()
        upgraded = PostgresDatabase(isolated)
        upgraded.migrate()
        upgraded.migrate()
        documents, chunks = PostgresDocumentRepository(upgraded), PostgresChunkRepository(upgraded)
        with upgraded.connect() as connection:
            assert connection.execute("SELECT * FROM chunk_scores").fetchall() == before
            evidence_after = connection.execute("SELECT * FROM prediction_evidence").fetchall()
            # Forward migrations may add audit identity columns. Every preexisting
            # value must still match exactly, including source IDs and excerpts.
            assert [{key: row[key] for key in evidence_before[0]} for row in evidence_after] == evidence_before
            assert (
                connection.execute("SELECT * FROM company_sentiment_snapshot_evidence").fetchall() == snapshots_before
            )
            unknown = connection.execute("SELECT * FROM source_documents WHERE document_id='unknown'").fetchone()
            assert unknown["source_raw_sha256"] is None
            assert unknown["raw_content_sha256"] == text_hash
            assert unknown["raw_content"] == text
            if last_migration >= "0008":
                known = connection.execute("SELECT * FROM source_documents WHERE document_id='known'").fetchone()
                assert known["source_raw_sha256"] == pdf_hash
                assert known["source_revision_id"] == f"META:investor_relations:known.pdf:{pdf_hash}"

        if last_migration >= "0008":
            # New canonical derivation resolves to the historical ID. Identical
            # legacy chunks must also resolve, so new scores never see duplicates.
            original = documents.get("known")
            assert original is not None
            incoming = replace(original, document_id=original.derivation_id)
            source = FixtureDocumentSource((incoming,))
            ingest = IngestDocuments(
                source,
                documents,
                chunks,
                processing_config_version="processing-v1",
                token_counter=lambda value: len(value.split()),
            )
            first, second = ingest.run(), ingest.run()
            assert first == second
            assert first.documents[0].document_id == "known"
            assert len(first.chunks) == 1
            assert first.chunks[0].chunk_id == "known:chunk:0"
            assert first.chunks[0].document_id == "known"
            assert len(documents.list_documents()) == (3 if last_migration == "0010" else 2)
            assert len(chunks.list_for_document("known")) == 1
            if last_migration == "0010":
                assert documents.get("known-copy").raw_content == text
                assert chunks.get("known-copy:chunk:0").content == text
                with upgraded.connect() as connection:
                    assert connection.execute("SELECT count(*) AS n FROM document_derivations").fetchone()["n"] == 1
            with pytest.raises(ValueError, match="immutable"):
                chunks.save(replace(first.chunks[0], content="Must not overwrite scored evidence."))
            with pytest.raises(ValueError, match="immutable"):
                documents.save(replace(original, raw_content="Conflicting source text."))
            changed = replace(
                incoming,
                cleaned_content="New cleaning. Preserved old guidance.",
                provenance=replace(
                    incoming.provenance,
                    cleaned_sha256=sha256(b"New cleaning. Preserved old guidance.").hexdigest(),
                    parser_version="cleaning-v2",
                ),
            )
            new_result = IngestDocuments(
                FixtureDocumentSource((changed,)),
                documents,
                chunks,
                processing_config_version="processing-v1",
                token_counter=lambda value: len(value.split()),
            ).run()
            assert new_result.documents[0].document_id != "known"
            assert chunks.get("known:chunk:0").content == text
            assert all(chunks.get(c.chunk_id).document_id == c.document_id for c in new_result.chunks)
            with upgraded.connect() as connection:
                assert connection.execute("SELECT count(*) AS n FROM source_revisions").fetchone()["n"] == 1
                assert connection.execute("SELECT * FROM chunk_scores").fetchall() == before
        # Hashless legacy rows remain historical; a verified replay creates one
        # active revision without asserting the old PDF's unrecoverable byte hash.
        verified = SourceDocument(
            document_id="verified-unknown",
            source_id="unknown.pdf",
            company="META",
            source="investor_relations",
            published_at=date(2025, 1, 30),
            document_type="earnings_call_transcript",
            raw_content=text,
            cleaned_content="",
            artifact=SourceArtifact(sha256=pdf_hash, path="raw/unknown.pdf"),
        )
        replay = IngestDocuments(
            FixtureDocumentSource((verified,)),
            documents,
            chunks,
            processing_config_version="processing-v2",
            token_counter=lambda value: len(value.split()),
        )
        current = replay.run()
        assert replay.run() == current
        assert len(current.documents) == len(current.chunks) == 1
        assert current.documents[0].document_id != "unknown"
        assert documents.get("unknown").original_byte_sha256 is None
        assert chunks.get("unknown:chunk:0").content == text
        assert current.chunks[0].document_id == current.documents[0].document_id
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.integration
def test_broad_csv_pdf_hash_survives_ingestion_and_postgres_round_trip(tmp_path):
    from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
    from tests.unit.scripts.test_download_earnings_calls import transcript_pdf

    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")
    folder = tmp_path / "data/company_communications/curated/META"
    folder.mkdir(parents=True)
    filename = f"call-{uuid4().hex}.pdf"
    raw = transcript_pdf("Full earnings call. Guidance remains stable. QUESTIONS AND ANSWERS")
    (folder / filename).write_bytes(raw)
    row = {
        "canonical_filename": filename,
        "ticker": "META",
        "published_at": "2025-01-30",
        "document_type": "earnings_call_transcript",
        "sha256": sha256(raw).hexdigest(),
    }
    with (folder / "manifest.csv").open("w") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)
    source = CachedCorpusDocumentSource(tmp_path)
    database = PostgresDatabase(dsn)
    database.migrate()
    documents, chunks = PostgresDocumentRepository(database), PostgresChunkRepository(database)
    ingest = IngestDocuments(
        source,
        documents,
        chunks,
        processing_config_version="pdf-round-trip-v1",
        token_counter=lambda text: len(text.split()),
    )
    result = ingest.run()
    assert ingest.run() == result
    stored = documents.get(result.documents[0].document_id)
    assert stored.original_byte_sha256 == sha256(raw).hexdigest()
    assert stored.original_byte_sha256 != sha256(stored.raw_content.encode()).hexdigest()
    assert stored.provenance is None
    with database.connect() as connection:
        value = connection.execute(
            "SELECT source_raw_sha256,raw_content_sha256 FROM source_documents WHERE document_id=%s",
            (stored.document_id,),
        ).fetchone()
        assert value["source_raw_sha256"] == sha256(raw).hexdigest()
        assert value["raw_content_sha256"] == sha256(stored.raw_content.encode()).hexdigest()


@pytest.mark.integration
def test_broad_pdf_then_frozen_membership_reuses_derivation_and_preserves_old_chunks(tmp_path):
    from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
    from sentiment_system.domain.research import FINAL_CORPUS_VERSION
    from tests.unit.scripts.test_download_earnings_calls import transcript_pdf

    dsn = os.getenv("POSTGRES_TEST_DSN")
    if not dsn:
        pytest.skip("POSTGRES_TEST_DSN is not configured")
    schema = "transition_" + uuid4().hex
    with psycopg.connect(dsn) as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        database = PostgresDatabase(make_conninfo(dsn, options=f"-csearch_path={schema}"))
        database.migrate()
        folder = tmp_path / "data/company_communications/curated/META"
        folder.mkdir(parents=True)
        raw = transcript_pdf("Full earnings call. Guidance remains stable. QUESTIONS AND ANSWERS")
        filename = "call.pdf"
        (folder / filename).write_bytes(raw)
        row = {
            "canonical_filename": filename,
            "ticker": "META",
            "published_at": "2025-01-30",
            "document_type": "earnings_call_transcript",
            "sha256": sha256(raw).hexdigest(),
        }
        with (folder / "manifest.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=tuple(row))
            writer.writeheader()
            writer.writerow(row)
        broad = CachedCorpusDocumentSource(tmp_path).fetch_documents()[0]
        documents, chunks = PostgresDocumentRepository(database), PostgresChunkRepository(database)

        def ingest(document, config="chunks-v1"):
            return IngestDocuments(
                FixtureDocumentSource((document,)),
                documents,
                chunks,
                processing_config_version=config,
                token_counter=lambda text: len(text.split()),
            ).run()

        original = ingest(broad)
        stored = original.documents[0]
        provenance = SourceProvenance(
            manifest_record_id="ir:call:original",
            source_url="https://investor.atmeta.com/call.pdf",
            retrieved_at=datetime(2026, 10, 17, tzinfo=timezone.utc),
            raw_path="raw/call.pdf",
            raw_sha256=sha256(raw).hexdigest(),
            cleaned_path="cleaned/call.txt",
            cleaned_sha256=sha256(stored.cleaned_content.encode()).hexdigest(),
            parser_version=stored.cleaning_version,
            source_type="investor_relations_transcript",
            form=None,
            form_items=(),
            content_group_id="META:call",
            canonical_for_scoring=True,
            evaluation_member=True,
            sector="Communication Services",
            sector_source_url="https://example.com/META",
            sector_retrieved_at=datetime(2026, 10, 18, tzinfo=timezone.utc),
        )
        frozen = replace(
            broad,
            document_id="frozen-alias",
            cleaned_content=stored.cleaned_content,
            manifest_version=FINAL_CORPUS_VERSION,
            provenance=provenance,
        )
        assert ingest(frozen) == original
        assert ingest(frozen) == original
        assert len(documents.list_documents()) == 1
        assert documents.get(stored.document_id).provenance is None
        with database.connect() as connection:
            memberships = connection.execute(
                "SELECT manifest_version, provenance FROM document_manifest_memberships WHERE document_id=%s",
                (stored.document_id,),
            ).fetchall()
            assert {row["manifest_version"] for row in memberships} == {broad.manifest_version, FINAL_CORPUS_VERSION}
            assert (
                next(row["provenance"] for row in memberships if row["manifest_version"] == FINAL_CORPUS_VERSION)[
                    "raw_sha256"
                ]
                == sha256(raw).hexdigest()
            )
            assert connection.execute("SELECT count(*) AS n FROM source_revisions").fetchone()["n"] == 1
        rechunked = ingest(frozen, "chunks-v2")
        assert rechunked.documents == original.documents
        assert {chunk.chunk_id for chunk in original.chunks}.isdisjoint(chunk.chunk_id for chunk in rechunked.chunks)
        assert all(chunks.get(chunk.chunk_id) == chunk for chunk in original.chunks)
        revised_text = "New cleaned transcript. Historical guidance remains addressable."
        revised = replace(
            frozen,
            cleaned_content=revised_text,
            provenance=replace(
                provenance,
                parser_version="transcript-cleaning-v2",
                cleaned_sha256=sha256(revised_text.encode()).hexdigest(),
            ),
        )
        latest = ingest(revised)
        assert latest.documents[0].document_id != stored.document_id
        assert latest.documents[0].source_revision_id == stored.source_revision_id
        assert documents.get(stored.document_id) == stored
        assert all(chunks.get(chunk.chunk_id) == chunk for chunk in (*original.chunks, *rechunked.chunks))
        assert len(documents.list_documents()) == 2
    finally:
        with psycopg.connect(dsn) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
