"""Use case for a manually triggered source-to-prediction batch."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sentiment_system.application.ports.repositories import ExperimentRunRepository
from sentiment_system.application.use_cases.aggregate_snapshots import AggregateSnapshots
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.domain.predictions import ExperimentRun

_BATCH_VERSION = "source-to-prediction-v1"
_SCORING_PROMPT = "Score each chunk for investor-independent sentiment and general importance."


@dataclass(frozen=True, slots=True)
class BatchResult:
    """Counts and identity returned by one completed batch."""

    run_id: str
    status: str
    document_count: int
    chunk_count: int
    indexed_chunk_count: int
    scored_chunk_count: int
    snapshot_count: int
    companies: tuple[str, ...]


class BatchExecutionError(RuntimeError):
    """Raised after a batch has recorded a failed run."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"batch run failed: {run_id}")
        self.run_id = run_id


class RunBatch:
    """Orchestrate ingestion through reusable investor-independent snapshots."""

    def __init__(
        self,
        ingestion: IngestDocuments,
        indexing: IndexChunks,
        scoring: ScoreChunks,
        aggregation: AggregateSnapshots,
        runs: ExperimentRunRepository,
        *,
        now: Callable[[], datetime] | None = None,
        scoring_prompt: str | None = None,
        scoring_provider: str = "deterministic",
        scoring_model: str = "deterministic-sha256-v1",
    ) -> None:
        self._ingestion = ingestion
        self._indexing = indexing
        self._scoring = scoring
        self._aggregation = aggregation
        self._runs = runs
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._scoring_prompt = scoring_prompt or _SCORING_PROMPT
        self._scoring_provider = scoring_provider
        self._scoring_model = scoring_model

    def execute(self, *, as_of: date, company: str | None = None) -> BatchResult:
        """Run the deterministic pipeline for documents available at ``as_of``."""
        run_id = str(uuid4())
        started_at = self._now()
        configuration = {
            "pipeline_version": _BATCH_VERSION,
            "as_of": as_of.isoformat(),
            "company": company,
            "scoring_prompt": self._scoring_prompt,
            "provider": self._scoring_provider,
            "model": self._scoring_model,
        }
        self._runs.save(
            ExperimentRun(
                run_id=run_id,
                run_type="batch",
                status="started",
                started_at=started_at,
                configuration=configuration,
            )
        )

        try:
            ingestion_result = self._ingestion.run(
                company=company,
                published_before=as_of + timedelta(days=1),
            )
            indexed_count = self._indexing.execute(ingestion_result.chunks)
            scored_count = self._scoring.execute(
                ingestion_result.chunks,
                run_id=run_id,
                prompt=self._scoring_prompt,
            )
            companies = tuple(sorted({document.company for document in ingestion_result.documents}))
            snapshot_count = sum(
                self._aggregation.execute(company=item, as_of=as_of, run_id=run_id) for item in companies
            )
            completed_at = self._now()
            counts = {
                "document_count": len(ingestion_result.documents),
                "chunk_count": len(ingestion_result.chunks),
                "indexed_chunk_count": indexed_count,
                "scored_chunk_count": scored_count,
                "snapshot_count": snapshot_count,
            }
            self._runs.save(
                ExperimentRun(
                    run_id=run_id,
                    run_type="batch",
                    status="completed",
                    started_at=started_at,
                    completed_at=completed_at,
                    configuration={**configuration, **counts},
                )
            )
            return BatchResult(run_id=run_id, status="completed", companies=companies, **counts)
        except Exception as error:
            self._runs.save(
                ExperimentRun(
                    run_id=run_id,
                    run_type="batch",
                    status="failed",
                    started_at=started_at,
                    completed_at=self._now(),
                    configuration={**configuration, "error_type": type(error).__name__},
                )
            )
            raise BatchExecutionError(run_id) from error
