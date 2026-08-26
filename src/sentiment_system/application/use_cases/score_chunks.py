"""Use case for obtaining auditable investor-independent chunk scores."""

from collections.abc import Callable, Sequence
from datetime import datetime, timezone

from sentiment_system.application.ports.llm import LLMScorer
from sentiment_system.application.ports.repositories import (
    ChunkScoreRepository,
    ExperimentProvenanceRepository,
    ExperimentRunRepository,
)
from sentiment_system.domain.documents import DocumentChunk
from sentiment_system.domain.predictions import ExperimentProvenance, ExperimentRun
from sentiment_system.domain.scoring import ChunkScoreRecord


class ScoreChunks:
    """Score chunks once per batch and preserve the complete audit trail."""

    def __init__(
        self,
        scorer: LLMScorer,
        scores: ChunkScoreRepository,
        provenance: ExperimentProvenanceRepository,
        runs: ExperimentRunRepository,
        *,
        provider: str = "deterministic",
        model_name: str = "deterministic-sha256-v1",
        input_source: str = "normalized_chunks",
        input_version: str = "processing-v2",
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._scorer = scorer
        self._scores = scores
        self._provenance = provenance
        self._runs = runs
        self._provider = provider
        self._model_name = model_name
        self._input_source = input_source
        self._input_version = input_version
        self._now = now or (lambda: datetime.now(timezone.utc))

    def execute(self, chunks: Sequence[DocumentChunk], *, run_id: str, prompt: str) -> int:
        """Persist one score per chunk and return the number processed."""
        started_at = self._now()
        configuration = {
            "provider": self._provider,
            "model": self._model_name,
            "input_source": self._input_source,
            "input_version": self._input_version,
            "prompt": prompt,
            "soft_exclusion_threshold": 0.05,
            "soft_exclusion_consecutive_runs": 3,
        }
        self._runs.save(
            ExperimentRun(
                run_id=run_id,
                run_type="scoring",
                status="started",
                started_at=started_at,
                configuration=configuration,
            )
        )

        raw_responses: list[str] = []
        parsed_outputs: dict[str, object] = {}
        for chunk in chunks:
            result = self._scorer.score_chunk(chunk)
            raw_responses.append(result.raw_response)
            parsed_outputs[chunk.chunk_id] = dict(result.parsed_output)
            previous = self._scores.list_for_chunk(chunk.chunk_id)
            low_scores = sum(1 for item in previous[-2:] if item.importance_score < 0.05)
            self._scores.save(
                ChunkScoreRecord(
                    chunk_id=chunk.chunk_id,
                    run_id=run_id,
                    sentiment=result.sentiment,
                    importance_score=result.importance_score,
                    excluded=result.importance_score < 0.05 and low_scores >= 2,
                    prompt=prompt,
                    raw_response=result.raw_response,
                    parsed_output=result.parsed_output,
                    token_usage=(
                        {
                            "prompt_tokens": result.token_usage.prompt_tokens,
                            "completion_tokens": result.token_usage.completion_tokens,
                            "truncated": result.truncated,
                        }
                        if result.token_usage is not None
                        else {}
                    ),
                )
            )

        completed_at = self._now()
        self._provenance.save(
            ExperimentProvenance(
                run_id=run_id,
                input_source=self._input_source,
                input_version=self._input_version,
                processing_config={"chunk_count": len(chunks)},
                model_provider=self._provider,
                model_name=self._model_name,
                prompt=prompt,
                raw_response="\n".join(raw_responses),
                parsed_output=parsed_outputs,
                thesis_parameters={},
                created_at=completed_at,
            )
        )
        self._runs.save(
            ExperimentRun(
                run_id=run_id,
                run_type="scoring",
                status="completed",
                started_at=started_at,
                completed_at=completed_at,
                configuration={**configuration, "chunk_count": len(chunks)},
            )
        )
        return len(chunks)
