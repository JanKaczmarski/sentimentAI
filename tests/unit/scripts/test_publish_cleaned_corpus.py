"""Cleaning revisions preserve frozen inputs and never overwrite prior evidence."""

import hashlib
import inspect
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts import acquire_corpus
from sentiment_system.adapters.outbound.persistence.in_memory import InMemoryChunkRepository, InMemoryDocumentRepository
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource
from sentiment_system.adapters.outbound.sources.fixtures import FixtureDocumentSource
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments, _clean_content
from sentiment_system.application.use_cases.sec_content import select_sec_content

SELECTION_VERSION = "thesis-v2-current-cache"
NEW_VERSION = "thesis-v2-current-cache-sec-form-aware-v2"


@pytest.fixture
def publication_inputs(tmp_path, sector_bundle):
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    sec = acquire_corpus.AcquiredCorpusRecord(
        company="META",
        source="sec",
        source_type="sec_filing",
        source_id="acc-1",
        document_type="10-K",
        form="10-K",
        form_items=(),
        published_at=date(2025, 1, 30),
        retrieved_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
        source_url="https://www.sec.gov/Archives/edgar/data/1326801/example.txt",
        raw_content=(
            b"<DOCUMENT><TYPE>10-K\n<TEXT><p>Annual results and notes.</p></TEXT></DOCUMENT>"
            b"<DOCUMENT><TYPE>EX-99.1\n<TEXT><p>Unrelated exhibit.</p></TEXT></DOCUMENT>"
        ),
        cleaned_content="Old incorrectly selected exhibit.",
        parser_version="source-cleaning-v1",
        content_group_id="META:annual",
        canonical_for_scoring=True,
        raw_suffix=".txt",
    )
    ir = replace(
        sec,
        source="investor_relations",
        source_type="investor_relations_transcript",
        source_id="call-1",
        document_type="earnings_call_transcript",
        form=None,
        source_url="https://investor.atmeta.com/call.txt",
        raw_content=b"Full call text.",
        cleaned_content="Preserved transcript formatting.\n\nQ&A.",
        content_group_id="META:call",
    )
    predecessor = acquire_corpus.write_corpus(
        tmp_path,
        (sec, ir),
        sector_review_path=review,
        manifest_version=SELECTION_VERSION,
    )
    manifest = json.loads((predecessor / "manifest.json").read_bytes())
    selection = {
        "manifest_version": SELECTION_VERSION,
        "evaluation_universe": ["META", "CRM", "V", "DIS", "WHR", "T"],
        "inputs": [],
        **{key: manifest[key] for key in ("corpus_window", "development_ends", "held_out_starts")},
        "records": [
            {
                **{
                    key: item[key]
                    for key in ("company", "source", "source_id", "document_type", "published_at", "raw_sha256")
                },
                "raw_path": (predecessor / item["raw_path"]).relative_to(tmp_path).as_posix(),
            }
            for item in manifest["records"]
        ],
    }
    selection_path = tmp_path / f"data/research_selection/{SELECTION_VERSION}.json"
    selection_path.parent.mkdir(parents=True)
    selection_path.write_text(json.dumps(selection))
    review_path = tmp_path / "data/extraction_reviews/test/review.json"
    review_path.parent.mkdir(parents=True)
    cleaned_evidence = review_path.parent / "records/META__acc-1/cleaned.txt"
    cleaned_evidence.parent.mkdir(parents=True)
    cleaned_evidence.write_text("Annual results and notes.")
    review_path.write_text(
        json.dumps(
            {
                "parser_version": "sec-form-aware-v2",
                "errors": [],
                "records": [],
                "implementation_sha256": {
                    "sec_selector": _sha(Path(inspect.getfile(select_sec_content)).read_bytes()),
                    "text_cleaner": _sha(Path(inspect.getfile(_clean_content)).read_bytes()),
                },
            }
        )
    )
    findings = review_path.parent / "findings-final.md"
    findings.write_text("Bounded manual review; not full-corpus certification.")
    return predecessor, selection_path, review_path, findings


