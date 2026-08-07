"""Tests for auditable snapshots, predictions, and provenance contracts."""

from datetime import date, datetime, timezone

import pytest

from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    ExperimentProvenance,
    Prediction,
    PredictionEvidence,
    SnapshotWindow,
)
from sentiment_system.domain.sentiment import SentimentScore


def _evidence() -> PredictionEvidence:
    return PredictionEvidence(
        chunk_id="chunk-1",
        published_at=date(2025, 1, 30),
        importance_score=0.9,
        excerpt="Revenue increased during the reporting period.",
    )


def _score(score: float) -> SentimentScore:
    return SentimentScore(score=score, confidence=0.8)


def test_company_snapshot_preserves_window_sentiment_evidence_and_run() -> None:
    evidence = _evidence()
    snapshot = CompanySentimentSnapshot(
        company="AAPL",
        as_of=date(2025, 2, 1),
        window_days=SnapshotWindow.NINETY_DAYS,
        sentiment=_score(0.72),
        evidence=(evidence,),
        run_id="run-1",
    )

    assert snapshot.window_days is SnapshotWindow.NINETY_DAYS
    assert snapshot.sentiment.score == 0.72
    assert snapshot.evidence == (evidence,)
    assert snapshot.run_id == "run-1"


@pytest.mark.parametrize("window", [SnapshotWindow.THIRTY_DAYS, SnapshotWindow.NINETY_DAYS, SnapshotWindow.YEAR])
def test_company_snapshot_accepts_only_supported_windows(window: SnapshotWindow) -> None:
    snapshot = CompanySentimentSnapshot(
        company="AAPL",
        as_of=date(2025, 2, 1),
        window_days=window,
        sentiment=_score(0.5),
        evidence=(),
        run_id="run-1",
    )

    assert snapshot.window_days is window


def test_company_snapshot_rejects_unsupported_window() -> None:
    with pytest.raises(ValueError, match="window_days must be one of 30, 90, or 365"):
        CompanySentimentSnapshot(
            company="AAPL",
            as_of=date(2025, 2, 1),
            window_days=60,
            sentiment=_score(0.5),
            evidence=(),
            run_id="run-1",
        )


def test_prediction_preserves_base_and_personalized_sentiment_contract() -> None:
    evidence = _evidence()
    prediction = Prediction(
        company="AAPL",
        as_of=date(2025, 2, 1),
        lookback_days=SnapshotWindow.NINETY_DAYS,
        forecast_horizon_days=20,
        base_sentiment=_score(0.72),
        personalized_sentiment=_score(0.68),
        confidence=0.81,
        evidence=(evidence,),
        run_id="run-1",
        reasoning="The structured thesis favors the long-term signal.",
    )

    assert prediction.base_sentiment.score == 0.72
    assert prediction.personalized_sentiment.score == 0.68
    assert prediction.lookback_days is SnapshotWindow.NINETY_DAYS
    assert prediction.forecast_horizon_days == 20
    assert prediction.confidence == 0.81
    assert prediction.evidence == (evidence,)
    assert prediction.run_id == "run-1"


def test_provenance_preserves_required_audit_values() -> None:
    provenance = ExperimentProvenance(
        run_id="run-1",
        input_source="fixture-corpus",
        input_version="manifest-v1",
        processing_config={"chunking": "fixed"},
        model_provider="groq",
        model_name="model-v1",
        prompt="Score the supplied chunk.",
        raw_response='{"score": 0.72}',
        parsed_output={"score": 0.72},
        thesis_parameters={"risk_tolerance": "medium"},
        created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
    )

    assert provenance.input_version == "manifest-v1"
    assert provenance.parsed_output["score"] == 0.72
    assert provenance.thesis_parameters["risk_tolerance"] == "medium"


@pytest.mark.parametrize(
    "field",
    ["processing_config", "parsed_output", "thesis_parameters"],
)
def test_provenance_rejects_secret_like_values(field: str) -> None:
    values: dict[str, object] = {
        "run_id": "run-1",
        "input_source": "fixture-corpus",
        "input_version": "manifest-v1",
        "processing_config": {"chunking": "fixed"},
        "model_provider": "groq",
        "model_name": "model-v1",
        "prompt": "Score the supplied chunk.",
        "raw_response": '{"score": 0.72}',
        "parsed_output": {"score": 0.72},
        "thesis_parameters": {"risk_tolerance": "medium"},
        "created_at": datetime(2025, 2, 1, tzinfo=timezone.utc),
    }
    values[field] = {"api_key": "not-a-secret-in-tests"}

    with pytest.raises(ValueError, match="secret-like provenance value"):
        ExperimentProvenance(**values)


def test_provenance_rejects_secret_in_raw_response() -> None:
    with pytest.raises(ValueError, match="secret-like provenance value"):
        ExperimentProvenance(
            run_id="run-1",
            input_source="fixture-corpus",
            input_version="manifest-v1",
            processing_config={"chunking": "fixed"},
            model_provider="groq",
            model_name="model-v1",
            prompt="Score the supplied chunk.",
            raw_response="Authorization: Bearer abc123",
            parsed_output={"score": 0.72},
            thesis_parameters={"risk_tolerance": "medium"},
            created_at=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )
