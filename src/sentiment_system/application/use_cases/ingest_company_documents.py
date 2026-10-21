"""Auditable on-demand preparation of one company's cached documents."""

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from uuid import uuid4

from sentiment_system.application.ports.repositories import ExperimentProvenanceRepository, ExperimentRunRepository
from sentiment_system.application.use_cases.index_chunks import IndexChunks, IndexingResult
from sentiment_system.application.use_cases.ingest_documents import IngestDocuments, IngestionResult, source_lineage
from sentiment_system.application.use_cases.run_batch import SourceScope
from sentiment_system.domain.companies import APPROVED_COMPANY_REGISTRY
from sentiment_system.domain.predictions import ExperimentProvenance, ExperimentRun


@dataclass(frozen=True, slots=True)
class CompanyIngestionResult:
    """Scope, totals and model-work diagnostics for one completed preparation."""

    run_id: str
    company: str
    source_scope: SourceScope
    document_count: int
    chunk_count: int
    indexed_chunk_count: int
    embedded_chunk_count: int
    reused_chunk_count: int


class IngestionExecutionError(RuntimeError):
    """An ingestion attempt failed after its run and diagnostic state were recorded."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"ingestion run failed: {run_id}")
        self.run_id = run_id


class IngestCompanyDocuments:
    """Prepare reusable source evidence without scoring or generating snapshots."""

    def __init__(
        self,
        ingestion: IngestDocuments,
        indexing: IndexChunks,
        runs: ExperimentRunRepository,
        *,
        provenance: ExperimentProvenanceRepository,
        embedding_configuration: Mapping[str, object],
        frozen_ingestion: IngestDocuments | None = None,
        frozen_manifest: Mapping[str, object] | None = None,
        input_source: str = "cached_corpus",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._ingestion = ingestion
        self._frozen_ingestion = frozen_ingestion
        self._indexing = indexing
        self._runs = runs
        self._provenance = provenance
        self._embedding_configuration = dict(embedding_configuration)
        self._frozen_manifest = dict(frozen_manifest or {})
        self._input_source = input_source
        self._now = now or (lambda: datetime.now(timezone.utc))

    def execute(
        self, *, company: str, as_of: date, source_scope: SourceScope = "operational"
    ) -> CompanyIngestionResult:
        """Create a fresh audit attempt while reusing immutable data and compatible vectors."""
        ticker = APPROVED_COMPANY_REGISTRY.lookup(company).ticker
        if source_scope not in {"operational", "frozen"}:
            raise ValueError("source_scope must be operational or frozen")
        run_id, started_at = str(uuid4()), self._now()
        config: dict[str, object] = {
            "pipeline_version": "company-ingestion-v1",
            "company": ticker,
            "as_of": as_of.isoformat(),
            "source_scope": source_scope,
            "input_source": self._input_source,
            "publication_rule": "published_at < as_of",
            "embedding": self._embedding_configuration,
            "embedding_fingerprint": self._indexing.embedding_fingerprint,
            **(self._frozen_manifest if source_scope == "frozen" else {}),
        }
        counts = dict(
            document_count=0, chunk_count=0, indexed_chunk_count=0, embedded_chunk_count=0, reused_chunk_count=0
        )
        lineage: list[dict[str, object]] = []
        stages: dict[str, dict[str, object]] = {}
        active_stage = "ingestion"

        def persist(status: str) -> None:
            completed_at = self._now() if status != "started" else None
            configuration = {**config, **counts, "source_lineage": lineage, "stages": stages}
            self._runs.save(ExperimentRun(run_id, "ingestion", status, started_at, completed_at, configuration))
            self._provenance.save(
                ExperimentProvenance(
                    run_id=run_id,
                    input_source=f"{self._input_source}:{source_scope}",
                    input_version=str(
                        config.get(
                            "source_manifest_version", config.get("processing_config_version", "company-ingestion-v1")
                        )
                    ),
                    processing_config={**configuration, "status": status},
                    model_provider=str(self._embedding_configuration.get("backend", "unspecified")),
                    model_name=str(self._embedding_configuration.get("model", "unspecified")),
                    prompt="Document preparation only; no generative model request.",
                    raw_response="",
                    parsed_output={},
                    thesis_parameters={},
                    created_at=completed_at or started_at,
                )
            )

        def record_document(partial: IngestionResult) -> None:
            counts["document_count"] += len(partial.documents)
            counts["chunk_count"] += len(partial.chunks)
            config["processing_config_version"] = partial.processing_config_version
            lineage.extend(source_lineage(partial))

        def record_indexing(partial: IndexingResult) -> None:
            counts.update(asdict(partial))

        def stage[T](name: str, action: Callable[[], T]) -> T:
            nonlocal active_stage
            active_stage = name
            stages[name] = {"status": "started", "started_at": self._now().isoformat()}
            persist("started")
            result = action()
            stages[name] = {**stages[name], "status": "completed", "completed_at": self._now().isoformat()}
            return result

        def ingest() -> IngestionResult:
            service = self._frozen_ingestion if source_scope == "frozen" else self._ingestion
            if service is None:
                raise ValueError("frozen corpus is not configured")
            return service.run(company=ticker, published_before=as_of, on_document=record_document)

        try:
            result = stage("ingestion", ingest)
            config["processing_config_version"] = result.processing_config_version
            indexed = stage(
                "indexing", lambda: self._indexing.execute_with_counts(result.chunks, on_progress=record_indexing)
            )
            counts.update(asdict(indexed))
            persist("completed")
            return CompanyIngestionResult(run_id=run_id, company=ticker, source_scope=source_scope, **counts)
        except Exception as error:
            stages[active_stage] = {
                **stages.get(active_stage, {}),
                "status": "failed",
                "completed_at": self._now().isoformat(),
            }
            config.update(failed_stage=active_stage, error_type=type(error).__name__)
            persist("failed")
            raise IngestionExecutionError(run_id) from error