def _publish(root, inputs, **kwargs):
    _, selection, review, findings = inputs
    return acquire_corpus.publish_cleaned_corpus(
        root,
        selection_path=selection,
        review_paths=(review,),
        findings_path=findings,
        **kwargs,
    )


def test_publish_preserves_selection_predecessor_and_transcript_and_activates_new_text(tmp_path, publication_inputs):
    predecessor, selection_path, _, _ = publication_inputs
    before = _inventory(predecessor)
    selection_before = selection_path.read_bytes()
    output = _publish(tmp_path, publication_inputs)
    old = json.loads((predecessor / "manifest.json").read_bytes())
    new = json.loads((output / "manifest.json").read_bytes())

    assert output.name == NEW_VERSION
    assert _inventory(predecessor) == before
    assert selection_path.read_bytes() == selection_before
    for key in ("corpus_window", "development_ends", "held_out_starts", "companies"):
        assert new[key] == old[key]
    for previous, current in zip(old["records"], new["records"], strict=True):
        mutable = {"cleaned_sha256", "parser_version"} if current["source"] == "sec" else set()
        assert {k: v for k, v in previous.items() if k not in mutable} == {
            k: v for k, v in current.items() if k not in mutable
        }
        if current["source"] == "sec":
            assert current["parser_version"] == "sec-form-aware-v2"
            assert (output / current["cleaned_path"]).read_text() == "Annual results and notes."
        else:
            assert (output / current["cleaned_path"]).read_bytes() == (
                predecessor / previous["cleaned_path"]
            ).read_bytes()
    assert new["cleaning_provenance"]["selection"]["sha256"] == _sha(selection_before)
    assert _publish(tmp_path, publication_inputs) == output
    docs = CachedCorpusDocumentSource(tmp_path).fetch_evaluation_documents()
    assert len(docs) == 2
    assert all(d.manifest_version == NEW_VERSION and d.document_id.startswith(NEW_VERSION + ":") for d in docs)
    assert next(d for d in docs if d.source == "sec").cleaned_content == "Annual results and notes."

    # Ingestion uses the published bytes, and old/new chunks can coexist.
    old_docs = acquire_corpus._load_final_manifest(
        predecessor / "manifest.json",
        predecessor,
        expected_version=SELECTION_VERSION,
    )
    document_repository = InMemoryDocumentRepository()
    chunk_repository = InMemoryChunkRepository()
    results = []
    for documents in (old_docs, docs):
        results.append(
            IngestDocuments(
                FixtureDocumentSource(documents),
                document_repository,
                chunk_repository,
                processing_config_version="same-chunking-config",
                token_counter=lambda text: len(text.split()),
            ).run()
        )
    # The unchanged transcript is one derivation across both manifests; changed
    # SEC cleaning has its own document/chunks, preserving the old evidence.
    for result in results:
        assert all(document_repository.get(d.document_id) == d for d in result.documents)
    old_sec = next(d for d in results[0].documents if d.source == "sec")
    new_sec = next(d for d in results[1].documents if d.source == "sec")
    assert old_sec.document_id != new_sec.document_id
    assert len(document_repository.list_documents()) == 3


def test_publication_compares_overlapping_reviewed_outputs(tmp_path, publication_inputs):
    predecessor, _, review_path, _ = publication_inputs
    sec = next(
        item for item in json.loads((predecessor / "manifest.json").read_bytes())["records"] if item["source"] == "sec"
    )
    review = json.loads(review_path.read_bytes())
    review["records"] = [
        {
            "accession_number": "acc-1",
            "ticker": "META",
            "status": "extracted",
            "raw_sha256": sec["raw_sha256"],
            "cleaned_sha256": _sha(b"Annual results and notes."),
            "metadata_path": "records/META__acc-1/metadata.json",
        }
    ]
    review_path.write_text(json.dumps(review))
    output = _publish(tmp_path, publication_inputs)
    assert json.loads((output / "publication.json").read_bytes())["reviewed_overlap_verified"] == 1


