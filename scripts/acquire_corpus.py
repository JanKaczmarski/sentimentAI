"""Immutable corpus writer for a frozen local selection or a curated release plan.

Usage:
    SEC_USER_AGENT="$SEC_USER_AGENT" \
        uv run python -m scripts.acquire_corpus --ir-plan /path/to/ir_releases.json

The IR plan is curated external data. It is never used by the runtime source
adapter, which reads only the completed local cache.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import ipaddress
import json
import os
import re
import shutil
import tempfile
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import urlparse

import httpx
from pypdf import PdfReader

from scripts.curate_earnings_calls import contained_file
from sentiment_system.adapters.outbound.sources.cached import _load_final_manifest
from sentiment_system.adapters.outbound.sources.sector_metadata import load_sector_review
from sentiment_system.application.use_cases.ingest_documents import _clean_content
from sentiment_system.application.use_cases.sec_content import SEC_PARSER_VERSION, select_sec_content
from sentiment_system.domain.research import (
    FINAL_CORPUS_VERSION,
    RESEARCH_SELECTION_VERSION,
    RESEARCH_TICKERS,
    CorpusSplit,
)

_MANIFEST_VERSION = FINAL_CORPUS_VERSION
_REQUEST_DELAY_SECONDS = 0.2
_MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
_SAFE_FILE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_CONTACT_EMAIL = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{directory}/{accession}.txt"


class CorpusAcquisitionError(ValueError):
    """Raised when corpus acquisition cannot create a valid immutable cache."""


@dataclass(frozen=True, slots=True)
class AcquiredCorpusRecord:
    """One downloaded source and its deterministic cleaned representation."""

    company: str
    source: str
    source_type: str
    source_id: str
    document_type: str
    form: str | None
    form_items: tuple[str, ...]
    published_at: date
    retrieved_at: datetime
    source_url: str
    raw_content: bytes
    cleaned_content: str
    parser_version: str
    content_group_id: str
    canonical_for_scoring: bool
    raw_suffix: str | None = None


def write_corpus(
    data_root: Path,
    records: Iterable[AcquiredCorpusRecord],
    *,
    sector_review_path: Path,
    manifest_version: str = _MANIFEST_VERSION,
) -> Path:
    """Atomically write a corpus once, returning its immutable cache directory."""
    if not data_root.is_dir():
        raise CorpusAcquisitionError(f"data root does not exist: {data_root}")
    ordered = tuple(sorted(records, key=_record_sort_key))
    _validate_records(ordered)
    try:
        review_relative = sector_review_path.relative_to(data_root).as_posix()
        companies, evidence = load_sector_review(data_root, review_relative)
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise CorpusAcquisitionError(f"invalid sector evidence: {error}") from error
    manifest, artifacts = _build_manifest(ordered, companies)
    manifest["manifest_version"] = _safe_component(manifest_version)
    manifest.update(
        sector_review_path=review_relative,
        sector_review_sha256=hashlib.sha256(evidence[review_relative]).hexdigest(),
    )
    artifacts = (*artifacts, *((PurePosixPath(path), content) for path, content in evidence.items()))
    return _publish_artifacts(data_root, manifest, artifacts)


def _publish_artifacts(
    data_root: Path, manifest: dict[str, object], artifacts: Iterable[tuple[PurePosixPath, bytes]]
) -> Path:
    """Publish once; even identical reruns verify every expected artifact byte."""
    version = _safe_component(_required_string(manifest, "manifest_version"))
    encoded_manifest = _encode_manifest(manifest)
    corpus_parent = data_root / "data" / "corpora"
    if corpus_parent.is_symlink() or not corpus_parent.resolve().is_relative_to(data_root.resolve()):
        raise CorpusAcquisitionError("corpus output escapes data root")
    corpus_parent.mkdir(parents=True, exist_ok=True)
    destination = corpus_parent / version
    if destination.is_symlink():
        raise CorpusAcquisitionError("immutable corpus must not be a symlink")
    if destination.exists():
        existing_manifest = destination / "manifest.json"
        if (
            not existing_manifest.is_symlink()
            and existing_manifest.is_file()
            and existing_manifest.read_bytes() == encoded_manifest
        ):
            expected_paths = {"manifest.json"}
            for relative, content in artifacts:
                expected_paths.add(relative.as_posix())
                path = contained_file(destination, relative.as_posix())
                if path.read_bytes() != content:
                    raise CorpusAcquisitionError(f"immutable corpus artifact checksum mismatch: {relative}")
            if set(_file_inventory(destination)) != expected_paths:
                raise CorpusAcquisitionError("immutable corpus artifact set changed")
            # All expected artifacts were checked above; untracked additions are
            # also a change to an immutable materialization.
            _load_final_manifest(existing_manifest, destination, expected_version=version)
            return destination
        raise CorpusAcquisitionError(f"final corpus is immutable and already exists: {destination}")

    staging = Path(tempfile.mkdtemp(prefix=f".{version}-", dir=corpus_parent))
    try:
        for relative_path, content in artifacts:
            path = _safe_output_path(staging, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        (staging / "manifest.json").write_bytes(encoded_manifest)
        staging.replace(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return destination


def publish_cleaned_corpus(
    data_root: Path,
    *,
    selection_path: Path,
    review_paths: tuple[Path, ...],
    findings_path: Path,
    sector_review_path: Path | None = None,
) -> Path:
    """Re-clean the approved SEC selection, retaining every other frozen byte.

    Review indexes pin the implementation, not a claim of full-corpus semantic
    approval. Original review flags and the predecessor remain untouched.
    """
    destination = data_root / "data/corpora" / _MANIFEST_VERSION
    if destination.exists() or destination.is_symlink():
        return verify_published_corpus(
            data_root,
            destination,
            selection_path=selection_path,
            review_paths=review_paths,
            findings_path=findings_path,
            sector_review_path=sector_review_path,
        )
    predecessor = data_root / "data/corpora" / RESEARCH_SELECTION_VERSION
    if predecessor.is_symlink() or not predecessor.resolve().is_relative_to(data_root.resolve()):
        raise CorpusAcquisitionError("predecessor corpus must be contained and not a symlink")
    inventory = _file_inventory(predecessor)
    predecessor_manifest = contained_file(predecessor, "manifest.json")
    _load_final_manifest(predecessor_manifest, predecessor, expected_version=RESEARCH_SELECTION_VERSION)
    manifest = json.loads(predecessor_manifest.read_bytes())
    _validate_requested_sector(data_root, predecessor, manifest, sector_review_path)
    snapshots: dict[str, bytes] = {}

    def snapshot(path: Path, name: str) -> dict[str, str]:
        relative = path.relative_to(data_root).as_posix()
        content = contained_file(data_root, relative).read_bytes()
        output = f"provenance/{name}"
        snapshots[output] = content
        return {"source_path": relative, "path": output, "sha256": hashlib.sha256(content).hexdigest()}

    selection_evidence = snapshot(selection_path, "selection.json")
    selection = json.loads(snapshots[selection_evidence["path"]])
    if selection["manifest_version"] != RESEARCH_SELECTION_VERSION or selection["evaluation_universe"] != list(
        RESEARCH_TICKERS
    ):
        raise CorpusAcquisitionError("selection version/universe does not match the approved corpus")
    for field in ("corpus_window", "development_ends", "held_out_starts"):
        if selection[field] != manifest[field]:
            raise CorpusAcquisitionError(f"frozen selection {field} disagrees with predecessor")
    keys = ("company", "source", "source_id", "document_type", "published_at", "raw_sha256")
    selected = {tuple(item[key] for key in keys) for item in selection["records"]}
    previous = {tuple(item[key] for key in keys) for item in manifest["records"]}
    if selected != previous or len(selected) != len(selection["records"]) or len(previous) != len(manifest["records"]):
        raise CorpusAcquisitionError("frozen selection membership/metadata disagrees with predecessor")
    for item in selection["records"]:
        raw = contained_file(data_root, item["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["raw_sha256"]:
            raise CorpusAcquisitionError("frozen selection source checksum mismatch")
    input_evidence = []
    for index, item in enumerate(selection["inputs"]):
        evidence = snapshot(data_root / item["path"], f"inputs/{index:03d}.json")
        if evidence["sha256"] != item["sha256"]:
            raise CorpusAcquisitionError("frozen selection input manifest checksum mismatch")
        input_evidence.append(evidence)

    implementation = {
        "sec_selector": hashlib.sha256(Path(inspect.getfile(select_sec_content)).read_bytes()).hexdigest(),
        "text_cleaner": hashlib.sha256(Path(inspect.getfile(_clean_content)).read_bytes()).hexdigest(),
    }
    if not review_paths:
        raise CorpusAcquisitionError("at least one reviewed extraction index is required")
    reviews = []
    review_evidence = []
    for index, path in enumerate(review_paths):
        evidence = snapshot(path, f"reviews/{index:03d}.json")
        review = json.loads(snapshots[evidence["path"]])
        if review["parser_version"] != SEC_PARSER_VERSION or review["errors"]:
            raise CorpusAcquisitionError("review parser version/errors do not permit publication")
        if any(review["implementation_sha256"].get(key) != value for key, value in implementation.items()):
            raise CorpusAcquisitionError("current implementation does not match reviewed implementation")
        reviews.append((path.parent, review))
        review_evidence.append(evidence)

    provenance = {
        "selection": selection_evidence,
        "selection_inputs": input_evidence,
        "predecessor": snapshot(predecessor_manifest, "predecessor-manifest.json"),
        "reviews": review_evidence,
        "findings": snapshot(findings_path, "findings-final.md"),
        "implementation_sha256": implementation,
        "review_scope": "Bounded development review; publication is not full-corpus semantic approval.",
    }
    inventory_bytes = _encode_manifest(cast(dict[str, object], inventory))
    snapshots["provenance/predecessor-inventory.json"] = inventory_bytes
    provenance["predecessor_inventory"] = {
        "path": "provenance/predecessor-inventory.json",
        "sha256": hashlib.sha256(inventory_bytes).hexdigest(),
    }
    replacements: dict[str, bytes] = {}
    matched: set[str] = set()
    changed = 0
    for record in manifest["records"]:
        if record["source"] != "sec":
            continue
        raw_path = contained_file(predecessor, record["raw_path"])
        cleaned = _clean_text(raw_path.read_bytes(), suffix=raw_path.suffix.lower(), source="sec", form=record["form"])
        content = cleaned.encode("utf-8")
        checksum = hashlib.sha256(content).hexdigest()
        changed += checksum != record["cleaned_sha256"]
        record["cleaned_sha256"] = checksum
        record["parser_version"] = SEC_PARSER_VERSION
        replacements[record["cleaned_path"]] = content
        for review_root, review in reviews:
            for reviewed in review["records"]:
                if (reviewed["ticker"], reviewed["accession_number"]) != (record["company"], record["source_id"]):
                    continue
                if (
                    reviewed["status"] != "extracted"
                    or reviewed["raw_sha256"] != record["raw_sha256"]
                    or reviewed["cleaned_sha256"] != checksum
                ):
                    raise CorpusAcquisitionError(
                        f"published output disagrees with reviewed output: {record['source_id']}"
                    )
                evidence_path = (PurePosixPath(reviewed["metadata_path"]).parent / "cleaned.txt").as_posix()
                if contained_file(review_root, evidence_path).read_bytes() != content:
                    raise CorpusAcquisitionError(f"reviewed output artifact checksum mismatch: {record['source_id']}")
                matched.add(record["record_id"])

    manifest["manifest_version"] = _MANIFEST_VERSION
    manifest["cleaning_provenance"] = provenance
    report = {
        "manifest_version": _MANIFEST_VERSION,
        "predecessor_version": RESEARCH_SELECTION_VERSION,
        "records": len(manifest["records"]),
        "sec_recleaned": len(replacements),
        "sec_cleaned_hashes_changed": changed,
        "ir_cleaned_artifacts_preserved": sum(item["source"] != "sec" for item in manifest["records"]),
        "reviewed_overlap_verified": len(matched),
        "predecessor_files_verified_unchanged": len(inventory),
        "selection_sha256": selection_evidence["sha256"],
        "corpus_window": manifest["corpus_window"],
        "development_ends": manifest["development_ends"],
        "held_out_starts": manifest["held_out_starts"],
    }
    report_bytes = _encode_manifest(report)
    snapshots["publication.json"] = report_bytes
    provenance["publication"] = {"path": "publication.json", "sha256": hashlib.sha256(report_bytes).hexdigest()}

    def artifacts() -> Iterable[tuple[PurePosixPath, bytes]]:
        for relative, checksum in inventory.items():
            original = contained_file(predecessor, relative).read_bytes()
            if hashlib.sha256(original).hexdigest() != checksum:
                raise CorpusAcquisitionError("predecessor artifact checksum changed during publication")
            if relative != "manifest.json":
                yield PurePosixPath(relative), replacements.get(relative, original)
        yield from ((PurePosixPath(path), content) for path, content in snapshots.items())
        if _file_inventory(predecessor) != inventory:
            raise CorpusAcquisitionError("predecessor inventory changed during publication")
        if selection_path.read_bytes() != snapshots[selection_evidence["path"]]:
            raise CorpusAcquisitionError("frozen selection changed during publication")

    return _publish_artifacts(data_root, manifest, artifacts())


def _validate_requested_sector(
    data_root: Path,
    corpus: Path,
    manifest: dict[str, Any],
    requested: Path | None,
) -> None:
    relative = manifest["sector_review_path"]
    requested = requested or data_root / relative
    request_relative = requested.relative_to(data_root).as_posix()
    content = contained_file(data_root, request_relative).read_bytes()
    if hashlib.sha256(content).hexdigest() != manifest["sector_review_sha256"]:
        raise CorpusAcquisitionError("requested sector review checksum differs from frozen evidence")
    _, requested_files = load_sector_review(data_root, request_relative)
    _, frozen_files = load_sector_review(corpus, relative, manifest["sector_review_sha256"])
    if requested_files != frozen_files:
        raise CorpusAcquisitionError("requested sector input artifacts differ from frozen evidence")


def verify_published_corpus(
    data_root: Path,
    corpus: Path,
    *,
    selection_path: Path,
    review_paths: tuple[Path, ...],
    findings_path: Path,
    sector_review_path: Path | None = None,
) -> Path:
    """Validate pinned inputs and complete existing artifacts, never re-clean them.

    An immutable artifact remains verifiable after runtime code evolves. Its
    creation fingerprints describe the historical implementation, not today's.
    """
    if corpus.is_symlink() or not corpus.resolve().is_relative_to(data_root.resolve()):
        raise CorpusAcquisitionError("immutable corpus must be contained and not a symlink")
    manifest_path = contained_file(corpus, "manifest.json")
    _load_final_manifest(manifest_path, corpus)
    manifest = json.loads(manifest_path.read_bytes())
    provenance = manifest.get("cleaning_provenance")
    if not isinstance(provenance, dict):
        raise CorpusAcquisitionError("existing corpus was not published from the requested frozen selection")
    _validate_requested_sector(data_root, corpus, manifest, sector_review_path)

    def verify_input(path: Path, evidence: dict[str, str]) -> None:
        raw = contained_file(data_root, path.relative_to(data_root).as_posix()).read_bytes()
        if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
            raise CorpusAcquisitionError(f"requested input checksum differs from immutable publication: {path}")

    verify_input(selection_path, provenance["selection"])
    for evidence in provenance["selection_inputs"]:
        verify_input(data_root / evidence["source_path"], evidence)
    if len(review_paths) != len(provenance["reviews"]):
        raise CorpusAcquisitionError("requested review indexes differ from immutable publication")
    for path, evidence in zip(review_paths, provenance["reviews"], strict=True):
        verify_input(path, evidence)
    verify_input(findings_path, provenance["findings"])
    predecessor = data_root / "data/corpora" / RESEARCH_SELECTION_VERSION
    inventory = json.loads(contained_file(corpus, provenance["predecessor_inventory"]["path"]).read_bytes())
    if _file_inventory(predecessor) != inventory:
        raise CorpusAcquisitionError("predecessor artifact inventory/checksum changed")
    original_manifest = json.loads(contained_file(corpus, provenance["predecessor"]["path"]).read_bytes())
    if set(manifest) != {*original_manifest, "cleaning_provenance"}:
        raise CorpusAcquisitionError("immutable publication manifest field set changed")
    for key, value in original_manifest.items():
        if key not in {"records", "manifest_version"} and manifest.get(key) != value:
            raise CorpusAcquisitionError(f"immutable publication metadata differs from predecessor: {key}")
    if len(manifest["records"]) != len(original_manifest["records"]):
        raise CorpusAcquisitionError("immutable publication selection membership changed")
    for previous, current in zip(original_manifest["records"], manifest["records"], strict=True):
        mutable = {"parser_version", "cleaned_sha256"} if previous["source"] == "sec" else set()
        if {k: v for k, v in previous.items() if k not in mutable} != {
            k: v for k, v in current.items() if k not in mutable
        }:
            raise CorpusAcquisitionError("immutable publication source metadata/selection changed")
        if previous["source"] == "sec" and current["parser_version"] != SEC_PARSER_VERSION:
            raise CorpusAcquisitionError("immutable SEC parser provenance changed")
    selection = json.loads(contained_file(data_root, selection_path.relative_to(data_root).as_posix()).read_bytes())
    for item in selection["records"]:
        raw = contained_file(data_root, item["raw_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["raw_sha256"]:
            raise CorpusAcquisitionError("frozen selection source checksum mismatch")
    expected = set(inventory)
    entries = [
        provenance[key] for key in ("selection", "predecessor", "findings", "predecessor_inventory", "publication")
    ]
    entries.extend(provenance["selection_inputs"])
    entries.extend(provenance["reviews"])
    expected.update(entry["path"] for entry in entries)
    actual = _file_inventory(corpus)
    if set(actual) != expected:
        raise CorpusAcquisitionError("immutable publication artifact set changed (missing or unexpected files)")
    replaceable = {
        "manifest.json",
        *(record["cleaned_path"] for record in manifest["records"] if record["source"] == "sec"),
    }
    for relative, checksum in inventory.items():
        if relative not in replaceable and actual[relative] != checksum:
            raise CorpusAcquisitionError(f"immutable copied artifact checksum mismatch: {relative}")
    return corpus


def verify_ir_plan_corpus(data_root: Path, corpus: Path, plan_path: Path, sector_review_path: Path) -> Path:
    """Legacy network mode reruns validate locally before making any requests."""
    if corpus.is_symlink():
        raise CorpusAcquisitionError("immutable corpus must not be a symlink")
    _load_final_manifest(corpus / "manifest.json", corpus)
    manifest = json.loads(contained_file(corpus, "manifest.json").read_bytes())
    _validate_requested_sector(data_root, corpus, manifest, sector_review_path)
    keys = ("company", "source_id", "source_url", "published_at", "content_group_id")
    plan = _load_ir_plan(plan_path)
    selected = {tuple(_required_string(item, key) for key in keys) for item in plan}
    actual = {
        tuple(item[key] for key in keys) for item in manifest["records"] if item["source"] == "investor_relations"
    }
    if len(selected) != len(plan) or selected != actual:
        raise CorpusAcquisitionError("requested IR plan differs from immutable corpus selection")
    for item in plan:
        expected_suffix = _raw_suffix(_required_string(item, "source_url"), item.get("raw_suffix"))
        record = next(
            r
            for r in manifest["records"]
            if r["source"] == "investor_relations" and r["source_id"] == item["source_id"]
        )
        if (
            PurePosixPath(record["raw_path"]).suffix != expected_suffix
            or record["source_type"] != "investor_relations_release"
        ):
            raise CorpusAcquisitionError("requested IR representation/source type differs from frozen corpus")
    _, evidence = load_sector_review(corpus, manifest["sector_review_path"], manifest["sector_review_sha256"])
    expected = {"manifest.json", *evidence}
    expected.update(r[key] for r in manifest["records"] for key in ("raw_path", "cleaned_path"))
    if set(_file_inventory(corpus)) != expected:
        raise CorpusAcquisitionError("immutable corpus artifact set changed")
    return corpus


def _file_inventory(root: Path) -> dict[str, str]:
    """Fingerprint the complete predecessor, refusing linked files/directories."""
    if root.is_symlink() or not root.is_dir():
        raise CorpusAcquisitionError(f"missing or linked corpus artifact directory: {root}")
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise CorpusAcquisitionError("corpus inventory must not contain symlinks")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def acquire_sec_records(user_agent: str, *, retrieved_at: datetime) -> tuple[AcquiredCorpusRecord, ...]:
    """Download supported SEC filings for the approved evaluation universe."""
    _validate_sec_user_agent(user_agent)
    _require_timestamp(retrieved_at, "retrieved_at")
    with httpx.Client(follow_redirects=False, timeout=30.0) as client:
        tickers = _fetch_json(client, _SEC_TICKERS_URL, user_agent=user_agent)
        cik_by_ticker = _cik_by_ticker(tickers)
        records: list[AcquiredCorpusRecord] = []
        for ticker in RESEARCH_TICKERS:
            cik = cik_by_ticker.get(ticker)
            if cik is None:
                raise CorpusAcquisitionError(f"SEC ticker map has no CIK for {ticker}")
            submission = _fetch_json(client, _SEC_SUBMISSIONS_URL.format(cik=cik), user_agent=user_agent)
            for filing in _select_sec_filings(ticker, cik, submission):
                raw_content = _fetch_bytes(client, filing.source_url, user_agent=user_agent)
                records.append(
                    AcquiredCorpusRecord(
                        company=ticker,
                        source="sec",
                        source_type="sec_filing",
                        source_id=filing.accession_number,
                        document_type="earnings_release" if filing.form == "8-K" else filing.form,
                        form=filing.form,
                        form_items=filing.form_items,
                        published_at=filing.published_at,
                        retrieved_at=retrieved_at,
                        source_url=filing.source_url,
                        raw_content=raw_content,
                        cleaned_content=_clean_text(raw_content, suffix=".txt", source="sec", form=filing.form),
                        parser_version=SEC_PARSER_VERSION,
                        content_group_id=filing.content_group_id,
                        canonical_for_scoring=True,
                        raw_suffix=".txt",
                    )
                )
                time.sleep(_REQUEST_DELAY_SECONDS)
    return tuple(records)


def acquire_ir_records(plan_path: Path, *, retrieved_at: datetime) -> tuple[AcquiredCorpusRecord, ...]:
    """Download the curated, official investor-relations release plan."""
    _require_timestamp(retrieved_at, "retrieved_at")
    plan = _load_ir_plan(plan_path)
    with httpx.Client(follow_redirects=False, timeout=30.0) as client:
        records = []
        for item in plan:
            source_url = _required_string(item, "source_url")
            _validate_curated_url(source_url)
            raw_content = _fetch_bytes(client, source_url)
            suffix = _raw_suffix(source_url, item.get("raw_suffix"))
            records.append(
                AcquiredCorpusRecord(
                    company=_required_string(item, "company").upper(),
                    source="investor_relations",
                    source_type="investor_relations_release",
                    source_id=_required_string(item, "source_id"),
                    document_type="earnings_release",
                    form=None,
                    form_items=(),
                    published_at=_required_date(item, "published_at"),
                    retrieved_at=retrieved_at,
                    source_url=source_url,
                    raw_content=raw_content,
                    cleaned_content=_clean_text(raw_content, suffix=suffix, source="investor_relations"),
                    parser_version="source-cleaning-v1",
                    content_group_id=_required_string(item, "content_group_id"),
                    canonical_for_scoring=False,
                    raw_suffix=suffix,
                )
            )
    return tuple(records)


def select_canonical_records(records: Iterable[AcquiredCorpusRecord]) -> tuple[AcquiredCorpusRecord, ...]:
    """Prefer SEC evidence in each matched content group without discarding IR records."""
    groups: dict[str, list[AcquiredCorpusRecord]] = {}
    for record in records:
        groups.setdefault(record.content_group_id, []).append(record)
    selected: list[AcquiredCorpusRecord] = []
    for group in groups.values():
        canonical = min(group, key=lambda item: (item.source != "sec", item.source_id, item.raw_content))
        selected.extend(replace(item, canonical_for_scoring=item is canonical) for item in group)
    return tuple(sorted(selected, key=_record_sort_key))


def records_from_selection(data_root: Path, selection_path: Path) -> tuple[AcquiredCorpusRecord, ...]:
    """Materialize exactly the frozen local references, without provider requests."""
    selection_relative = selection_path.relative_to(data_root).as_posix()
    selection = json.loads(contained_file(data_root, selection_relative).read_bytes())
    if selection["manifest_version"] != RESEARCH_SELECTION_VERSION or selection["evaluation_universe"] != list(
        RESEARCH_TICKERS
    ):
        raise CorpusAcquisitionError("selection version/universe does not match the approved corpus")
    manifests = {}
    for entry in selection["inputs"]:
        content = contained_file(data_root, entry["path"]).read_bytes()
        if hashlib.sha256(content).hexdigest() != entry["sha256"]:
            raise CorpusAcquisitionError("frozen selection input manifest checksum mismatch")
        manifests[entry["path"]] = json.loads(content)
    records = []
    for entry in selection["records"]:
        source = entry["source"]
        manifest = manifests[entry["source_manifest"]]
        original = next(
            item
            for item in manifest["documents"]
            if (item["accession_number"] if source == "sec" else item["canonical_filename"]) == entry["source_id"]
        )
        path = contained_file(data_root, entry["raw_path"])
        raw = path.read_bytes()
        published = original["filed_at"] if source == "sec" else original["published_at"]
        if (
            hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]
            or published != entry["published_at"]
            or manifest["ticker"] != entry["company"]
        ):
            raise CorpusAcquisitionError("frozen selection source metadata/checksum mismatch")
        form = original["form"] if source == "sec" else None
        records.append(
            AcquiredCorpusRecord(
                company=entry["company"],
                source=source,
                source_type="sec_filing" if source == "sec" else "investor_relations_transcript",
                source_id=entry["source_id"],
                document_type=entry["document_type"],
                form=form,
                form_items=tuple(original["form_items"]) if form == "8-K" else (),
                published_at=date.fromisoformat(published),
                retrieved_at=datetime.fromisoformat(original["retrieved_at"]),
                source_url=original["source_url"],
                raw_content=raw,
                cleaned_content=_clean_text(raw, suffix=path.suffix.lower(), source=source, form=form),
                parser_version=SEC_PARSER_VERSION if source == "sec" else "source-cleaning-v1",
                content_group_id=(
                    f"{entry['company']}:earnings:{published}"
                    if form == "8-K"
                    else (
                        f"{entry['company']}:{form}:{original['report_date']}"
                        if source == "sec"
                        else f"{entry['company']}:earnings_call:{original['fiscal_period']}"
                    )
                ),
                canonical_for_scoring=True,
                raw_suffix=path.suffix.lower(),
            )
        )
    split = CorpusSplit.from_publications(record.published_at for record in records)
    if (
        selection["corpus_window"] != {"start": split.start.isoformat(), "end": split.cutoff.isoformat()}
        or selection["development_ends"] != split.development_ends.isoformat()
        or selection["held_out_starts"] != split.held_out_starts.isoformat()
    ):
        raise CorpusAcquisitionError("frozen selection split does not derive from its included publications")
    return select_canonical_records(records)


@dataclass(frozen=True, slots=True)
class _SecFiling:
    accession_number: str
    form: str
    form_items: tuple[str, ...]
    published_at: date
    source_url: str
    content_group_id: str


def _select_sec_filings(ticker: str, cik: str, submission: dict[str, object]) -> tuple[_SecFiling, ...]:
    filings = _object(submission.get("filings"), "SEC filings")
    recent = _object(filings.get("recent"), "SEC recent filings")
    forms = _string_list(recent.get("form"), "SEC form")
    filing_dates = _string_list(recent.get("filingDate"), "SEC filingDate")
    accessions = _string_list(recent.get("accessionNumber"), "SEC accessionNumber")
    report_dates = _string_list(recent.get("reportDate"), "SEC reportDate")
    items = _string_list(recent.get("items"), "SEC items")
    columns = (forms, filing_dates, accessions, report_dates, items)
    if len({len(column) for column in columns}) != 1:
        raise CorpusAcquisitionError("SEC recent filings columns have inconsistent lengths")
    selected: list[_SecFiling] = []
    for form, filing_date, accession, report_date, filing_items in zip(*columns, strict=True):
        published_at = _parse_date(filing_date, "SEC filingDate")
        item_values = tuple(item.strip() for item in filing_items.split(",") if item.strip())
        if form not in {"10-K", "10-Q"} and not (form == "8-K" and "2.02" in item_values):
            continue
        directory = accession.replace("-", "")
        selected.append(
            _SecFiling(
                accession_number=accession,
                form=form,
                form_items=item_values if form == "8-K" else (),
                published_at=published_at,
                source_url=_SEC_ARCHIVES_URL.format(cik=int(cik), directory=directory, accession=accession),
                content_group_id=(
                    f"{ticker}:earnings:{published_at.isoformat()}"
                    if form == "8-K"
                    else f"{ticker}:{form}:{_parse_date(report_date, 'SEC reportDate').isoformat()}"
                ),
            )
        )
    return tuple(sorted(selected, key=lambda item: (item.published_at, item.form, item.accession_number)))


def _build_manifest(
    records: tuple[AcquiredCorpusRecord, ...], companies: list[dict[str, object]]
) -> tuple[dict[str, object], tuple[tuple[PurePosixPath, bytes], ...]]:
    artifacts: list[tuple[PurePosixPath, bytes]] = []
    manifest_records = []
    for record in records:
        raw_sha256 = hashlib.sha256(record.raw_content).hexdigest()
        cleaned_bytes = record.cleaned_content.encode("utf-8")
        cleaned_sha256 = hashlib.sha256(cleaned_bytes).hexdigest()
        raw_suffix = _raw_suffix(record.source_url, record.raw_suffix)
        source_id = _safe_component(record.source_id)
        raw_path = PurePosixPath("raw") / record.source / record.company / f"{source_id}{raw_suffix}"
        cleaned_path = PurePosixPath("cleaned") / record.source / record.company / f"{source_id}.txt"
        artifacts.extend(((raw_path, record.raw_content), (cleaned_path, cleaned_bytes)))
        manifest_records.append(
            {
                "record_id": f"{record.source}:{record.source_id}:{raw_sha256}",
                "company": record.company,
                "source": record.source,
                "source_type": record.source_type,
                "source_id": record.source_id,
                "document_type": record.document_type,
                "form": record.form,
                "form_items": list(record.form_items),
                "published_at": record.published_at.isoformat(),
                "retrieved_at": record.retrieved_at.isoformat(),
                "source_url": record.source_url,
                "raw_path": raw_path.as_posix(),
                "raw_sha256": raw_sha256,
                "cleaned_path": cleaned_path.as_posix(),
                "cleaned_sha256": cleaned_sha256,
                "parser_version": record.parser_version,
                "content_group_id": record.content_group_id,
                "canonical_for_scoring": record.canonical_for_scoring,
            }
        )
    split = CorpusSplit.from_publications(record.published_at for record in records)
    return (
        {
            "schema_version": 2,
            "manifest_version": _MANIFEST_VERSION,
            "corpus_window": {"start": split.start.isoformat(), "end": split.cutoff.isoformat()},
            "development_ends": split.development_ends.isoformat(),
            "held_out_starts": split.held_out_starts.isoformat(),
            "companies": companies,
            "records": manifest_records,
        },
        tuple(artifacts),
    )


def _validate_records(records: tuple[AcquiredCorpusRecord, ...]) -> None:
    if not records:
        raise CorpusAcquisitionError("at least one corpus record is required")
    split = CorpusSplit.from_publications(record.published_at for record in records)
    seen_records: set[tuple[str, str, str]] = set()
    groups: dict[str, list[AcquiredCorpusRecord]] = {}
    for record in records:
        if record.company not in RESEARCH_TICKERS:
            raise CorpusAcquisitionError(f"unsupported corpus company: {record.company}")
        _safe_component(record.source_id)
        _validate_record_source(record)
        _require_timestamp(record.retrieved_at, "retrieved_at")
        if not split.start <= record.published_at <= split.cutoff:
            raise CorpusAcquisitionError("corpus record is outside the approved publication window")
        if not record.raw_content or len(record.raw_content) > _MAX_DOWNLOAD_BYTES:
            raise CorpusAcquisitionError("corpus raw content is missing or exceeds the size limit")
        if not record.cleaned_content.strip():
            raise CorpusAcquisitionError("corpus cleaned content is required")
        key = (record.source, record.source_id, hashlib.sha256(record.raw_content).hexdigest())
        if key in seen_records:
            raise CorpusAcquisitionError("corpus records must not duplicate a source revision")
        seen_records.add(key)
        groups.setdefault(record.content_group_id, []).append(record)
    for group_id, members in groups.items():
        if sum(member.canonical_for_scoring for member in members) != 1:
            raise CorpusAcquisitionError(f"content group {group_id} must have exactly one canonical record")


def _validate_record_source(record: AcquiredCorpusRecord) -> None:
    _validate_curated_url(record.source_url)
    if record.source == "sec" and record.source_type == "sec_filing":
        if urlparse(record.source_url).hostname not in {"sec.gov", "www.sec.gov", "data.sec.gov"}:
            raise CorpusAcquisitionError("SEC source URL must use an official SEC host")
        if record.form not in {"10-K", "10-Q", "8-K"}:
            raise CorpusAcquisitionError("unsupported SEC form")
        if record.form in {"10-K", "10-Q"} and (record.document_type != record.form or record.form_items):
            raise CorpusAcquisitionError("SEC 10-K and 10-Q metadata is invalid")
        if record.form == "8-K" and (record.document_type != "earnings_release" or "2.02" not in record.form_items):
            raise CorpusAcquisitionError("SEC 8-K record must be an Item 2.02 earnings release")
        return
    if record.source == "investor_relations" and record.source_type == "investor_relations_release":
        if record.document_type != "earnings_release" or record.form is not None or record.form_items:
            raise CorpusAcquisitionError("investor-relations metadata is invalid")
        return
    if record.source == "investor_relations" and record.source_type == "investor_relations_transcript":
        if record.document_type != "earnings_call_transcript" or record.form is not None or record.form_items:
            raise CorpusAcquisitionError("investor-relations transcript metadata is invalid")
        return
    raise CorpusAcquisitionError("unsupported corpus source type")


def _validate_complete_coverage(records: Iterable[AcquiredCorpusRecord]) -> None:
    grouped: dict[str, set[str]] = {ticker: set() for ticker in RESEARCH_TICKERS}
    sec_earnings_groups: set[tuple[str, str]] = set()
    ir_groups: set[tuple[str, str]] = set()
    for record in records:
        if record.source == "sec":
            grouped[record.company].add(record.form or "")
            if record.form == "8-K":
                sec_earnings_groups.add((record.company, record.content_group_id))
        else:
            grouped[record.company].add("investor_relations")
            if record.document_type == "earnings_release":
                ir_groups.add((record.company, record.content_group_id))
    expected = {"10-K", "10-Q", "8-K", "investor_relations"}
    missing = {company: sorted(expected - kinds) for company, kinds in grouped.items() if expected - kinds}
    if missing:
        raise CorpusAcquisitionError(f"incomplete source coverage: {missing}")
    if not ir_groups <= sec_earnings_groups:
        raise CorpusAcquisitionError("each investor-relations release must link to a matching SEC Item 2.02 record")


def _fetch_json(client: httpx.Client, url: str, *, user_agent: str) -> dict[str, object]:
    content = _fetch_bytes(client, url, user_agent=user_agent)
    try:
        value = json.loads(content)
    except json.JSONDecodeError as error:
        raise CorpusAcquisitionError(f"SEC response is not valid JSON: {url}") from error
    return _object(value, "SEC response")


def _fetch_bytes(client: httpx.Client, url: str, *, user_agent: str | None = None) -> bytes:
    _validate_curated_url(url)
    headers = {"User-Agent": user_agent} if user_agent is not None else None
    try:
        with client.stream("GET", url, headers=headers) as response:
            response.raise_for_status()
            content = b"".join(response.iter_bytes(chunk_size=64 * 1024))
    except httpx.HTTPError as error:
        raise CorpusAcquisitionError(f"download failed for {url}: {type(error).__name__}") from error
    if not content or len(content) > _MAX_DOWNLOAD_BYTES:
        raise CorpusAcquisitionError(f"download is empty or exceeds the size limit: {url}")
    return content


def _cik_by_ticker(payload: dict[str, object]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in payload.values():
        row = _object(value, "SEC ticker entry")
        ticker = _required_string(row, "ticker").upper()
        cik = row.get("cik_str")
        if not isinstance(cik, int) or cik < 1:
            raise CorpusAcquisitionError("SEC ticker entry has an invalid cik_str")
        if ticker in RESEARCH_TICKERS:
            result[ticker] = f"{cik:010d}"
    return result


def _load_ir_plan(path: Path) -> tuple[dict[str, object], ...]:
    if path.is_symlink() or not path.is_file():
        raise CorpusAcquisitionError(f"IR plan must be a regular file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorpusAcquisitionError(f"cannot read IR plan: {path}") from error
    if not isinstance(value, list):
        raise CorpusAcquisitionError("IR plan must be a JSON list")
    return tuple(_object(item, "IR plan entry") for item in value)


def _clean_text(raw_content: bytes, *, suffix: str, source: str, form: str | None = None) -> str:
    if suffix == ".pdf":
        try:
            reader = PdfReader(BytesIO(raw_content))
            if reader.is_encrypted:
                raise CorpusAcquisitionError("encrypted IR PDFs are unsupported")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except CorpusAcquisitionError:
            raise
        except Exception as error:
            raise CorpusAcquisitionError("cannot extract text from IR PDF") from error
    else:
        try:
            text = raw_content.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CorpusAcquisitionError("source content is not UTF-8") from error
    try:
        return _clean_content(text, source=source, form=form)
    except ValueError as error:
        raise CorpusAcquisitionError("source content failed the readability gate") from error


def _record_sort_key(record: AcquiredCorpusRecord) -> tuple[object, ...]:
    return (
        record.company,
        record.published_at,
        record.source,
        record.source_id,
        hashlib.sha256(record.raw_content).hexdigest(),
    )


def _raw_suffix(source_url: str, specified: object) -> str:
    if specified is not None:
        if not isinstance(specified, str):
            raise CorpusAcquisitionError("raw_suffix must be a string")
        suffix = specified.lower()
    else:
        suffix = PurePosixPath(urlparse(source_url).path).suffix.lower() or ".html"
    if suffix not in {".html", ".htm", ".pdf", ".txt"}:
        raise CorpusAcquisitionError(f"unsupported raw source type: {suffix}")
    return suffix


def _safe_output_path(root: Path, relative_path: PurePosixPath) -> Path:
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise CorpusAcquisitionError("output path must be a safe relative path")
    path = root.joinpath(*relative_path.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as error:
        raise CorpusAcquisitionError("output path escapes the corpus directory") from error
    return path


def _safe_component(value: str) -> str:
    if _SAFE_FILE_COMPONENT.fullmatch(value) is None:
        raise CorpusAcquisitionError(f"unsafe source identifier: {value}")
    return value


def _validate_sec_user_agent(value: str) -> None:
    if not value.strip() or len(value) > 512 or "\r" in value or "\n" in value or _CONTACT_EMAIL.search(value) is None:
        raise CorpusAcquisitionError("SEC_USER_AGENT must be descriptive and include a contact email")


def _validate_curated_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CorpusAcquisitionError("source URLs must be credential-free HTTPS URLs")
    if parsed.hostname in {"localhost", "localhost.localdomain"} or parsed.hostname.endswith(".local"):
        raise CorpusAcquisitionError("source URLs must not target local hosts")
    try:
        address = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        return
    if not address.is_global:
        raise CorpusAcquisitionError("source URLs must not target non-public IP addresses")


def _required_string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item.strip():
        raise CorpusAcquisitionError(f"{key} is required")
    return item


def _required_date(value: Mapping[str, object], key: str) -> date:
    return _parse_date(_required_string(value, key), key)


def _parse_date(value: str, name: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CorpusAcquisitionError(f"{name} must be an ISO date") from error
    if value != parsed.isoformat():
        raise CorpusAcquisitionError(f"{name} must be an ISO date")
    return parsed


def _require_timestamp(value: datetime, name: str) -> None:
    if value.tzinfo is None:
        raise CorpusAcquisitionError(f"{name} must include a timezone")


def _object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CorpusAcquisitionError(f"{name} must be an object")
    return cast(dict[str, object], value)


def _string_list(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CorpusAcquisitionError(f"{name} must be a string list")
    return tuple(value)


def _encode_manifest(manifest: dict[str, object]) -> bytes:
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


def main() -> None:
    """Acquire the final cache from official SEC and curated IR inputs."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ir-plan", type=Path, help="Legacy network-based official IR release plan JSON")
    mode.add_argument("--selection", type=Path, help="Frozen local selection JSON (default: current cache selection)")
    parser.add_argument(
        "--sector-review",
        type=Path,
        help="Sector evidence to validate against the frozen corpus; required for --ir-plan",
    )
    parser.add_argument("--sec-reviews", type=Path, nargs="+", help="Reviewed SEC extraction indexes")
    parser.add_argument("--sec-findings", type=Path, help="Final bounded manual extraction findings")
    parser.add_argument(
        "--data-root",
        type=Path,
        default=None,
        help="Separate research-data repository root",
    )
    arguments = parser.parse_args()
    configured_root = arguments.data_root or (Path(value) if (value := os.environ.get("SENTIMENT_DATA_ROOT")) else None)
    if configured_root is None:
        raise CorpusAcquisitionError("SENTIMENT_DATA_ROOT or --data-root is required")
    configured_root = configured_root.resolve()
    if arguments.ir_plan is not None:
        if arguments.sector_review is None:
            parser.error("--sector-review is required with --ir-plan")
        existing = configured_root / "data/corpora" / _MANIFEST_VERSION
        if existing.exists() or existing.is_symlink():
            destination = verify_ir_plan_corpus(configured_root, existing, arguments.ir_plan, arguments.sector_review)
            print(f"Verified immutable corpus: {destination}")
            return
        retrieved_at = datetime.now(timezone.utc)
        user_agent = os.environ.get("SEC_USER_AGENT", "")
        records = select_canonical_records(
            (
                *acquire_sec_records(user_agent, retrieved_at=retrieved_at),
                *acquire_ir_records(arguments.ir_plan, retrieved_at=retrieved_at),
            )
        )
        split = CorpusSplit.from_publications(record.published_at for record in records)
        records = tuple(record for record in records if record.published_at >= split.start)
    else:
        selection = (
            arguments.selection or configured_root / f"data/research_selection/{RESEARCH_SELECTION_VERSION}.json"
        )
        reviews = tuple(
            arguments.sec_reviews
            or (
                configured_root / "data/extraction_reviews/sec-v2-round5/review.json",
                configured_root / "data/extraction_reviews/sec-v2-edge-round4/review.json",
            )
        )
        findings = arguments.sec_findings or configured_root / "data/extraction_reviews/sec-v2-round5/findings-final.md"
        destination = publish_cleaned_corpus(
            configured_root,
            selection_path=selection,
            review_paths=reviews,
            findings_path=findings,
            sector_review_path=arguments.sector_review,
        )
        print(f"Published verified immutable cleaned corpus: {destination}")
        return
    _validate_complete_coverage(records)
    destination = write_corpus(configured_root, records, sector_review_path=arguments.sector_review)
    print(f"Wrote immutable corpus: {destination}")


if __name__ == "__main__":
    main()
