"""Tests for immutable SEC and investor-relations corpus acquisition output."""

import csv
import hashlib
import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from scripts.acquire_corpus import AcquiredCorpusRecord, CorpusAcquisitionError, acquire_sec_records, write_corpus
from sentiment_system.adapters.outbound.sources.cached import CachedCorpusDocumentSource, CacheManifestError


def test_write_corpus_is_idempotent_and_refuses_to_overwrite_changed_source(tmp_path: Path, sector_bundle) -> None:
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    records = (
        _record(
            source="sec",
            source_type="sec_filing",
            source_id="acc-1",
            raw_content=b"SEC release",
            cleaned_content="SEC release",
            form="8-K",
            form_items=("2.02",),
            canonical_for_scoring=True,
        ),
        _record(
            source="investor_relations",
            source_type="investor_relations_release",
            source_id="aapl-q1-2025",
            raw_content=b"IR release",
            cleaned_content="IR release",
            form=None,
            form_items=(),
            canonical_for_scoring=False,
        ),
    )

    first = write_corpus(tmp_path, records, sector_review_path=review)
    second = write_corpus(tmp_path, records, sector_review_path=review)

    assert first == second
    assert (first / "manifest.json").is_file()
    assert len(tuple(path for path in (first / "raw").rglob("*") if path.is_file())) == 2

    changed = (_record(raw_content=b"Changed SEC release"), records[1])
    with pytest.raises(CorpusAcquisitionError, match="immutable"):
        write_corpus(tmp_path, changed, sector_review_path=review)


def test_writer_derives_dates_and_embeds_verified_sector_evidence(tmp_path: Path, sector_bundle) -> None:
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    records = tuple(
        replace(_record(), source_id=f"acc-{index}", content_group_id=f"META:{index}", published_at=published)
        for index, published in enumerate((date(2021, 9, 1), date(2024, 9, 4), date(2026, 8, 27)))
    )
    output = write_corpus(tmp_path, records, sector_review_path=review)
    payload = json.loads((output / "manifest.json").read_text())

    assert payload["corpus_window"] == {"start": "2021-08-27", "end": "2026-08-27"}
    assert payload["development_ends"] == "2024-08-27"
    assert payload["held_out_starts"] == "2024-09-04"
    assert payload["companies"][0]["sector_retrieved_at"] == "2026-10-18T00:00:00+00:00"
    assert (output / payload["sector_review_path"]).read_bytes() == review.read_bytes()

    assert len(CachedCorpusDocumentSource(tmp_path).fetch_evaluation_documents()) == 3