def test_runtime_rejects_tampered_publication_lineage(tmp_path, publication_inputs):
    output = _publish(tmp_path, publication_inputs)
    (output / "provenance/selection.json").write_text("{}")
    with pytest.raises(ValueError, match="checksum"):
        CachedCorpusDocumentSource(tmp_path)


def test_rerun_checks_requested_sector_and_ignores_unrelated_runtime_code_changes(
    tmp_path, publication_inputs, monkeypatch
):
    output = _publish(tmp_path, publication_inputs)
    manifest = json.loads((output / "manifest.json").read_bytes())
    sector = tmp_path / manifest["sector_review_path"]
    assert _publish(tmp_path, publication_inputs, sector_review_path=sector) == output
    # Existing immutable bytes do not depend on today's cleaner module fingerprint.
    monkeypatch.setattr(
        acquire_corpus, "_clean_text", lambda *a, **kw: pytest.fail("must not re-clean a published corpus")
    )
    assert _publish(tmp_path, publication_inputs) == output
    sector.write_text("{}")
    with pytest.raises(ValueError, match="sector|checksum"):
        _publish(tmp_path, publication_inputs, sector_review_path=sector)


@pytest.mark.parametrize("target", ["raw", "cleaned", "sector", "lineage", "extra"])
def test_rerun_rejects_missing_or_unexpected_artifacts(tmp_path, publication_inputs, target):
    output = _publish(tmp_path, publication_inputs)
    payload = json.loads((output / "manifest.json").read_bytes())
    paths = {
        "raw": payload["records"][0]["raw_path"],
        "cleaned": payload["records"][0]["cleaned_path"],
        "sector": payload["sector_review_path"],
        "lineage": "provenance/selection.json",
    }
    if target == "extra":
        (output / "unexpected.txt").write_text("unrecorded artifact")
    else:
        (output / paths[target]).unlink()
    with pytest.raises(ValueError, match="missing|checksum|artifact|escapes"):
        _publish(tmp_path, publication_inputs)


def test_cli_checks_explicit_sector_and_selection_on_existing_publication(tmp_path, publication_inputs, monkeypatch):
    output = _publish(tmp_path, publication_inputs)
    _, selection, review, findings = publication_inputs
    manifest = json.loads((output / "manifest.json").read_bytes())
    sector = tmp_path / manifest["sector_review_path"]
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_corpus",
            "--data-root",
            str(tmp_path),
            "--selection",
            str(selection),
            "--sector-review",
            str(sector),
            "--sec-reviews",
            str(review),
            "--sec-findings",
            str(findings),
        ],
    )
    acquire_corpus.main()
    sector.write_text("changed requested input")
    with pytest.raises(ValueError, match="sector.*checksum"):
        acquire_corpus.main()


def test_rerun_rejects_changed_selection_even_when_membership_is_identical(tmp_path, publication_inputs):
    _publish(tmp_path, publication_inputs)
    selection = publication_inputs[1]
    payload = json.loads(selection.read_bytes())
    payload["note"] = "Changed requested selection input"
    selection.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="input checksum"):
        _publish(tmp_path, publication_inputs)


