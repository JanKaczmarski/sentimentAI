"""Tests for prediction generation and user-scoped history."""

from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from uuid import uuid4

import pytest

from sentiment_system.adapters.outbound.persistence.in_memory import (
    InMemoryExperimentRunRepository,
    InMemoryInvestmentThesisRepository,
    InMemoryPredictionRepository,
    InMemorySnapshotRepository,
    InMemoryUserAccountRepository,
)
from sentiment_system.application.use_cases.generate_prediction import GeneratePrediction, PredictionUnavailableError
from sentiment_system.application.use_cases.manage_investment_theses import ManageInvestmentTheses
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.investment_thesis import InvestmentHorizon, InvestmentStyle, RiskTolerance
from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    ExperimentRun,
    PredictionEvidence,
    SnapshotWindow,
)
from sentiment_system.domain.sentiment import SentimentScore


def test_generate_prediction_persists_user_scoped_evidence_and_history() -> None:
    accounts = InMemoryUserAccountRepository()
    account = UserAccount(
        user_id=uuid4(),
        email="investor@example.com",
        username="investor",
        api_key_digest=sha256(b"key").hexdigest(),
    )
    accounts.save(account)
    thesis_repository = InMemoryInvestmentThesisRepository()
    theses = ManageInvestmentTheses(accounts, thesis_repository)
    theses.create(
        api_key="key",
        companies=("AAPL",),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
        description=None,
    )
    snapshots = InMemorySnapshotRepository(
        _snapshots(thesis_run="run-1"),
    )
    predictions = InMemoryPredictionRepository()

    result = GeneratePrediction(
        accounts, thesis_repository, snapshots, predictions, InMemoryExperimentRunRepository([_run("run-1", 1)])
    ).execute(
        api_key="key",
        company="AAPL",
        as_of=date(2025, 2, 1),
        forecast_horizon_days=20,
    )

    assert result.user_id == str(account.user_id)
    assert result.personalized_sentiment.score == 0.54
    assert len(result.evidence) == 2
    assert result.rule_version == "aggregation-personalization-v1"
    assert result.run_metadata["status"] == "completed"
    assert result.thesis_parameters["investment_style"] == "passive"
    assert result.thesis_parameters["companies"] == ("AAPL",)
    assert result.prediction_id
    assert predictions.list_for_company("AAPL") == (result,)


def _snapshots(*, thesis_run: str) -> tuple[CompanySentimentSnapshot, ...]:
    return tuple(
        CompanySentimentSnapshot(
            company="AAPL",
            as_of=date(2025, 2, 1),
            window_days=window,
            sentiment=SentimentScore(score=score, confidence=0.8),
            evidence=(
                PredictionEvidence(
                    chunk_id=f"chunk-{window}",
                    published_at=date(2025, 1, 1),
                    sentiment=SentimentScore(score=score, confidence=0.8),
                    importance_score=0.9,
                    excerpt=f"Evidence {window}",
                ),
            ),
            run_id=thesis_run,
        )
        for window, score in ((SnapshotWindow.NINETY_DAYS, 0.4), (SnapshotWindow.YEAR, 0.6))
    )


def _run(
    run_id: str,
    hour: int,
    *,
    status: str = "completed",
    company: str | None = "AAPL",
    as_of: str = "2025-02-01",
    run_type: str = "batch",
) -> ExperimentRun:
    started_at = datetime(2026, 8, 26, hour, tzinfo=timezone.utc)
    return ExperimentRun(
        run_id=run_id,
        run_type=run_type,
        status=status,
        started_at=started_at,
        completed_at=started_at + timedelta(minutes=1) if status != "started" else None,
        configuration={"as_of": as_of, "company": company},
    )


def _prediction_case(snapshots, runs):
    accounts = InMemoryUserAccountRepository(
        [
            UserAccount(
                user_id=uuid4(),
                email="investor@example.com",
                username="investor",
                api_key_digest=sha256(b"key").hexdigest(),
            )
        ]
    )
    theses = InMemoryInvestmentThesisRepository()
    ManageInvestmentTheses(accounts, theses).create(
        api_key="key",
        companies=("AAPL",),
        risk_tolerance=RiskTolerance.MEDIUM,
        investment_horizon=InvestmentHorizon.LONG_TERM,
        investment_style=InvestmentStyle.PASSIVE,
        description=None,
    )
    predictions = InMemoryPredictionRepository()
    return (
        GeneratePrediction(
            accounts,
            theses,
            InMemorySnapshotRepository(snapshots),
            predictions,
            InMemoryExperimentRunRepository(runs),
        ),
        predictions,
    )


