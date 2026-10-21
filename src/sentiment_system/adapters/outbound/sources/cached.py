"""Offline source adapter for the separate SEC and investor-relations cache."""

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Literal, cast
from urllib.parse import urlparse

from pypdf import PdfReader

from sentiment_system.domain.companies import APPROVED_COMPANIES
from sentiment_system.domain.documents import SourceArtifact, SourceDocument, SourceProvenance
from sentiment_system.domain.research import (
    FINAL_CORPUS_VERSION,
    RESEARCH_SELECTION_VERSION,
    RESEARCH_TICKERS,
    SECTOR_BENCHMARKS,
    CorpusSplit,
)

from .sector_metadata import load_sector_review

_FINAL_MANIFEST_VERSION = FINAL_CORPUS_VERSION
_FINAL_COMPANIES = RESEARCH_TICKERS
_FINAL_RAW_SUFFIXES = frozenset({".html", ".htm", ".pdf", ".txt"})
_MAX_CACHED_SOURCE_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _FinalCompany:
    ticker: str
    sector: str
    benchmark: str
    sector_source_url: str
    sector_retrieved_at: datetime


class CacheManifestError(ValueError):
    """Raised when a cache manifest or referenced source file is invalid."""


class CachedCorpusDocumentSource:
    """Load immutable local SEC and curated IR documents without network access."""

    def __init__(self, root: Path, *, scope: Literal["operational", "frozen"] = "operational") -> None:
        if scope not in {"operational", "frozen"}:
            raise CacheManifestError("source scope must be operational or frozen")
        self._root = root
        self._evaluation_documents = self._load_final_corpus() or ()
        manifest = root / "data" / "corpora" / _FINAL_MANIFEST_VERSION / "manifest.json"
        self.manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.is_file() else None
        if scope == "frozen":
            if not self._evaluation_documents:
                raise CacheManifestError("frozen corpus manifest and documents are required")
            self._documents = self._evaluation_documents
            return
        # Preserve the broad operational cache. Prefer frozen lineage only for the
        # exact same source revision; a different revision remains separate evidence.
        documents: dict[tuple[str, str, str, str], SourceDocument] = {}
        for document in (*self._load_sec(), *self._load_ir(), *self._load_sec_history(), *self._evaluation_documents):
            checksum = document.original_byte_sha256
            if checksum is None:
                raise CacheManifestError("cached sources require verified original bytes")
            key = (document.company, document.source, document.source_id, checksum)
            previous = documents.get(key)
            if previous is not None and previous.published_at != document.published_at:
                # Legacy quarterly snapshots used fiscal report dates. Authoritative
                # filing/history or frozen metadata takes precedence over that defect.
                if previous.artifact is not None:
                    if previous.artifact.path.startswith("data/sec/history/"):
                        raise CacheManifestError("conflicting publication metadata for the same source revision")
            documents[key] = document
        self._documents = tuple(documents.values())

    def fetch_evaluation_documents(self) -> tuple[SourceDocument, ...]:
        """Return only explicit immutable research-manifest records, never the broad cache."""
        return tuple(sorted(self._evaluation_documents, key=_document_sort_key))

    def fetch_documents(
        self,
        *,
        company: str | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> tuple[SourceDocument, ...]:
        documents = (
            document
            for document in self._documents
            if (company is None or document.company == company.upper())
            and (published_after is None or document.published_at > published_after)
            and (published_before is None or document.published_at < published_before)
        )
        return tuple(sorted(documents, key=_document_sort_key))

    def _load_sec_history(self) -> tuple[SourceDocument, ...]:
        documents = []
        metadata: dict[tuple[str, str, str], tuple[object, ...]] = {}
        supported = {company.ticker for company in APPROVED_COMPANIES}
        for manifest_path in sorted((self._root / "data/sec/history").glob("*/manifest.json")):
            _contained_source(self._root, manifest_path.relative_to(self._root).as_posix())
            payload = _read_json(manifest_path)
            ticker = _string(payload, "ticker")
            if ticker != manifest_path.parent.name or ticker not in supported:
                raise CacheManifestError("history manifest company mismatch/unsupported company")
            if payload.get("schema_version") != 1 or not isinstance(payload.get("documents"), list):
                raise CacheManifestError("invalid SEC history manifest")
            for item in payload["documents"]:
                if not isinstance(item, dict):
                    raise CacheManifestError("invalid history record")
                form = _string(item, "form")
                if form not in {"10-K", "10-Q", "8-K"}:
                    continue
                if item.get("status") not in {"downloaded", "existing", "pending", "failed"}:
                    raise CacheManifestError("invalid history download status")
                if item.get("status") not in {"downloaded", "existing"}:
                    continue
                published = _final_date(item, "published_at")
                if published != _final_date(item, "filed_at"):
                    raise CacheManifestError("history publication date disagrees with filing date")
                path, raw = _verified_cache_file(
                    self._root,
                    _string(item, "raw_path"),
                    _final_sha256(item, "raw_sha256"),
                    allowed_suffixes=_FINAL_RAW_SUFFIXES,
                )
                source_id = _string(item, "accession_number")
                url = _final_https_url(item, "source_url")
                if urlparse(url).hostname not in {"sec.gov", "www.sec.gov", "data.sec.gov"}:
                    raise CacheManifestError("history source must use an official SEC host")
                items = _final_string_list(item, "form_items")
                key = (ticker, source_id, item["raw_sha256"])
                identity_metadata = (published, form, items, url)
                if key in metadata and metadata[key] != identity_metadata:
                    raise CacheManifestError("conflicting history metadata for one source revision")
                metadata[key] = identity_metadata
                content = _source_text(path, raw)
                documents.append(
                    SourceDocument(
                        document_id=f"sec:{source_id}:{hashlib.sha256(raw).hexdigest()}",
                        source_id=source_id,
                        company=ticker,
                        source="sec",
                        published_at=published,
                        document_type="earnings_release" if form == "8-K" and "2.02" in items else form,
                        raw_content=content,
                        cleaned_content="",
                        manifest_version="sec-history-v1",
                        artifact=SourceArtifact(
                            sha256=hashlib.sha256(raw).hexdigest(),
                            path=item["raw_path"],
                            source_url=url,
                            retrieved_at=_final_timestamp(item, "retrieved_at"),
                            form=form,
                            form_items=items,
                        ),
                    )
                )
        return tuple(sorted(documents, key=_document_sort_key))

    def _load_final_corpus(self) -> tuple[SourceDocument, ...] | None:
        corpus_root = self._root / "data" / "corpora" / _FINAL_MANIFEST_VERSION
        if corpus_root.is_symlink() or (corpus_root.exists() and not corpus_root.is_dir()):
            raise CacheManifestError(f"invalid final corpus directory: {corpus_root}")
        if not corpus_root.is_dir():
            return None
        manifest_path = corpus_root / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise CacheManifestError(f"missing regular final corpus manifest: {manifest_path}")
        return _load_final_manifest(manifest_path, corpus_root)

    def _load_sec(self) -> tuple[SourceDocument, ...]:
        manifest_path = self._root / "data" / "sec" / "manifests" / "previous_calendar_quarter_earnings_releases.json"
        if not manifest_path.is_file():
            return ()
        payload = _read_json(manifest_path)
        manifest_version = _manifest_version(payload, "sec-v1")
        releases = payload.get("releases")
        if not isinstance(releases, list):
            raise CacheManifestError(f"{manifest_path} has no releases list")
        documents = []
        for release in releases:
            if not isinstance(release, dict):
                raise CacheManifestError(f"{manifest_path} contains an invalid release")
            ticker = _string(release, "ticker")
            source_id = _string(release, "accession_number")
            path = self._root / "data" / "sec" / "earnings_releases" / f"{ticker}_{source_id}.txt"
            path = _contained_source(self._root, path.relative_to(self._root).as_posix())
            actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            expected_hash = release.get("raw_sha256")
            if expected_hash is not None:
                if not path.is_file():
                    raise CacheManifestError(f"missing cached source file: {path}")
                if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                    raise CacheManifestError(f"invalid raw_sha256 for {path}")
                if actual_hash != expected_hash:
                    raise CacheManifestError(f"checksum mismatch for {path}")
            documents.append(
                _document(
                    path=path,
                    document_id=f"sec:{source_id}",
                    source_id=source_id,
                    company=ticker,
                    source="sec",
                    published_at=date.fromisoformat(
                        str(release.get("published_at") or release.get("filed_at") or _string(release, "report_date"))
                    ),
                    document_type=str(release.get("document_type") or "earnings_release"),
                    manifest_version=manifest_version,
                    artifact=SourceArtifact(
                        sha256=actual_hash,
                        path=path.relative_to(self._root).as_posix(),
                        source_url=release.get("source_url"),
                        form="8-K",
                        form_items=("2.02",),
                    ),
                )
            )
        return tuple(documents)

    def _load_ir(self) -> tuple[SourceDocument, ...]:
        root = self._root / "data" / "company_communications" / "curated"
        documents = []
        for manifest_path in sorted(root.glob("*/manifest.csv")):
            _contained_source(self._root, manifest_path.relative_to(self._root).as_posix())
            with manifest_path.open(encoding="utf-8", newline="") as handle:
                for row in csv.DictReader(handle):
                    filename = _row_string(row, "canonical_filename", manifest_path)
                    ticker = _row_string(row, "ticker", manifest_path)
                    path = _contained_source(
                        self._root, (manifest_path.parent / filename).relative_to(self._root).as_posix()
                    )
                    expected_hash = _row_string(row, "sha256", manifest_path)
                    actual_hash = hashlib.sha256(path.read_bytes()).hexdigest()
                    if actual_hash != expected_hash:
                        raise CacheManifestError(f"checksum mismatch for {path}")
                    content = _read_text(path)
                    documents.append(
                        SourceDocument(
                            document_id=f"investor_relations:{filename}",
                            source_id=filename,
                            company=ticker,
                            source="investor_relations",
                            published_at=date.fromisoformat(_row_string(row, "published_at", manifest_path)),
                            document_type=_row_string(row, "document_type", manifest_path),
                            raw_content=content,
                            cleaned_content=content,
                            manifest_version="ir-v1",
                            artifact=SourceArtifact(
                                sha256=actual_hash,
                                path=path.relative_to(self._root).as_posix(),
                                source_url=row.get("source_url") or None,
                            ),
                        )
                    )
        return tuple(documents)


def _load_final_manifest(
    manifest_path: Path, corpus_root: Path, *, expected_version: str = _FINAL_MANIFEST_VERSION
) -> tuple[SourceDocument, ...]:
    payload = _read_json(manifest_path)
    _final_integer(payload, "schema_version", expected=2)
    if _final_string(payload, "manifest_version") != expected_version:
        raise CacheManifestError(f"final corpus manifest_version must be {expected_version}")
    companies = _parse_final_companies(payload.get("companies"))
    records = payload.get("records")
    if not isinstance(records, list) or not records:
        raise CacheManifestError("final corpus records must be a non-empty list")

    documents = tuple(_parse_final_record(value, corpus_root, companies, expected_version) for value in records)
    split = CorpusSplit.from_publications(document.published_at for document in documents)
    window = _final_object(payload.get("corpus_window"), "corpus_window")
    if (_final_date(window, "start"), _final_date(window, "end")) != (split.start, split.cutoff):
        raise CacheManifestError("final corpus_window must derive from the latest included publication")
    if _final_date(payload, "development_ends") != split.development_ends:
        raise CacheManifestError("final corpus development_ends must derive from the cutoff")
    if _final_date(payload, "held_out_starts") != split.held_out_starts:
        raise CacheManifestError(
            "final corpus held_out_starts must be the first included publication after development"
        )
    if any(document.published_at < split.start for document in documents):
        raise CacheManifestError("final corpus record is outside the approved publication window")
    try:
        reviewed, _ = load_sector_review(
            corpus_root, _final_string(payload, "sector_review_path"), _final_sha256(payload, "sector_review_sha256")
        )
        if {item["ticker"]: _parse_final_company(item) for item in reviewed} != companies:
            raise ValueError("company metadata disagrees with downloaded sector evidence")
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise CacheManifestError(f"invalid final corpus sector evidence: {error}") from error
    record_ids = {document.provenance.manifest_record_id for document in documents if document.provenance is not None}
    source_versions = {
        (document.source, document.source_id, document.provenance.raw_sha256)
        for document in documents
        if document.provenance is not None
    }
    if len(record_ids) != len(documents):
        raise CacheManifestError("final corpus record IDs must be unique")
    if len(source_versions) != len(documents):
        raise CacheManifestError("final corpus source revisions must be unique by source ID and raw hash")
    _validate_canonical_groups(documents)
    if "cleaning_provenance" in payload:
        _validate_cleaning_provenance(payload, corpus_root)
    return documents


def _validate_cleaning_provenance(payload: dict[str, Any], corpus_root: Path) -> None:
    """Verify embedded publication lineage without depending on external history."""
    provenance = _final_object(payload["cleaning_provenance"], "cleaning_provenance")
    entries = [
        provenance.get(key) for key in ("selection", "predecessor", "findings", "predecessor_inventory", "publication")
    ]
    for key in ("selection_inputs", "reviews"):
        values = provenance.get(key)
        if not isinstance(values, list):
            raise CacheManifestError(f"cleaning provenance {key} must be a list")
        entries.extend(values)
    for value in entries:
        entry = _final_object(value, "cleaning provenance artifact")
        _verified_cache_file(
            corpus_root,
            _final_string(entry, "path"),
            _final_sha256(entry, "sha256"),
            allowed_suffixes=frozenset({".json", ".md"}),
        )


def _parse_final_companies(value: object) -> dict[str, _FinalCompany]:
    if not isinstance(value, list):
        raise CacheManifestError("final corpus companies must be a list")
    companies = tuple(_parse_final_company(item) for item in value)
    if {company.ticker for company in companies} != set(_FINAL_COMPANIES) or len(companies) != len(_FINAL_COMPANIES):
        raise CacheManifestError("final corpus companies must match the approved evaluation universe")
    for company in companies:
        if company.benchmark != SECTOR_BENCHMARKS.get(company.sector, "SPY"):
            raise CacheManifestError(f"final corpus sector metadata is invalid for {company.ticker}")
    return {company.ticker: company for company in companies}


def _parse_final_company(value: object) -> _FinalCompany:
    company = _final_object(value, "company")
    if _final_boolean(company, "evaluation_member") is not True:
        raise CacheManifestError("final corpus companies must be evaluation members")
    return _FinalCompany(
        ticker=_final_string(company, "ticker").upper(),
        sector=_final_string(company, "sector"),
        benchmark=_final_string(company, "benchmark"),
        sector_source_url=_final_https_url(company, "sector_source_url"),
        sector_retrieved_at=_final_timestamp(company, "sector_retrieved_at"),
    )


def _parse_final_record(
    value: object,
    corpus_root: Path,
    companies: dict[str, _FinalCompany],
    manifest_version: str,
) -> SourceDocument:
    record = _final_object(value, "record")
    source = _final_string(record, "source")
    source_type = _final_string(record, "source_type")
    source_id = _final_string(record, "source_id")
    company_name = _final_string(record, "company").upper()
    company = companies.get(company_name)
    if company is None:
        raise CacheManifestError(f"final corpus record has an unsupported company: {company_name}")
    document_type = _final_string(record, "document_type")
    form = _final_optional_string(record, "form")
    form_items = _final_string_list(record, "form_items")
    _validate_source_record(
        source=source,
        source_type=source_type,
        source_url=_final_https_url(record, "source_url"),
        document_type=document_type,
        form=form,
        form_items=form_items,
    )
    published_at = _final_date(record, "published_at")
    raw_path, raw_bytes = _verified_cache_file(
        corpus_root,
        _final_string(record, "raw_path"),
        _final_sha256(record, "raw_sha256"),
        allowed_suffixes=_FINAL_RAW_SUFFIXES,
    )
    cleaned_path, cleaned_bytes = _verified_cache_file(
        corpus_root,
        _final_string(record, "cleaned_path"),
        _final_sha256(record, "cleaned_sha256"),
        allowed_suffixes=frozenset({".txt"}),
    )
    raw_content = _source_text(raw_path, raw_bytes)
    cleaned_content = _utf8_text(cleaned_path, cleaned_bytes)
    provenance = SourceProvenance(
        manifest_record_id=_final_string(record, "record_id"),
        source_url=_final_https_url(record, "source_url"),
        retrieved_at=_final_timestamp(record, "retrieved_at"),
        raw_path=_final_string(record, "raw_path"),
        raw_sha256=_final_sha256(record, "raw_sha256"),
        cleaned_path=_final_string(record, "cleaned_path"),
        cleaned_sha256=_final_sha256(record, "cleaned_sha256"),
        parser_version=_final_string(record, "parser_version"),
        source_type=source_type,
        form=form,
        form_items=form_items,
        content_group_id=_final_string(record, "content_group_id"),
        canonical_for_scoring=_final_boolean(record, "canonical_for_scoring"),
        evaluation_member=True,
        sector=company.sector,
        sector_source_url=company.sector_source_url,
        sector_retrieved_at=company.sector_retrieved_at,
    )
    # Cleaning revisions share original bytes but must never collide in persisted
    # documents/chunks. Keep the predecessor's historical identity unchanged.
    revision_id = f"{source}:{source_id}:{provenance.raw_sha256}"
    return SourceDocument(
        document_id=(
            revision_id if manifest_version == RESEARCH_SELECTION_VERSION else f"{manifest_version}:{revision_id}"
        ),
        source_id=source_id,
        company=company_name,
        source=source,
        published_at=published_at,
        document_type=document_type,
        raw_content=raw_content,
        cleaned_content=cleaned_content,
        manifest_version=manifest_version,
        provenance=provenance,
    )


def _validate_source_record(
    *,
    source: str,
    source_type: str,
    source_url: str,
    document_type: str,
    form: str | None,
    form_items: tuple[str, ...],
) -> None:
    if source == "sec" and source_type == "sec_filing":
        if urlparse(source_url).hostname not in {"sec.gov", "www.sec.gov", "data.sec.gov"}:
            raise CacheManifestError("SEC source_url must use an official SEC host")
        if form not in {"10-K", "10-Q", "8-K"}:
            raise CacheManifestError("SEC form is unsupported")
        if form in {"10-K", "10-Q"} and (document_type != form or form_items):
            raise CacheManifestError("SEC 10-K and 10-Q records must use their form as document_type")
        if form == "8-K" and (document_type != "earnings_release" or "2.02" not in form_items):
            raise CacheManifestError("SEC 8-K records must be Item 2.02 earnings releases")
        return
    if source == "investor_relations" and source_type == "investor_relations_release":
        if document_type != "earnings_release" or form is not None or form_items:
            raise CacheManifestError("investor-relations records must be earnings releases without SEC form metadata")
        return
    if source == "investor_relations" and source_type == "investor_relations_transcript":
        if document_type != "earnings_call_transcript" or form is not None or form_items:
            raise CacheManifestError("investor-relations transcripts must not contain SEC form metadata")
        return
    raise CacheManifestError("final corpus record has an unsupported source type")


def _validate_canonical_groups(documents: tuple[SourceDocument, ...]) -> None:
    groups: dict[str, list[SourceDocument]] = {}
    for document in documents:
        provenance = document.provenance
        if provenance is None:
            raise CacheManifestError("final corpus document is missing provenance")
        groups.setdefault(provenance.content_group_id, []).append(document)
    for group_id, records in groups.items():
        if sum(record.provenance is not None and record.provenance.canonical_for_scoring for record in records) != 1:
            raise CacheManifestError(f"content group {group_id} must have exactly one canonical record")


def _verified_cache_file(
    corpus_root: Path,
    raw_path: str,
    expected_hash: str,
    *,
    allowed_suffixes: frozenset[str],
) -> tuple[Path, bytes]:
    relative_path = PurePosixPath(raw_path)
    if relative_path.is_absolute() or any(part in {"", ".", ".."} for part in relative_path.parts):
        raise CacheManifestError(f"cached path must be a safe relative path: {raw_path}")
    path = corpus_root.joinpath(*relative_path.parts)
    if path.suffix.lower() not in allowed_suffixes:
        raise CacheManifestError(f"cached source has an unsupported file type: {raw_path}")
    try:
        resolved_path = path.resolve(strict=True)
        resolved_path.relative_to(corpus_root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise CacheManifestError(f"cached path escapes the corpus directory: {raw_path}") from error
    if path.is_symlink() or not path.is_file():
        raise CacheManifestError(f"missing regular cached source file: {path}")
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CacheManifestError(f"cannot read cached source file: {path}") from error
    if len(content) > _MAX_CACHED_SOURCE_BYTES:
        raise CacheManifestError(f"cached source file exceeds {_MAX_CACHED_SOURCE_BYTES} bytes: {path}")
    if hashlib.sha256(content).hexdigest() != expected_hash:
        raise CacheManifestError(f"checksum mismatch for {path}")
    return path, content


def _source_text(path: Path, content: bytes) -> str:
    if path.suffix.lower() != ".pdf":
        return _utf8_text(path, content)
    try:
        reader = PdfReader(BytesIO(content))
        if reader.is_encrypted:
            raise CacheManifestError(f"encrypted PDF source is unsupported: {path}")
        extracted = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    except CacheManifestError:
        raise
    except Exception as error:
        raise CacheManifestError(f"cannot extract text from cached PDF source: {path}") from error
    if not extracted:
        raise CacheManifestError(f"cached source file has no text: {path}")
    return extracted


def _utf8_text(path: Path, content: bytes) -> str:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CacheManifestError(f"cached source file is not UTF-8: {path}") from error
    if not text.strip():
        raise CacheManifestError(f"cached source file has no text: {path}")
    return text


def _final_object(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise CacheManifestError(f"final corpus {name} must be an object")
    return cast(dict[str, object], value)


def _final_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CacheManifestError(f"final corpus field {key} is required")
    return value


def _final_optional_string(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise CacheManifestError(f"final corpus field {key} must be a non-empty string or null")
    return value


def _final_boolean(payload: dict[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise CacheManifestError(f"final corpus field {key} must be a boolean")
    return value


def _final_integer(payload: dict[str, Any], key: str, *, expected: int) -> None:
    if payload.get(key) != expected:
        raise CacheManifestError(f"final corpus field {key} must be {expected}")


def _final_string_list(payload: dict[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise CacheManifestError(f"final corpus field {key} must be a string list")
    return tuple(value)


def _final_sha256(payload: dict[str, object], key: str) -> str:
    value = _final_string(payload, key)
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise CacheManifestError(f"final corpus field {key} must be a lowercase SHA-256 hash")
    return value


def _final_date(payload: dict[str, object], key: str) -> date:
    value = _final_string(payload, key)
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CacheManifestError(f"final corpus field {key} must be an ISO date") from error
    if value != parsed.isoformat():
        raise CacheManifestError(f"final corpus field {key} must be an ISO date")
    return parsed


def _final_timestamp(payload: dict[str, object], key: str) -> datetime:
    value = _final_string(payload, key)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise CacheManifestError(f"final corpus field {key} must be an ISO timestamp") from error
    if parsed.tzinfo is None:
        raise CacheManifestError(f"final corpus field {key} must include a timezone")
    return parsed


def _final_https_url(payload: dict[str, object], key: str) -> str:
    value = _final_string(payload, key)
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise CacheManifestError(f"final corpus field {key} must be an HTTPS URL without credentials")
    return value


def _document(**values: object) -> SourceDocument:
    path = values.pop("path")
    if not isinstance(path, Path) or not path.is_file():
        raise CacheManifestError(f"missing cached source file: {path}")
    content = _read_text(path)
    return SourceDocument(raw_content=content, cleaned_content=content, **values)  # type: ignore[arg-type]


def _document_sort_key(document: SourceDocument) -> tuple[object, ...]:
    return (
        document.published_at,
        document.source,
        document.source_id,
        document.company,
        document.original_byte_sha256 or "",
        document.document_id,
        document.artifact.path if document.artifact else "",
    )


def _contained_source(root: Path, relative: str) -> Path:
    path = root / relative
    if Path(relative).is_absolute() or ".." in Path(relative).parts or path.is_symlink():
        raise CacheManifestError("source path must be a safe regular relative file")
    if not path.resolve().is_relative_to(root.resolve()) or not path.is_file():
        raise CacheManifestError("source file is missing or escapes data root")
    return path


def _read_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        content = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages).strip()
    else:
        content = path.read_text(encoding="utf-8")
    if not content.strip():
        raise CacheManifestError(f"cached source file has no text: {path}")
    return content


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CacheManifestError(f"cannot read cache manifest: {path}") from error
    if not isinstance(payload, dict):
        raise CacheManifestError(f"{path} must contain an object")
    return payload


def _manifest_version(payload: dict[str, Any], default: str) -> str:
    value = payload.get("manifest_version", default)
    return value if isinstance(value, str) and value.strip() else default


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CacheManifestError(f"manifest field {key} is required")
    return value


def _row_string(row: dict[str, str], key: str, path: Path) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value.strip():
        raise CacheManifestError(f"{path} field {key} is required")
    return value
