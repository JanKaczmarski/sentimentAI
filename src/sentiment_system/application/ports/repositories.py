"""Ports for persistence of auditable domain values."""

from datetime import date
from typing import Protocol, runtime_checkable

from sentiment_system.domain.documents import DocumentChunk, SourceDocument
from sentiment_system.domain.investment_thesis import InvestmentThesis
from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    ExperimentProvenance,
    Prediction,
)


@runtime_checkable
class DocumentRepository(Protocol):
    """Persist and query normalized source documents."""

    def save(self, document: SourceDocument) -> None:
        """Insert or replace a document by its stable identifier."""

    def get(self, document_id: str) -> SourceDocument | None:
        """Return one document by identifier."""

    def list_documents(self, *, company: str | None = None) -> tuple[SourceDocument, ...]:
        """Return documents in deterministic publication order."""


@runtime_checkable
class ChunkRepository(Protocol):
    """Persist and query document chunks."""

    def save(self, chunk: DocumentChunk) -> None:
        """Insert or replace a chunk by its stable identifier."""

    def get(self, chunk_id: str) -> DocumentChunk | None:
        """Return one chunk by identifier."""

    def list_for_document(self, document_id: str) -> tuple[DocumentChunk, ...]:
        """Return chunks in ordinal order."""


@runtime_checkable
class InvestmentThesisRepository(Protocol):
    """Persist structured Investment Theses."""

    def save(self, thesis: InvestmentThesis) -> None:
        """Insert or replace a thesis by its stable identifier."""

    def get(self, thesis_id: str) -> InvestmentThesis | None:
        """Return one thesis by identifier."""

    def list_for_user(self, user_id: str) -> tuple[InvestmentThesis, ...]:
        """Return a user's theses in deterministic identifier order."""


@runtime_checkable
class SnapshotRepository(Protocol):
    """Persist investor-independent company snapshots."""

    def save(self, snapshot: CompanySentimentSnapshot) -> None:
        """Insert or replace a snapshot by company, date, window, and run."""

    def list_for_company(
        self,
        company: str,
        *,
        as_of: date | None = None,
    ) -> tuple[CompanySentimentSnapshot, ...]:
        """Return snapshots optionally limited to an as-of date."""


@runtime_checkable
class PredictionRepository(Protocol):
    """Persist auditable predictions."""

    def save(self, prediction: Prediction) -> None:
        """Insert or replace a prediction by its stable prediction key."""

    def list_for_company(
        self,
        company: str,
        *,
        as_of: date | None = None,
    ) -> tuple[Prediction, ...]:
        """Return predictions optionally limited to an as-of date."""


@runtime_checkable
class ExperimentProvenanceRepository(Protocol):
    """Persist secret-free experiment provenance by run identifier."""

    def save(self, provenance: ExperimentProvenance) -> None:
        """Insert or replace provenance by run identifier."""

    def get(self, run_id: str) -> ExperimentProvenance | None:
        """Return provenance for one run."""
