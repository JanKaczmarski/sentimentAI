"""Deterministic SEC document selection with attachment-level review evidence.

Exhibit numbers identify attachments, not their semantic role. Rules use the
document's title, description and filing references; unresolved roles stay visible
in diagnostics rather than being labelled as verified earnings material.
"""

import re
from dataclasses import dataclass, replace

from bs4 import BeautifulSoup

SEC_PARSER_VERSION = "sec-form-aware-v2"
_DOCUMENT = re.compile(r"<DOCUMENT>(.*?)</DOCUMENT>", re.IGNORECASE | re.DOTALL)
_TEXT = re.compile(r"<TEXT>(.*?)</TEXT>", re.IGNORECASE | re.DOTALL)
_FORM = re.compile(r"CONFORMED SUBMISSION TYPE:\s*(10-K|10-Q|8-K)\b", re.IGNORECASE)
_PRESENTATION = re.compile(r"presentation|earningsdeck|earnings.?slides|conference.?call.?slides", re.IGNORECASE)
_RELEASE = re.compile(
    r"earnings[ _-]*release|press[ _-]*release|"
    r"(?:reports?|announces?).{0,100}(?:quarter|year|financial|fiscal).{0,60}(?:results|earnings)|"
    r"(?:q[1-4]|[1-4]q|first|second|third|fourth|quarter|full.year).{0,60}(?:results|earnings)",
    re.IGNORECASE,
)
_EARNINGS_HEADLINE = re.compile(
    r"(?:reports?|announces?).{0,100}(?:quarter|year|financial|fiscal).{0,60}(?:results|earnings)",
    re.IGNORECASE,
)
_FINANCIAL = re.compile(
    r"financial\s+(?:statements|data|information)|(?:operating|segment)\s+(?:data|financial\s+data)|"
    r"reconcil(?:iation|ing)|non.gaap\s+(?:discussion|financial.measures)|net.earnings.to.ebit",
    re.IGNORECASE,
)
_UNRELATED = re.compile(
    r"board.of.directors|departs?.{0,20}board|founder.led|note.from|"
    r"internal.communications.faq|shelf.registration|class.of.stock",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class SecDocumentDecision:
    """Original embedded text and the auditable reason for its selection."""

    document_type: str
    filename: str
    description: str
    content: str
    selected: bool = False
    reason: str = "supporting/non-narrative document"


@dataclass(frozen=True, slots=True)
class SecExtraction:
    """Selected original HTML and observations requiring source/output review."""

    content: str
    form: str | None
    documents: tuple[SecDocumentDecision, ...]
    issues: tuple[str, ...]


def sec_html_to_text(content: str) -> str:
    """Keep visible report facts, table rows and image-page transcriptions.

    An SEC TEXT/XBRL wrapper may enclose the whole report: never discard it.
    Only explicitly hidden inline resources are removed, not all XBRL facts or
    white/small transcription text used in older image-backed earnings releases.
    """
    soup = BeautifulSoup(content, "html.parser")
    for tag in list(soup.find_all(True)):
        if tag.attrs is None:  # An ancestor may already have been decomposed.
            continue
        name = (tag.name or "").casefold()
        style = re.sub(r"\s+", "", str(tag.get("style", ""))).casefold()
        if (
            name in {"head", "script", "style", "svg", "ix:header", "ix:hidden", "xbrli:context", "xbrli:unit"}
            or tag.has_attr("hidden")
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            tag.decompose()
    # Keep the values on the same row. Do not deduplicate repeated numeric cells.
    for row in list(soup.find_all("tr")):
        cells = row.find_all(["td", "th"], recursive=False)
        if cells and not row.find("table"):
            row.replace_with("\n" + "\t".join(cell.get_text(" ", strip=True) for cell in cells) + "\n")
    return soup.get_text("\n")


def _field(header: str, name: str) -> str:
    match = re.search(rf"<{name}>\s*([^\r\n<]*)", header, re.IGNORECASE)
    return match.group(1).strip() if match else ""


def _parts(raw: str) -> tuple[SecDocumentDecision, ...]:
    parts = []
    for match in _DOCUMENT.finditer(raw):
        body = match.group(1)
        text = _TEXT.search(body)
        header = body[: text.start()] if text else body
        parts.append(
            SecDocumentDecision(
                document_type=_field(header, "TYPE").upper(),
                filename=_field(header, "FILENAME"),
                description=_field(header, "DESCRIPTION"),
                content=text.group(1) if text else "",
            )
        )
    return tuple(parts)


def _reference_roles(parts: tuple[SecDocumentDecision, ...]) -> dict[str, str]:
    """Resolve explicit exhibit-index descriptions to their embedded filename.

    Scope to a single table row or paragraph, rather than mixing adjacent exhibit
    descriptions. Links are read as metadata only; no referenced URL is fetched.
    """
    roles = {}
    for main in parts:
        if main.document_type != "8-K":
            continue
        soup = BeautifulSoup(main.content, "html.parser")
        for row in soup.find_all("tr"):
            text = re.sub(r"\s+", " ", row.get_text(" ", strip=True))
            numbers = set(re.findall(r"(?<!\d)99\.\d+(?!\d)", text))
            if len(numbers) == 1 and _PRESENTATION.search(text):
                # Older exhibit indexes often have no hyperlinks at all.
                roles[f"ex-{next(iter(numbers))}"] = "presentation"
        for anchor in soup.find_all("a", href=True):
            filename = str(anchor["href"]).split("#")[0].rsplit("/", 1)[-1].casefold()
            scope = anchor.find_parent("tr") or anchor.find_parent("p")
            if scope is None:
                continue
            # A layout table may hold the whole exhibit index; don't conflate rows.
            targets = {str(link.get("href", "")) for link in scope.find_all("a", href=True)}
            if len(targets) != 1:
                continue
            text = re.sub(r"\s+", " ", scope.get_text(" ", strip=True))
            if _PRESENTATION.search(text):
                roles[filename] = "presentation"
            elif re.search(r"(?:press|earnings)\s+release", text, re.I):
                roles.setdefault(filename, "release")
    return roles


def _attachment_role(part: SecDocumentDecision, references: dict[str, str]) -> tuple[str, str]:
    title = re.sub(r"\s+", " ", sec_html_to_text(part.content)).strip()[:2200]
    metadata = f"{part.description} {part.filename}"
    # Explicit deck filenames/descriptions beat incidental results language in slides.
    reference = references.get(part.filename.casefold()) or references.get(part.document_type.casefold())
    if reference == "presentation" or _PRESENTATION.search(metadata) or _PRESENTATION.search(title[:250]):
        return "excluded", "presentation, not the earnings release/financial supplement"
    # Generic 'press release' metadata does not distinguish earnings from other news.
    if _EARNINGS_HEADLINE.search(title[:600]):
        # A release may legitimately announce earnings AND a governance event.
        return "release", "earnings-release title/content"
    if _UNRELATED.search(title[:350]):
        return "excluded", "unrelated governance/capital-markets communication"
    if reference == "release" or re.search(r"earnings[ _-]*release|press[ _-]*release", part.filename, re.I):
        return "release", "release filename/scoped main-report reference with no conflicting title"
    if _FINANCIAL.search(f"{part.description} {title[:350]}"):
        return "financial", "accompanying financial statements/data/reconciliation"
    if _RELEASE.search(title[:1200]):
        return "release", "earnings-release title/content"
    return "unresolved", "unresolved exhibit role; compare source and output"


def select_sec_content(raw_content: str, *, form: str | None = None) -> SecExtraction:
    """Select a full periodic report or earnings communication, never by EX number alone."""
    parts = _parts(raw_content)
    inferred = _FORM.search(raw_content[:20000])
    forms = {part.document_type for part in parts if part.document_type in {"10-K", "10-Q", "8-K"}}
    expected = form.upper() if form else (inferred.group(1).upper() if inferred else None)
    if expected is None and len(forms) == 1:
        expected = next(iter(forms))
    if expected is not None and expected not in {"10-K", "10-Q", "8-K"}:
        raise ValueError(f"unsupported SEC form: {expected}")
    issues: list[str] = []
    if not parts:
        if re.search(r"<DOCUMENT>|<TEXT>", raw_content, re.IGNORECASE):
            raise ValueError("malformed SEC submission document/text wrapper")
        parts = (SecDocumentDecision(expected or "standalone", "", "", raw_content, True, "standalone document"),)
        content = raw_content
    elif expected in {"10-K", "10-Q"}:
        main = [part for part in parts if part.document_type == expected and part.content.strip()]
        if len(main) != 1:
            raise ValueError(f"expected exactly one readable {expected} main report; found {len(main)}")
        parts = tuple(
            replace(
                part, selected=part is main[0], reason="complete main report" if part is main[0] else "separate exhibit"
            )
            for part in parts
        )
        content = main[0].content
    else:
        decisions = []
        release_found = False
        references = _reference_roles(parts)
        for part in parts:
            if re.fullmatch(r"EX-99(?:\.\d+)?", part.document_type):
                role, reason = _attachment_role(part, references)
                selected = role in {"release", "financial"}
                release_found |= role == "release"
                if role == "unresolved":
                    issues.append(f"{part.document_type} {part.filename}: {reason}")
                decisions.append(replace(part, selected=selected, reason=reason))
            else:
                decisions.append(part)
        if not release_found:
            main = [part for part in decisions if part.document_type == "8-K" and part.content.strip()]
            if len(main) != 1:
                raise ValueError("cannot identify earnings release or a unique 8-K main disclosure")
            decisions = [
                (
                    replace(part, selected=True, reason="main 8-K disclosure; no separate release identified")
                    if part is main[0]
                    else part
                )
                for part in decisions
            ]
            issues.append("no separate earnings release identified; main 8-K disclosure retained for review")
        parts = tuple(decisions)
        content = "\n\n".join(part.content for part in parts if part.selected)
    if expected == "10-K" and re.search(r'href\s*=\s*["\'][^"\']*(?:dex13|exhibit13|ex13)[^"\']*["\']', content, re.I):
        issues.append(
            "annual report Exhibit 13 linked externally; incorporated content may not be in the downloaded file"
        )
    return SecExtraction(content, expected, parts, tuple(issues))
