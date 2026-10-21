"""Offline review bundles preserve evidence without certifying semantic quality."""

import hashlib
import json
from collections import Counter
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from scripts import review_sec_extraction as review
from sentiment_system.application.use_cases.sec_content import SecExtraction


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def submission() -> bytes:
    parts = [
        ("8-K", "filing.htm", "Current report", "<p>Item 2.02 Results of Operations</p><p>See earnings release.</p>"),
        (
            "EX-99.1",
            "earnings.htm",
            "Earnings release",
            "<h1>Quarterly earnings release</h1><p>Revenue increased strongly.</p>"
            "<table><tr><td>Revenue</td><td>12345</td></tr></table>",
        ),
        ("EX-99.2", "slides.htm", "Investor presentation", "<h1>Investor presentation</h1><p>Slide narrative.</p>"),
        ("GRAPHIC", "logo.jpg", "Logo", "begin 644 logo.jpg\nM_binary_data\nend"),
    ]
    return (
        "<SEC-DOCUMENT>\n<SEC-HEADER>\nCONFORMED SUBMISSION TYPE: 8-K\n</SEC-HEADER>\n"
        + "\n".join(
            f"<DOCUMENT>\n<TYPE>{kind}\n<SEQUENCE>{index}\n<FILENAME>{name}\n"
            f"<DESCRIPTION>{description}\n<TEXT>\n{body}\n</TEXT>\n</DOCUMENT>"
            for index, (kind, name, description, body) in enumerate(parts, 1)
        )
        + "\n</SEC-DOCUMENT>"
    ).encode()


def make_history(root: Path, tickers: tuple[str, ...] = ("META",), years: tuple[int, ...] = (2020,)) -> list[dict]:
    records = []
    for ticker in tickers:
        folder = root / "data/sec/history" / ticker
        folder.mkdir(parents=True)
        documents = []
        for year in years:
            for number, form in enumerate(("10-K", "10-Q", "8-K"), 1):
                accession = f"0001326801-{year % 100:02d}-{number:06d}"
                raw = submission() if form == "8-K" else b"<html><body><p>Annual revenue 12345.</p></body></html>"
                path = folder / f"{accession}.txt"
                path.write_bytes(raw)
                record = {
                    "accession_number": accession,
                    "form": form,
                    "filed_at": f"{year}-03-01",
                    "published_at": f"{year}-03-01",
                    "form_items": ["2.02", "9.01"] if form == "8-K" else [],
                    "raw_path": path.relative_to(root).as_posix(),
                    "raw_sha256": sha(raw),
                    "source_url": f"https://www.sec.gov/Archives/{accession}.txt",
                    "status": "downloaded",
                }
                documents.append(record)
                records.append({"ticker": ticker, **record})
        (folder / "manifest.json").write_text(json.dumps({"ticker": ticker, "documents": documents}))
    return records


def bundle(root: Path, output: Path, **kwargs: object) -> dict:
    return review.export_review(root, output, tickers=("META",), **kwargs)


def test_stratified_limit_spreads_dates_and_is_independent_of_manifest_order(tmp_path: Path) -> None:
    tickers = ("META", "CRM", "V", "DIS", "WHR", "T")
    make_history(tmp_path, tickers, tuple(range(2015, 2025)))
    first = review.export_review(tmp_path, tmp_path / "first", tickers=tickers, limit=36)
    selected = first["records"]
    assert len(selected) == 36
    assert Counter((row["ticker"], row["form"]) for row in selected) == {
        (ticker, form): 2 for ticker in tickers for form in ("10-K", "10-Q", "8-K")
    }
    assert {row["filed_at"][:4] for row in selected} == {"2015", "2024"}
    for ticker in tickers:
        manifest = tmp_path / "data/sec/history" / ticker / "manifest.json"
        value = json.loads(manifest.read_text())
        value["documents"].reverse()
        manifest.write_text(json.dumps(value))
    second = review.export_review(tmp_path, tmp_path / "second", tickers=tickers, limit=36)
    assert [(r["ticker"], r["accession_number"]) for r in selected] == [
        (r["ticker"], r["accession_number"]) for r in second["records"]
    ]


