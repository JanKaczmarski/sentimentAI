"""Repeatable, auditable cached-source-to-prediction batch orchestration."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
from typing import Literal
from uuid import uuid4

from sentiment_system.application.ports.repositories import ExperimentProvenanceRepository, ExperimentRunRepository
from sentiment_system.application.use_cases.aggregate_snapshots import RULE_VERSION, AggregateSnapshots
from sentiment_system.application.use_cases.index_chunks import IndexChunks
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments, IngestionResult
from sentiment_system.application.use_cases.score_chunks import ScoreChunks
from sentiment_system.application.use_cases.synchronize_chunk_exclusions import SynchronizeChunkExclusions
from sentiment_system.domain.predictions import ExperimentProvenance, ExperimentRun

SourceScope = Literal["operational", "frozen"]
_BATCH_VERSION = "source-to-prediction-v2"
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
    source_scope: SourceScope


class BatchExecutionError(RuntimeError):
    """Raised after a batch has recorded a failed run."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"batch run failed: {run_id}")
        self.run_id = run_id


class RunBatch:
    """Own the run lifecycle until all reusable sentiment stages succeed."""

    def __init__(
        self,
        ingestion: IngestDocuments,
        indexing: IndexChunks,
        scoring: ScoreChunks,
        aggregation: AggregateSnapshots,
        runs: ExperimentRunRepository,
        *,
        provenance: ExperimentProvenanceRepository,
        exclusion_sync: SynchronizeChunkExclusions,
        frozen_ingestion: IngestDocuments | None = None,
        frozen_manifest: Mapping[str, object] | None = None,
        embedding_configuration: Mapping[str, object] | None = None,
        input_source: str = "document_source",
        now: Callable[[], datetime] | None = None,
        scoring_prompt: str | None = None,
        scoring_provider: str = "deterministic",
        scoring_model: str = "deterministic-sha256-v1",
    ) -> None:
        self._ingestion = ingestion
        self._frozen_ingestion = frozen_ingestion
        self._frozen_manifest = dict(frozen_manifest or {})
        self._embedding_configuration = dict(embedding_configuration or {})
        self._input_source = input_source
        self._indexing = indexing
        self._scoring = scoring
        self._aggregation = aggregation
        self._exclusion_sync = exclusion_sync
        self._runs = runs
        self._provenance = provenance
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._scoring_prompt = scoring_prompt or _SCORING_PROMPT
        self._scoring_provider = scoring_provider
        self._scoring_model = scoring_model

    def execute(
        self, *, as_of: date, company: str | None = None, source_scope: SourceScope = "operational"
    ) -> BatchResult:
        """Run one explicit source scope with strict publication-before semantics."""
        if source_scope not in {"operational", "frozen"}:
            raise ValueError("source_scope must be operational or frozen")
        company = company.upper() if company is not None else None
        run_id, started_at = str(uuid4()), self._now()
        configuration: dict[str, object] = {
            "pipeline_version": _BATCH_VERSION,
            "as_of": as_of.isoformat(),
            "company": company,
            "source_scope": source_scope,
            "input_source": self._input_source,
            "scoring_prompt": self._scoring_prompt,
            "provider": self._scoring_provider,
            "model": self._scoring_model,
            "embedding": self._embedding_configuration,
            "rule_version": RULE_VERSION,
            "publication_rule": "published_at < as_of",
            **(self._frozen_manifest if source_scope == "frozen" else {}),
        }
        stages: dict[str, dict[str, object]] = {}
        source_lineage: list[dict[str, object]] = []
        configuration["source_lineage"] = source_lineage
        active_stage = "ingestion"
        counts = dict(document_count=0, chunk_count=0, indexed_chunk_count=0, scored_chunk_count=0, snapshot_count=0)

        def persist(status: str) -> None:
            completed_at = self._now() if status != "started" else None
            config = {**configuration, **counts, "stages": stages}
            self._runs.save(
                ExperimentRun(
                    run_id=run_id,
                    run_type="batch",
                    status=status,
                    started_at=started_at,
                    completed_at=completed_at,
                    configuration=config,
                )
            )
            existing = self._provenance.get(run_id)
            self._provenance.save(
                ExperimentProvenance(
                    run_id=run_id,
                    input_source=f"{self._input_source}:{source_scope}",
                    input_version=str(
                        configuration.get(
                            "source_manifest_version", configuration.get("processing_config_version", _BATCH_VERSION)
                        )
                    ),
                    processing_config={**(existing.processing_config if existing else {}), **config, "status": status},
                    model_provider=self._scoring_provider,
                    model_name=self._scoring_model,
                    prompt=self._scoring_prompt,
                    raw_response=existing.raw_response if existing else "",
                    parsed_output=existing.parsed_output if existing else {},
                    thesis_parameters={},
                    created_at=completed_at or self._now(),
                )
            )

        def stage[T](name: str, action: Callable[[], T]) -> T:
            nonlocal active_stage
            active_stage = name
            stages[name] = {"status": "started", "started_at": self._now().isoformat()}
            persist("started")
            result = action()
            stages[name] = {**stages[name], "status": "completed", "completed_at": self._now().isoformat()}
            return result

        def ingest() -> IngestionResult:
            ingestion = self._frozen_ingestion if source_scope == "frozen" else self._ingestion
            if ingestion is None:
                raise ValueError("frozen corpus is not configured")
            return ingestion.run(company=company, published_before=as_of, on_document=record_document)

        def record_document(partial: IngestionResult) -> None:
            counts["document_count"] += len(partial.documents)
            counts["chunk_count"] += len(partial.chunks)
            configuration["processing_config_version"] = partial.processing_config_version
            source_lineage.extend(_source_lineage(partial))

        try:
            result = stage("ingestion", ingest)
            counts.update(document_count=len(result.documents), chunk_count=len(result.chunks))
            configuration["processing_config_version"] = result.processing_config_version
            counts["indexed_chunk_count"] = stage("indexing", lambda: self._indexing.execute(result.chunks))
            counts["scored_chunk_count"] = stage(
                "scoring",
                lambda: self._scoring.execute(
                    result.chunks,
                    run_id=run_id,
                    prompt=self._scoring_prompt,
                ),
            )
            companies = tuple(sorted({document.company for document in result.documents}))
            counts["snapshot_count"] = stage(
                "aggregation",
                lambda: sum(self._aggregation.execute(company=item, as_of=as_of, run_id=run_id) for item in companies),
            )
            stage("exclusion_sync", lambda: self._exclusion_sync.execute(result.chunks, run_id=run_id))
            persist("completed")
            return BatchResult(
                run_id=run_id, status="completed", companies=companies, source_scope=source_scope, **counts
            )
        except Exception as error:
            stages[active_stage] = {
                **stages.get(active_stage, {}),
                "status": "failed",
                "completed_at": self._now().isoformat(),
            }
            configuration.update(failed_stage=active_stage, error_type=type(error).__name__)
            partial = self._provenance.get(run_id)
            counts["scored_chunk_count"] = len(partial.parsed_output) if partial else 0
            persist("failed")
            raise BatchExecutionError(run_id) from error


def _source_lineage(result: IngestionResult) -> list[dict[str, object]]:
    return [
        {
            "document_id": document.document_id,
            "source_id": source.source_id,
            "company": source.company,
            "source": source.source,
            "published_at": source.published_at.isoformat(),
            "original_byte_sha256": source.original_byte_sha256,
            "raw_text_sha256": sha256(source.raw_content.encode()).hexdigest(),
            "cleaned_sha256": sha256(document.cleaned_content.encode()).hexdigest(),
            "cleaning_version": document.cleaning_version,
            "manifest_version": source.manifest_version,
            "manifest_record_id": source.provenance.manifest_record_id if source.provenance else None,
            "chunk_ids": [chunk.chunk_id for chunk in result.chunks if chunk.document_id == document.document_id],
        }
        for source, document in zip(result.source_documents, result.documents, strict=True)
    ]
