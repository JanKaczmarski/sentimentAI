"""Deterministic in-memory repositories for local development and tests."""

from collections.abc import Iterable
from datetime import date
from uuid import UUID

from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.documents import DocumentChunk, SourceDocument
from sentiment_system.domain.investment_thesis import InvestmentThesis
from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    ExperimentProvenance,
    ExperimentRun,
    Prediction,
)
from sentiment_system.domain.scoring import ChunkScoreRecord


class InMemoryDocumentRepository:
    """Store documents by stable document identifier."""

    def __init__(self, documents: Iterable[SourceDocument] = ()) -> None:
        self._documents: dict[str, SourceDocument] = {}
        for document in documents:
            self.save(document)

    def save(self, document: SourceDocument) -> None:
        self._documents[document.document_id] = document

    def get(self, document_id: str) -> SourceDocument | None:
        return self._documents.get(document_id)

    def list_documents(self, *, company: str | None = None) -> tuple[SourceDocument, ...]:
        documents = (
            document for document in self._documents.values() if company is None or document.company == company
        )
        return tuple(sorted(documents, key=lambda item: (item.published_at, item.document_id)))


class InMemoryChunkRepository:
    """Store chunks by stable chunk identifier."""

    def __init__(self, chunks: Iterable[DocumentChunk] = ()) -> None:
        self._chunks: dict[str, DocumentChunk] = {}
        for chunk in chunks:
            self.save(chunk)

    def save(self, chunk: DocumentChunk) -> None:
        self._chunks[chunk.chunk_id] = chunk

    def get(self, chunk_id: str) -> DocumentChunk | None:
        return self._chunks.get(chunk_id)

    def list_for_document(self, document_id: str) -> tuple[DocumentChunk, ...]:
        chunks = (chunk for chunk in self._chunks.values() if chunk.document_id == document_id)
        return tuple(sorted(chunks, key=lambda item: (item.ordinal, item.chunk_id)))


class InMemoryChunkScoreRepository:
    """Store append-only chunk scores by chunk and run identity."""

    def __init__(self, scores: Iterable[ChunkScoreRecord] = ()) -> None:
        self._scores: dict[tuple[str, str], ChunkScoreRecord] = {}
        for score in scores:
            self.save(score)

    def save(self, score: ChunkScoreRecord) -> None:
        self._scores.setdefault((score.chunk_id, score.run_id), score)

    def list_for_chunk(self, chunk_id: str) -> tuple[ChunkScoreRecord, ...]:
        scores = (score for score in self._scores.values() if score.chunk_id == chunk_id)
        return tuple(sorted(scores, key=lambda item: item.run_id))


class InMemoryInvestmentThesisRepository:
    """Store structured theses by stable thesis identifier."""

    def __init__(self, theses: Iterable[InvestmentThesis] = ()) -> None:
        self._theses: dict[str, InvestmentThesis] = {}
        for thesis in theses:
            self.save(thesis)

    def save(self, thesis: InvestmentThesis) -> None:
        self._theses[thesis.thesis_id] = thesis

    def get(self, thesis_id: str) -> InvestmentThesis | None:
        return self._theses.get(thesis_id)

    def list_for_user(self, user_id: str) -> tuple[InvestmentThesis, ...]:
        theses = (thesis for thesis in self._theses.values() if thesis.user_id == user_id)
        return tuple(sorted(theses, key=lambda item: item.thesis_id))


class InMemoryUserAccountRepository:
    """Store investor accounts by immutable server-generated identifier."""

    def __init__(self, accounts: Iterable[UserAccount] = ()) -> None:
        self._accounts: dict[UUID, UserAccount] = {}
        for account in accounts:
            self.save(account)

    def save(self, account: UserAccount) -> None:
        self._accounts[account.user_id] = account

    def get_by_email(self, email: str) -> UserAccount | None:
        return next((account for account in self._accounts.values() if account.email == email), None)

    def get_by_username(self, username: str) -> UserAccount | None:
        return next((account for account in self._accounts.values() if account.username == username), None)

    def get_by_api_key_digest(self, api_key_digest: str) -> UserAccount | None:
        return next(
            (account for account in self._accounts.values() if account.api_key_digest == api_key_digest),
            None,
        )


class InMemorySnapshotRepository:
    """Store snapshots by company, as-of date, window, and run."""

    def __init__(self, snapshots: Iterable[CompanySentimentSnapshot] = ()) -> None:
        self._snapshots: dict[tuple[str, date, int, str], CompanySentimentSnapshot] = {}
        for snapshot in snapshots:
            self.save(snapshot)

    def save(self, snapshot: CompanySentimentSnapshot) -> None:
        key = (snapshot.company, snapshot.as_of, int(snapshot.window_days), snapshot.run_id)
        self._snapshots[key] = snapshot

    def list_for_company(
        self,
        company: str,
        *,
        as_of: date | None = None,
    ) -> tuple[CompanySentimentSnapshot, ...]:
        snapshots = (
            snapshot
            for snapshot in self._snapshots.values()
            if snapshot.company == company and (as_of is None or snapshot.as_of <= as_of)
        )
        return tuple(
            sorted(
                snapshots,
                key=lambda item: (item.as_of, int(item.window_days), item.run_id),
            )
        )


class InMemoryPredictionRepository:
    """Store predictions by their deterministic prediction key."""

    def __init__(self, predictions: Iterable[Prediction] = ()) -> None:
        self._predictions: dict[tuple[str, date, int, int, str, str | None], Prediction] = {}
        for prediction in predictions:
            self.save(prediction)

    def save(self, prediction: Prediction) -> None:
        key = (
            prediction.company,
            prediction.as_of,
            int(prediction.lookback_days),
            prediction.forecast_horizon_days,
            prediction.run_id,
            prediction.user_id,
        )
        self._predictions[key] = prediction

    def list_for_company(
        self,
        company: str,
        *,
        as_of: date | None = None,
    ) -> tuple[Prediction, ...]:
        predictions = (
            prediction
            for prediction in self._predictions.values()
            if prediction.company == company and (as_of is None or prediction.as_of <= as_of)
        )
        return tuple(
            sorted(
                predictions,
                key=lambda item: (
                    item.as_of,
                    int(item.lookback_days),
                    item.forecast_horizon_days,
                    item.run_id,
                ),
            )
        )

    def list_for_user(self, user_id: str) -> tuple[Prediction, ...]:
        predictions = (prediction for prediction in self._predictions.values() if prediction.user_id == user_id)
        return tuple(
            sorted(
                predictions,
                key=lambda item: (item.as_of, item.company, int(item.lookback_days), item.forecast_horizon_days),
            )
        )


class InMemoryProvenanceRepository:
    """Store secret-free provenance by run identifier."""

    def __init__(self, provenance: Iterable[ExperimentProvenance] = ()) -> None:
        self._provenance: dict[str, ExperimentProvenance] = {}
        for item in provenance:
            self.save(item)

    def save(self, provenance: ExperimentProvenance) -> None:
        self._provenance[provenance.run_id] = provenance

    def get(self, run_id: str) -> ExperimentProvenance | None:
        return self._provenance.get(run_id)


class InMemoryExperimentRunRepository:
    """Store experiment runs by stable identifier."""

    def __init__(self, runs: Iterable[ExperimentRun] = ()) -> None:
        self._runs: dict[str, ExperimentRun] = {}
        for run in runs:
            self.save(run)

    def save(self, run: ExperimentRun) -> None:
        self._runs[run.run_id] = run

    def get(self, run_id: str) -> ExperimentRun | None:
        return self._runs.get(run_id)