def test_filters_original_forms_item_202_cutoff_and_targeted_older_accessions(tmp_path: Path) -> None:
    records = make_history(tmp_path, years=(2010, 2024, 2025))
    manifest = tmp_path / "data/sec/history/META/manifest.json"
    value = json.loads(manifest.read_text())
    original = value["documents"][0]
    value["documents"].extend(
        [
            {**original, "form": "10-K/A", "accession_number": "0001326801-10-000009"},
            {**original, "form": "8-K", "form_items": ["5.02"], "accession_number": "0001326801-10-000010"},
            {**original, "filed_at": "2024-08-27", "accession_number": "0001326801-24-000011"},
        ]
    )
    manifest.write_text(json.dumps(value))
    result = bundle(tmp_path, tmp_path / "all", limit=0)
    assert len(result["records"]) == 6
    assert all(date.fromisoformat(r["filed_at"]) < date(2024, 8, 27) for r in result["records"])
    target = records[0]["accession_number"]
    targeted = bundle(tmp_path, tmp_path / "target", accessions=(target,))
    assert [r["accession_number"] for r in targeted["records"]] == [target]


def test_hash_mismatch_is_visible_error_and_other_records_continue(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    records = make_history(tmp_path)
    (tmp_path / records[0]["raw_path"]).write_bytes(b"tampered")
    output = tmp_path / "review"
    code = review.main(["--data-root", str(tmp_path), "--output", str(output), "--tickers", "META"])
    assert code == 1
    result = json.loads((output / "review.json").read_text())
    assert len(result["errors"]) == 1
    assert "SHA256 mismatch" in result["errors"][0]["error"]
    assert len([r for r in result["records"] if r["status"] == "extracted"]) == 2
    assert "ERROR" in capsys.readouterr().err
    failed = next(row for row in result["records"] if row["status"] == "error")
    metadata = json.loads((output / failed["metadata_path"]).read_text())
    assert metadata["observed_raw_sha256"] == sha(b"tampered")
    assert metadata["cleaned_path"] is None


def test_evidence_is_reproducible_and_has_complete_source_lineage(tmp_path: Path) -> None:
    records = make_history(tmp_path)
    original = {r["raw_path"]: (tmp_path / r["raw_path"]).read_bytes() for r in records}
    first, second = tmp_path / "first", tmp_path / "second"
    result = bundle(tmp_path, first)
    bundle(tmp_path, second)
    assert result["reviewed"] is False
    assert result["review_status"] == "manual_review_pending"
    assert result["errors"] == []
    row = next(row for row in result["records"] if row["form"] == "8-K")
    metadata = json.loads((first / row["metadata_path"]).read_text())
    assert (first / row["metadata_path"]).read_bytes() == (second / row["metadata_path"]).read_bytes()
    assert metadata["parser_version"] == review.SEC_PARSER_VERSION
    assert metadata["raw_sha256"] == sha(submission()) == metadata["observed_raw_sha256"]
    snapshot = first / metadata["source_manifest_snapshot"]
    assert sha(snapshot.read_bytes()) == metadata["source_manifest_sha256"]
    assert snapshot.read_bytes() == (tmp_path / metadata["source_manifest"]).read_bytes()
    assert len(metadata["documents"]) == 4
    for decision in metadata["documents"]:
        assert isinstance(decision["selected"], bool)
        assert decision["reason"]
        assert decision["content_sha256"]
        if decision["filename"] == "logo.jpg":
            assert decision["readable_path"] is None
            assert decision["evidence_status"] == "unsupported_binary"
        else:
            readable = first / decision["readable_path"]
            assert readable.is_file()
            assert sha(readable.read_bytes()) == decision["readable_sha256"]
            assert readable.read_bytes() == (second / decision["readable_path"]).read_bytes()
    slides = next(d for d in metadata["documents"] if d["filename"] == "slides.htm")
    assert "Slide narrative" in (first / slides["readable_path"]).read_text()
    cleaned = (first / metadata["cleaned_path"]).read_bytes()
    assert b"12345" in cleaned
    assert sha(cleaned) == metadata["cleaned_sha256"]
    assert cleaned == (second / metadata["cleaned_path"]).read_bytes()
    assert all((tmp_path / path).read_bytes() == raw for path, raw in original.items())
    instructions = (first / "README.md").read_text()
    assert "selection omission" in instructions
    assert "incorporated" in instructions
    assert "external manual annotations" in instructions


@pytest.mark.parametrize("destination", ["existing", "data/sec/history/new", "data/frozen/new"])
def test_output_refuses_existing_or_protected_destination(tmp_path: Path, destination: str) -> None:
    make_history(tmp_path)
    output = tmp_path / destination
    if destination == "existing":
        output.mkdir()
        (output / "sentinel").write_text("keep")
    with pytest.raises((ValueError, FileExistsError)):
        bundle(tmp_path, output)
    if output.exists():
        assert list(output.iterdir()) == [output / "sentinel"]


def test_output_refuses_symlink_and_nested_previous_review(tmp_path: Path) -> None:
    make_history(tmp_path)
    previous = tmp_path / "previous"
    bundle(tmp_path, previous)
    with pytest.raises(ValueError):
        bundle(tmp_path, previous / "nested")
    (tmp_path / "link").symlink_to(previous, target_is_directory=True)
    with pytest.raises(ValueError):
        bundle(tmp_path, tmp_path / "link/new")


@pytest.mark.parametrize("unsafe", ["../outside.txt", "data/sec/history/META/link.txt"])
def test_contained_file_checks_apply_before_raw_read(tmp_path: Path, unsafe: str) -> None:
    records = make_history(tmp_path)
    (tmp_path / "data/sec/history/META/link.txt").symlink_to(tmp_path / records[0]["raw_path"])
    manifest = tmp_path / "data/sec/history/META/manifest.json"
    value = json.loads(manifest.read_text())
    value["documents"][0]["raw_path"] = unsafe
    manifest.write_text(json.dumps(value))
    result = bundle(tmp_path, tmp_path / "review")
    assert len(result["errors"]) == 1
    assert "safe regular relative file" in result["errors"][0]["error"]


def test_missing_manifest_or_requested_accession_is_an_error(tmp_path: Path) -> None:
    make_history(tmp_path)
    missing = review.export_review(tmp_path, tmp_path / "missing", tickers=("CRM",))
    assert missing["errors"]
    targeted = bundle(tmp_path, tmp_path / "targeted", accessions=("0001326801-10-999999",))
    assert "not eligible" in targeted["errors"][0]["error"]


def test_cli_environment_root_all_and_default_fresh_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_history(tmp_path)
    monkeypatch.setenv("SENTIMENT_DATA_ROOT", str(tmp_path))
    assert review.main(["--tickers", "META", "--all"]) == 0
    outputs = list((tmp_path / "data/extraction_reviews").iterdir())
    assert len(outputs) == 1
    result = json.loads((outputs[0] / "review.json").read_text())
    assert result["inputs"]["limit"] == 0
    assert result["inputs"]["before"] == "2024-08-27"
    assert result["inputs"]["data_root"] == str(tmp_path)


def test_parser_exception_is_captured_per_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_history(tmp_path)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("parser exploded")

    monkeypatch.setattr(review, "select_sec_content", broken)
    result = bundle(tmp_path, tmp_path / "review")
    assert len(result["errors"]) == 3
    assert all("parser exploded" in row["error"] for row in result["errors"])


def test_parser_issues_are_warnings_not_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    make_history(tmp_path)
    selector = review.select_sec_content

    def with_issue(raw: str, *, form: str | None = None) -> SimpleNamespace:
        extraction = selector(raw, form=form)
        return SimpleNamespace(
            content=extraction.content,
            form=extraction.form,
            documents=extraction.documents,
            issues=("external incorporated source missing",),
        )

    monkeypatch.setattr(review, "select_sec_content", with_issue)
    result = bundle(tmp_path, tmp_path / "review")
    assert result["errors"] == []
    assert all(row["status"] == "extracted" for row in result["records"])
    assert any(row["warning"] == "external incorporated source missing" for row in result["warnings"])


def test_source_manifest_must_be_contained_regular_file(tmp_path: Path) -> None:
    make_history(tmp_path)
    manifest = tmp_path / "data/sec/history/META/manifest.json"
    original = tmp_path / "original.json"
    manifest.rename(original)
    manifest.symlink_to(original)
    result = bundle(tmp_path, tmp_path / "review")
    assert result["records"] == []
    assert "safe regular relative file" in result["errors"][0]["error"]


def test_missing_raw_hash_remains_a_record_error_without_aborting_batch(tmp_path: Path) -> None:
    make_history(tmp_path)
    manifest = tmp_path / "data/sec/history/META/manifest.json"
    value = json.loads(manifest.read_text())
    del value["documents"][0]["raw_sha256"]
    manifest.write_text(json.dumps(value))
    result = bundle(tmp_path, tmp_path / "review")
    assert len(result["records"]) == 3
    assert len(result["errors"]) == 1
    assert "raw_sha256" in result["errors"][0]["error"]


def update_8k(root: Path, raw: bytes) -> None:
    manifest = root / "data/sec/history/META/manifest.json"
    value = json.loads(manifest.read_text())
    record = next(row for row in value["documents"] if row["form"] == "8-K")
    (root / record["raw_path"]).write_bytes(raw)
    record["raw_sha256"] = sha(raw)
    manifest.write_text(json.dumps(value))


def test_xbrl_wrapped_source_evidence_preserves_hidden_text_and_repeated_values(tmp_path: Path) -> None:
    make_history(tmp_path)
    body = (
        b"<XBRL><html><head><title>Head noise</title></head><body>"
        b"<p>Wrapped main disclosure</p><ix:nonFraction>777</ix:nonFraction>"
        b"<table><tr><td>777</td><td>777</td></tr></table>"
        b"<div hidden style='display:none'>Hidden source metadata</div>"
        b"<script>Script noise</script><style>Style noise</style></body></html></XBRL>"
    )
    raw = submission().replace(b"<p>Item 2.02 Results of Operations</p><p>See earnings release.</p>", body)
    update_8k(tmp_path, raw)
    output = tmp_path / "review"
    result = bundle(tmp_path, output)
    assert result["errors"] == []
    row = next(row for row in result["records"] if row["form"] == "8-K")
    metadata = json.loads((output / row["metadata_path"]).read_text())
    main = next(doc for doc in metadata["documents"] if doc["document_type"] == "8-K")
    evidence = (output / main["readable_path"]).read_text()
    assert "Wrapped main disclosure" in evidence
    assert "Hidden source metadata" in evidence
    assert evidence.split().count("777") == 3
    assert all(noise not in evidence for noise in ("Head noise", "Script noise", "Style noise"))
    assert metadata["status"] == "extracted"
    assert "12345" in (output / metadata["cleaned_path"]).read_text()


@pytest.mark.parametrize("body", ["", "<XBRL></XBRL>", "<html><head><title>Only metadata</title></head></html>"])
def test_empty_supporting_evidence_warns_and_preserves_cleaned_output(tmp_path: Path, body: str) -> None:
    make_history(tmp_path)
    support = (
        "<DOCUMENT>\n<TYPE>EX-101.INS\n<FILENAME>instance.xml\n<DESCRIPTION>XBRL instance\n"
        f"<TEXT>{body}</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>"
    )
    raw = submission().replace(b"</SEC-DOCUMENT>", support.encode())
    update_8k(tmp_path, raw)
    output = tmp_path / "review"
    result = bundle(tmp_path, output)
    assert result["errors"] == []
    row = next(row for row in result["records"] if row["form"] == "8-K")
    metadata = json.loads((output / row["metadata_path"]).read_text())
    supporting = next(doc for doc in metadata["documents"] if doc["document_type"] == "EX-101.INS")
    assert supporting["evidence_status"] == "empty_readable"
    assert (output / supporting["readable_path"]).read_bytes() == b""
    assert supporting["readable_sha256"] == sha(b"")
    assert any("document 5: readable evidence is empty" in warning for warning in metadata["warnings"])
    expected = review._clean_content(submission().decode(), source="sec", form="8-K").encode()
    assert (output / metadata["cleaned_path"]).read_bytes() == expected
    assert metadata["cleaned_sha256"] == sha(expected)
    assert metadata["status"] == "extracted"


def test_source_evidence_never_uses_production_cleaner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    make_history(tmp_path)
    cleaner = review._clean_content
    calls = []

    def production_only(raw: str, *, source: str = "", form: str | None = None) -> str:
        assert source == "sec", "source evidence must be independent of production cleaning"
        calls.append(form)
        return cleaner(raw, source=source, form=form)

    monkeypatch.setattr(review, "_clean_content", production_only)
    result = bundle(tmp_path, tmp_path / "review")
    assert result["errors"] == []
    assert Counter(calls) == {"10-K": 1, "10-Q": 1, "8-K": 1}


@pytest.mark.parametrize("selected", [False, True])
def test_only_selected_binary_evidence_warns(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, selected: bool) -> None:
    make_history(tmp_path)
    selector = review.select_sec_content

    def binary_decision(raw: str, *, form: str | None = None) -> SecExtraction:
        extraction = selector(raw, form=form)
        return replace(
            extraction,
            documents=tuple(
                replace(doc, selected=selected) if doc.document_type == "GRAPHIC" else doc
                for doc in extraction.documents
            ),
        )

    monkeypatch.setattr(review, "select_sec_content", binary_decision)
    output = tmp_path / "review"
    result = bundle(tmp_path, output)
    assert result["errors"] == []
    row = next(row for row in result["records"] if row["form"] == "8-K")
    metadata = json.loads((output / row["metadata_path"]).read_text())
    graphic = next(doc for doc in metadata["documents"] if doc["document_type"] == "GRAPHIC")
    assert graphic["evidence_status"] == "unsupported_binary"
    assert graphic["readable_path"] is None
    assert graphic["reason"]
    assert bool([warning for warning in metadata["warnings"] if "binary/unsupported" in warning]) == selected