@pytest.mark.parametrize("target", ["raw", "cleaned", "selection", "sector"])
@pytest.mark.parametrize("mutation", ["missing", "tampered"])
def test_cli_rerun_rejects_corruption_without_republishing(tmp_path, publication_inputs, monkeypatch, target, mutation):
    output = _publish(tmp_path, publication_inputs)
    _, selection, review, findings = publication_inputs
    manifest_bytes = (output / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    paths = {
        "raw": output / manifest["records"][0]["raw_path"],
        "cleaned": output / manifest["records"][0]["cleaned_path"],
        "selection": selection,
        "sector": tmp_path / manifest["sector_review_path"],
    }
    monkeypatch.setattr(
        "sys.argv",
        [
            "acquire_corpus",
            "--data-root",
            str(tmp_path),
            "--selection",
            str(selection),
            "--sector-review",
            str(paths["sector"]),
            "--sec-reviews",
            str(review),
            "--sec-findings",
            str(findings),
        ],
    )
    monkeypatch.setattr(acquire_corpus, "_clean_text", lambda *a, **kw: pytest.fail("must not re-clean on rerun"))
    acquire_corpus.main()
    if mutation == "missing":
        paths[target].unlink()
    else:
        paths[target].write_bytes(b"changed")
    with pytest.raises(ValueError):
        acquire_corpus.main()
    assert (output / "manifest.json").read_bytes() == manifest_bytes


def test_legacy_network_mode_verifies_existing_plan_without_requests(tmp_path, sector_bundle, monkeypatch):
    from tests.unit.scripts.test_acquire_corpus import _record

    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    ir = _record(
        source="investor_relations",
        source_type="investor_relations_release",
        source_id="release",
        form=None,
        form_items=(),
        raw_content=b"IR release",
        cleaned_content="IR release",
    )
    output = acquire_corpus.write_corpus(tmp_path, (ir,), sector_review_path=review)
    plan = tmp_path / "plan.json"
    payload = [
        {
            "company": ir.company,
            "source_id": ir.source_id,
            "source_url": ir.source_url,
            "published_at": ir.published_at.isoformat(),
            "content_group_id": ir.content_group_id,
        }
    ]
    plan.write_text(json.dumps(payload))
    monkeypatch.setattr(
        "sys.argv",
        ["acquire_corpus", "--data-root", str(tmp_path), "--ir-plan", str(plan), "--sector-review", str(review)],
    )
    monkeypatch.setattr(
        acquire_corpus, "acquire_sec_records", lambda *a, **kw: pytest.fail("unexpected network access")
    )
    acquire_corpus.main()
    payload[0]["published_at"] = "2025-01-29"
    plan.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="plan.*selection"):
        acquire_corpus.main()
    payload[0]["published_at"] = ir.published_at.isoformat()
    plan.write_text(json.dumps(payload))
    (output / "raw/investor_relations/META/release.html").unlink()
    with pytest.raises(ValueError, match="missing|escapes"):
        acquire_corpus.main()


@pytest.mark.parametrize("target", ["predecessor", "published"])
def test_publication_rejects_corrupt_artifacts_even_on_rerun(tmp_path, publication_inputs, target):
    predecessor = publication_inputs[0]
    output = _publish(tmp_path, publication_inputs)
    folder = predecessor if target == "predecessor" else output
    manifest = json.loads((folder / "manifest.json").read_bytes())
    (folder / manifest["records"][0]["cleaned_path"]).write_text("tampered")
    with pytest.raises(ValueError, match="checksum|immutable"):
        _publish(tmp_path, publication_inputs)


@pytest.mark.parametrize("change", ["selection", "implementation", "reviewed_output"])
def test_publication_refuses_changed_selection_or_unreviewed_implementation(tmp_path, publication_inputs, change):
    _, selection_path, review_path, _ = publication_inputs
    if change == "selection":
        selection = json.loads(selection_path.read_bytes())
        selection["records"][0]["published_at"] = "2025-01-29"
        selection_path.write_text(json.dumps(selection))
    else:
        review = json.loads(review_path.read_bytes())
        if change == "implementation":
            review["implementation_sha256"]["sec_selector"] = "0" * 64
        else:
            old = json.loads((publication_inputs[0] / "manifest.json").read_bytes())
            sec = next(item for item in old["records"] if item["source"] == "sec")
            review["records"] = [
                {
                    "accession_number": "acc-1",
                    "raw_sha256": sec["raw_sha256"],
                    "cleaned_sha256": "0" * 64,
                    "ticker": "META",
                    "status": "extracted",
                }
            ]
        review_path.write_text(json.dumps(review))
    with pytest.raises(ValueError, match="selection|review|implementation"):
        _publish(tmp_path, publication_inputs)
    assert not (tmp_path / "data/corpora" / NEW_VERSION).exists()


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _inventory(root):
    return {p.relative_to(root).as_posix(): _sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
