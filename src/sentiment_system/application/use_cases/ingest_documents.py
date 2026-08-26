"""Use case for loading, cleaning, normalizing, and storing source documents."""

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser

from sentiment_system.application.ports.document_sources import DocumentSource
from sentiment_system.application.ports.repositories import ChunkRepository, DocumentRepository
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
            document_chunks = _chunk_document(
                document,
                processing_config_version=self._processing_config_version,
                token_counter=self._token_counter,
            )
            self._document_repository.save(document)
            for chunk in document_chunks:
                self._chunk_repository.save(chunk)
            documents.append(document)
            chunks.extend(document_chunks)

        return IngestionResult(tuple(documents), tuple(chunks), self._processing_config_version)


_SEC_DOCUMENT = re.compile(r"<DOCUMENT>(?P<body>.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
_SEC_TYPE = re.compile(r"<TYPE>\s*(?P<document_type>[^\s<]+)", re.IGNORECASE)
_SEC_TEXT = re.compile(r"<TEXT>(?P<text>.*?)</TEXT>", re.IGNORECASE | re.DOTALL)
_SEC_XBRL = re.compile(r"<XBRL>.*?</XBRL>", re.IGNORECASE | re.DOTALL)
_HTML_MARKUP = re.compile(r"<[A-Za-z][^>]*>")
_PAGE_MARKER = re.compile(r"^(?:page\s+\d+|\d+\s+of\s+\d+)$", re.IGNORECASE)
_NAVIGATION_MARKER = re.compile(
    r"^(?:back to top|contents|home|next|previous|skip to main content|table of contents)$", re.IGNORECASE
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_ABBREVIATIONS = {"e.g.", "i.e.", "etc.", "inc.", "ltd.", "co.", "corp.", "u.s.", "u.k."}
_SEC_EXHIBIT_TYPES = {"ex-99.1", "ex-99.2"}
_BLOCK_TAGS = {
    "article",
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "section",
    "td",
    "th",
    "tr",
}
_IGNORED_TAGS = {"head", "script", "style", "svg"}


def _normalize_document(document: SourceDocument) -> SourceDocument:
    return SourceDocument(
        document_id=document.document_id,
        source_id=document.source_id,
        company=document.company,
        source=document.source,
        published_at=document.published_at,
        document_type=document.document_type,
        raw_content=document.raw_content,
        cleaned_content=_clean_content(document.raw_content, source=document.source),
    )


def _clean_content(raw_content: str, *, source: str = "") -> str:
    extracted = _extract_sec_communication(raw_content) if source.casefold() == "sec" else raw_content
    extracted = _SEC_XBRL.sub("", extracted)
    extracted = _html_to_text(extracted)
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
    cleaned = "\n\n".join(paragraph for paragraph in paragraphs if counts[paragraph] < 3)
    _require_readable_content(raw_content, cleaned)
    return cleaned


def _extract_sec_communication(raw_content: str) -> str:
    sections: list[tuple[str, str]] = []
    for match in _SEC_DOCUMENT.finditer(raw_content):
        body = match.group("body")
        document_type_match = _SEC_TYPE.search(body)
        text_match = _SEC_TEXT.search(body)
        if document_type_match is not None and text_match is not None:
            sections.append((document_type_match.group("document_type").casefold(), text_match.group("text")))
    if not sections:
        return raw_content
    exhibits = [text for document_type, text in sections if document_type in _SEC_EXHIBIT_TYPES]
    return "\n\n".join(exhibits or [text for _, text in sections])


class _PlainTextHTMLParser(HTMLParser):
    """Extract visible text while retaining block-level line boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        elif self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return "".join(self._parts)


def _html_to_text(content: str) -> str:
    if _HTML_MARKUP.search(content) is None:
        return content
    parser = _PlainTextHTMLParser()
    parser.feed(content)
    parser.close()
    return parser.text()


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
            chunk_id=f"{document.document_id}:chunk:{ordinal}",
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