def _execute(use_case):
    return use_case.execute(api_key="key", company="AAPL", as_of=date(2025, 2, 1), forecast_horizon_days=20)


def test_latest_run_uses_start_time_not_id_or_completion_time() -> None:
    older = replace(_run("run-z", 1), completed_at=datetime(2026, 8, 26, 4, tzinfo=timezone.utc))
    newer = _run("run-a", 2)
    use_case, _ = _prediction_case(_snapshots(thesis_run="run-z") + _snapshots(thesis_run="run-a"), [newer, older])
    assert _execute(use_case).run_id == "run-a"


def test_explicit_frozen_scope_never_selects_operational_snapshots_or_falls_back():
    frozen = replace(
        _run("frozen", 1), configuration={"as_of": "2025-02-01", "company": "AAPL", "source_scope": "frozen"}
    )
    operational = replace(
        _run("operational", 2), configuration={"as_of": "2025-02-01", "company": "AAPL", "source_scope": "operational"}
    )
    use_case, _ = _prediction_case(
        _snapshots(thesis_run="frozen") + _snapshots(thesis_run="operational"), [frozen, operational]
    )
    assert (
        use_case.execute(
            api_key="key", company="AAPL", as_of=date(2025, 2, 1), forecast_horizon_days=20, source_scope="frozen"
        ).run_id
        == "frozen"
    )
    failed = replace(
        frozen,
        run_id="failed-frozen",
        started_at=operational.started_at + timedelta(hours=1),
        status="failed",
        completed_at=None,
    )
    use_case, _ = _prediction_case(_snapshots(thesis_run="frozen"), [frozen, operational, failed])
    with pytest.raises(PredictionUnavailableError):
        use_case.execute(
            api_key="key", company="AAPL", as_of=date(2025, 2, 1), forecast_horizon_days=20, source_scope="frozen"
        )


@pytest.mark.parametrize(
    ("status", "windows"),
    [
        ("failed", 0),
        ("failed", 1),
        ("failed", 2),
        ("started", 0),
        ("started", 1),
        ("started", 2),
        ("completed", 0),
        ("completed", 1),
    ],
)
def test_unusable_latest_run_never_falls_back_to_older_snapshots(status, windows) -> None:
    snapshots = _snapshots(thesis_run="run-z") + _snapshots(thesis_run="run-a")[:windows]
    use_case, predictions = _prediction_case(snapshots, [_run("run-z", 1), _run("run-a", 2, status=status)])
    with pytest.raises(PredictionUnavailableError, match="prediction snapshots unavailable"):
        _execute(use_case)
    assert predictions.list_for_company("AAPL") == ()


def test_selection_ignores_other_company_dates_and_non_scoring_runs() -> None:
    use_case, _ = _prediction_case(
        _snapshots(thesis_run="run-a"),
        [
            _run("run-a", 1),
            _run("other-company", 2, company="MSFT"),
            _run("other-date", 3, as_of="2025-02-02"),
            _run("evaluation", 4, run_type="evaluation"),
        ],
    )
    assert _execute(use_case).run_id == "run-a"


def test_start_time_ties_are_deterministic() -> None:
    use_case, _ = _prediction_case(
        _snapshots(thesis_run="run-z") + _snapshots(thesis_run="run-a"), [_run("run-z", 1), _run("run-a", 1)]
    )
    assert _execute(use_case).run_id == "run-z"


def test_missing_run_metadata_cannot_supply_prediction() -> None:
    use_case, _ = _prediction_case(_snapshots(thesis_run="unknown"), [])
    with pytest.raises(PredictionUnavailableError):
        _execute(use_case)


def test_snapshot_windows_must_match_exact_requested_date() -> None:
    snapshots = (_snapshots(thesis_run="run-a")[0], replace(_snapshots(thesis_run="run-a")[1], as_of=date(2025, 1, 31)))
    use_case, _ = _prediction_case(snapshots, [_run("run-a", 1)])
    with pytest.raises(PredictionUnavailableError):
        _execute(use_case)