def test_final_corpus_keeps_amat_and_out_of_window_operational_documents(tmp_path: Path, sector_bundle) -> None:
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    write_corpus(tmp_path, (_record(),), sector_review_path=review)
    sec = tmp_path / "data/sec"
    (sec / "manifests").mkdir(parents=True)
    (sec / "earnings_releases").mkdir()
    releases = []
    for source_id, published, content in (
        ("acc-1", "2025-01-30", b"SEC release"),  # identical frozen revision
        ("older", "2010-01-01", b"Old filing"),
        ("newer", "2026-10-16", b"New filing"),
    ):
        (sec / f"earnings_releases/META_{source_id}.txt").write_bytes(content)
        releases.append({"ticker": "META", "accession_number": source_id, "report_date": published})
    (sec / "manifests/previous_calendar_quarter_earnings_releases.json").write_text(json.dumps({"releases": releases}))
    curated = tmp_path / "data/company_communications/curated/AMAT"
    curated.mkdir(parents=True)
    (curated / "remarks.txt").write_bytes(b"AMAT remarks")
    with (curated / "manifest.csv").open("w", newline="") as handle:
        row = {
            "canonical_filename": "remarks.txt",
            "ticker": "AMAT",
            "published_at": "2026-02-12",
            "document_type": "earnings_call_prepared_remarks",
            "sha256": hashlib.sha256(b"AMAT remarks").hexdigest(),
        }
        writer = csv.DictWriter(handle, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)

    source = CachedCorpusDocumentSource(tmp_path)
    assert len(source.fetch_documents()) == 4
    assert len(source.fetch_documents(company="AMAT")) == 1
    assert len(source.fetch_documents(company="META")) == 3
    assert len(source.fetch_evaluation_documents()) == 1
    assert source.fetch_evaluation_documents()[0].provenance is not None
    assert {item.source_id for item in source.fetch_evaluation_documents()} == {"acc-1"}
    # Another byte revision of that source must remain visible operationally.
    (sec / "earnings_releases/META_acc-1.txt").write_bytes(b"Different revision")
    source = CachedCorpusDocumentSource(tmp_path)
    assert len(source.fetch_documents(company="META")) == 4
    assert len(source.fetch_evaluation_documents()) == 1


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("corpus_window", {"start": "2021-08-27", "end": "2026-08-27"}, "latest included publication"),
        ("development_ends", "2023-09-24", "derive from the cutoff"),
        ("held_out_starts", "2023-01-31", "first included publication"),
    ],
)
def test_reader_rejects_dates_not_derived_from_records(tmp_path: Path, sector_bundle, field, value, message) -> None:
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    output = write_corpus(tmp_path, (_record(),), sector_review_path=review)
    path = output / "manifest.json"
    payload = json.loads(path.read_text())
    payload[field] = value
    path.write_text(json.dumps(payload))
    with pytest.raises(CacheManifestError, match=message):
        CachedCorpusDocumentSource(tmp_path)


def test_reader_rejects_tampered_sector_evidence(tmp_path: Path, sector_bundle) -> None:
    review = tmp_path / sector_bundle(tmp_path)["sector_review_path"]
    output = write_corpus(tmp_path, (_record(),), sector_review_path=review)
    (output / "sector_evidence/META.html").write_text("changed source")
    with pytest.raises(CacheManifestError, match="sector evidence.*checksum"):
        CachedCorpusDocumentSource(tmp_path)


def test_acquire_sec_records_requires_a_descriptive_environment_user_agent() -> None:
    with pytest.raises(CorpusAcquisitionError, match="SEC_USER_AGENT"):
        acquire_sec_records("", retrieved_at=datetime(2025, 9, 24, tzinfo=timezone.utc))


def test_acquisition_cleaner_uses_expected_form_not_exhibit_priority() -> None:
    from scripts.acquire_corpus import _clean_text

    raw = (
        b"<DOCUMENT><TYPE>10-K\n<TEXT><p>Main annual report and financial notes.</p></TEXT></DOCUMENT>"
        b"<DOCUMENT><TYPE>EX-99.1\n<TEXT><p>Separate exhibit.</p></TEXT></DOCUMENT>"
    )
    cleaned = _clean_text(raw, suffix=".txt", source="sec", form="10-K")
    assert "Main annual report and financial notes" in cleaned
    assert "Separate exhibit" not in cleaned


def _record(
    *,
    source: str = "sec",
    source_type: str = "sec_filing",
    source_id: str = "acc-1",
    raw_content: bytes = b"SEC release",
    cleaned_content: str = "SEC release",
    form: str | None = "8-K",
    form_items: tuple[str, ...] = ("2.02",),
    canonical_for_scoring: bool = True,
) -> AcquiredCorpusRecord:
    return AcquiredCorpusRecord(
        company="META",
        source=source,
        source_type=source_type,
        source_id=source_id,
        document_type="earnings_release",
        form=form,
        form_items=form_items,
        published_at=date(2025, 1, 30),
        retrieved_at=datetime(2025, 1, 31, tzinfo=timezone.utc),
        source_url=(
            "https://www.sec.gov/Archives/edgar/data/1326801/example.txt"
            if source == "sec"
            else "https://investor.atmeta.com/example.html"
        ),
        raw_content=raw_content,
        cleaned_content=cleaned_content,
        parser_version="source-cleaning-v1",
        content_group_id="META:2025-Q1",
        canonical_for_scoring=canonical_for_scoring,
    )
