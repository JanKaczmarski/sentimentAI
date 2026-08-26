"""Unit contracts for auditable scoring and experiment-run records."""

from datetime import datetime, timezone

from sentiment_system.domain.predictions import ExperimentRun
from sentiment_system.domain.scoring import ChunkScoreRecord
from sentiment_system.domain.sentiment import SentimentScore


def test_scoring_records_keep_provider_output_and_run_lineage() -> None:
    score = ChunkScoreRecord(
        chunk_id="chunk-1",
        run_id="run-1",
        sentiment=SentimentScore(score=0.7, confidence=0.8),
        importance_score=0.9,
        excluded=False,
        prompt="Score this chunk.",
        raw_response='{"score": 0.7}',
        parsed_output={"score": 0.7},
        token_usage={"prompt_tokens": 12, "completion_tokens": 3},
    )
    run = ExperimentRun(
        run_id="run-1",
        run_type="scoring",
        status="completed",
        started_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        completed_at=datetime(2025, 2, 1, 0, 1, tzinfo=timezone.utc),
        configuration={"variant": "standard"},
    )

    assert score.run_id == run.run_id
    assert score.token_usage["completion_tokens"] == 3
    assert run.configuration["variant"] == "standard"
