"""Use case for loading, cleaning, normalizing, and storing source documents."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from hashlib import sha256

from bs4 import BeautifulSoup

from sentiment_system.application.ports.document_sources import DocumentSource
from sentiment_system.application.ports.repositories import ChunkRepository, DocumentRepository
from sentiment_system.application.use_cases.sec_content import (
    SEC_PARSER_VERSION,
    _parts,
    sec_html_to_text,
    select_sec_content,
)
from sentiment_system.domain.documents import DocumentChunk, SourceDocument

TokenCounter = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class IngestionResult:
    """Documents and chunks produced by one deterministic ingestion pass."""

    documents: tuple[SourceDocument, ...]
    chunks: tuple[DocumentChunk, ...]
    processing_config_version: str


class ContentQualityError(ValueError):
    """Raised when a source document has no sufficiently readable content."""


class IngestDocuments:
    """Normalize fixture documents, create chunks, and persist both values."""

    def __init__(
        self,
        source: DocumentSource,
        document_repository: DocumentRepository,
        chunk_repository: ChunkRepository,
        *,
        processing_config_version: str,
        token_counter: TokenCounter,
    ) -> None:
        if not processing_config_version.strip():
            raise ValueError("processing_config_version is required")
        self._source = source
        self._document_repository = document_repository
        self._chunk_repository = chunk_repository
        self._processing_config_version = processing_config_version
        self._token_counter = token_counter

    def run(
        self,
        *,
        company: str | None = None,
        published_after: date | None = None,
        published_before: date | None = None,
    ) -> IngestionResult:
        documents: list[SourceDocument] = []
        chunks: list[DocumentChunk] = []
        for source_document in self._source.fetch_documents(
            company=company,
            published_after=published_after,
            published_before=published_before,
        ):
            document = _normalize_document(source_document)
            document = self._document_repository.save(document)
            document_chunks = (
                _chunk_document(
                    document,
                    processing_config_version=self._processing_config_version,
                    token_counter=self._token_counter,
                )
                if source_document.provenance is None or source_document.provenance.canonical_for_scoring
                else ()
            )
            for chunk in document_chunks:
                chunks.append(self._chunk_repository.save(chunk))
            documents.append(document)

        return IngestionResult(tuple(documents), tuple(chunks), self._processing_config_version)


_SEC_XBRL = re.compile(r"<XBRL>.*?</XBRL>", re.IGNORECASE | re.DOTALL)
_HTML_MARKUP = re.compile(r"<[A-Za-z][^>]*>")
_PAGE_MARKER = re.compile(r"^(?:page\s+\d+|\d+\s+of\s+\d+)$", re.IGNORECASE)
_NAVIGATION_MARKER = re.compile(
    r"^(?:back to top|contents|home|next|previous|skip to main content|table of contents)$", re.IGNORECASE
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ABBREVIATIONS = {"e.g.", "i.e.", "etc.", "inc.", "ltd.", "co.", "corp.", "u.s.", "u.k."}
_IGNORED_TAGS = {"head", "script", "style", "svg"}


def _normalize_document(document: SourceDocument) -> SourceDocument:
    cleaned_content = document.cleaned_content
    cleaning_version = SEC_PARSER_VERSION if document.source == "sec" else "source-cleaning-v1"
    if document.provenance is None:
        form = (
            document.artifact.form
            if document.artifact
            else (document.document_type if document.document_type in {"10-K", "10-Q", "8-K"} else None)
        )
        raw_for_cleaning = document.raw_content
        if (
            document.source == "sec"
            and form == "8-K"
            and document.artifact
            and "2.02" not in document.artifact.form_items
        ):
            main = [part for part in _parts(raw_for_cleaning) if part.document_type == "8-K"]
            if len(main) != 1:
                raise ContentQualityError("non-earnings 8-K must have exactly one main disclosure")
            raw_for_cleaning = main[0].content
            cleaning_version = "sec-main-disclosure-v1"
        cleaned_content = _clean_content(raw_for_cleaning, source=document.source, form=form)
    else:
        _require_readable_content(document.raw_content, cleaned_content)
    normalized = replace(
        document,
        cleaned_content=cleaned_content,
        cleaning_version=(document.provenance.parser_version if document.provenance else cleaning_version),
    )
    return replace(normalized, document_id=normalized.derivation_id)


def _clean_content(raw_content: str, *, source: str = "", form: str | None = None) -> str:
    is_sec = source.casefold() == "sec"
    if is_sec:
        extracted = sec_html_to_text(select_sec_content(raw_content, form=form).content)
    else:
        extracted = _html_to_text(_SEC_XBRL.sub("", raw_content))
    normalized = unicodedata.normalize("NFKC", extracted).replace("\r\n", "\n").replace("\r", "\n")
    paragraphs: list[str] = []
    current_lines: list[str] = []
    for line in normalized.split("\n"):
        cleaned_line = "".join(
            character for character in line if character in "\t\n" or unicodedata.category(character)[0] != "C"
        )
        cleaned_line = re.sub(r"[ \t]+", " ", cleaned_line).strip()
        if not cleaned_line:
            if current_lines:
                paragraphs.append("\n".join(current_lines))
                current_lines = []
        elif not _PAGE_MARKER.fullmatch(cleaned_line) and not _NAVIGATION_MARKER.fullmatch(cleaned_line):
            current_lines.append(cleaned_line)
    if current_lines:
        paragraphs.append("\n".join(current_lines))

    counts: dict[str, int] = {}
    for paragraph in paragraphs:
        counts[paragraph] = counts.get(paragraph, 0) + 1
    cleaned = "\n\n".join(paragraph for paragraph in paragraphs if is_sec or counts[paragraph] < 3)
    _require_readable_content(raw_content, cleaned)
    return cleaned


def _html_to_text(content: str) -> str:
    if _HTML_MARKUP.search(content) is None:
        return content
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(list(_IGNORED_TAGS)):
        tag.decompose()
    return soup.get_text("\n")


def _require_readable_content(raw_content: str, cleaned_content: str) -> None:
    if "\x00" in raw_content or "\ufffd" in raw_content:
        raise ContentQualityError("document content is not readable")
    visible = [character for character in cleaned_content if not character.isspace()]
    alphanumeric = sum(character.isalnum() for character in visible)
    if not visible or not alphanumeric or alphanumeric / len(visible) < 0.35:
        raise ContentQualityError("document content does not contain sufficient readable text")


def _chunk_document(
    document: SourceDocument,
    *,
    processing_config_version: str,
    token_counter: TokenCounter,
) -> tuple[DocumentChunk, ...]:
    sentences = [
        part
        for sentence in _split_sentences(document.cleaned_content)
        for part in _split_long_sentence(sentence, token_counter)
    ]
    groups: list[list[str]] = []
    current: list[str] = []
    for sentence in sentences:
        candidate = " ".join((*current, sentence))
        if current and (len(current) >= 3 or token_counter(candidate) > 2000):
            groups.append(current)
            current = []
        current.append(sentence)
    if current:
        groups.append(current)

    if len(groups) > 1 and len(groups[-1]) == 1 and len(groups[-2]) > 1:
        groups[-1].insert(0, groups[-2].pop())

    return tuple(
        DocumentChunk(
            chunk_id=f"{document.document_id}:chunks:{sha256(processing_config_version.encode()).hexdigest()}:chunk:{ordinal}",
            document_id=document.document_id,
            ordinal=ordinal,
            content=" ".join(group),
            processing_config_version=processing_config_version,
        )
        for ordinal, group in enumerate(groups)
    )


def _split_sentences(content: str) -> tuple[str, ...]:
    parts = _SENTENCE_END.split(content)
    sentences: list[str] = []
    index = 0
    while index < len(parts):
        sentence = parts[index].strip()
        if not sentence:
            index += 1
            continue
        if sentence.lower().endswith(tuple(_ABBREVIATIONS)) and index + 1 < len(parts):
            sentence = f"{sentence} {parts[index + 1].strip()}"
            index += 2
        else:
            index += 1
        sentences.append(sentence)
    return tuple(sentences)


def _split_long_sentence(sentence: str, token_counter: TokenCounter) -> tuple[str, ...]:
    if token_counter(sentence) <= 2000:
        return (sentence,)

    parts: list[str] = []
    words: list[str] = []
    for word in sentence.split():
        candidate = " ".join((*words, word))
        if words and token_counter(candidate) > 2000:
            parts.append(" ".join(words))
            words = []
        words.append(word)
    if words:
        parts.append(" ".join(words))
    return tuple(parts)
