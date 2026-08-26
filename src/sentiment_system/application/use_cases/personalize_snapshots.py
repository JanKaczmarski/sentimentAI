"""Use case for deterministic Investment Thesis personalization."""

from dataclasses import dataclass
from datetime import date

from sentiment_system.application.ports.repositories import SnapshotRepository
from sentiment_system.domain.investment_thesis import (
    InvestmentHorizon,
    InvestmentStyle,
    InvestmentThesis,
    RiskTolerance,
)
from sentiment_system.domain.predictions import (
    CompanySentimentSnapshot,
    PredictionEvidence,
    SnapshotWindow,
    sort_evidence,
)
from sentiment_system.domain.sentiment import PersonalizedSentiment, SentimentLabel, SentimentScore

RULE_VERSION = "aggregation-personalization-v1"


@dataclass(frozen=True, slots=True)
class PersonalizationResult:
    """Personalized values and their reusable source evidence."""

    base_sentiment: SentimentScore
    personalized_sentiment: PersonalizedSentiment
    evidence: tuple[PredictionEvidence, ...]
    run_id: str
    rule_version: str


class MissingSnapshotError(ValueError):
    """Raised when a required snapshot is unavailable for the requested run."""


class PersonalizeSnapshots:
    """Apply the approved horizon, style, and risk rules without an LLM call."""

    def __init__(self, snapshots: SnapshotRepository) -> None:
        self._snapshots = snapshots

    def execute(
        self,
        *,
        company: str,
        as_of: date,
        thesis: InvestmentThesis,
        run_id: str,
    ) -> PersonalizationResult:
        selected = self._select_snapshots(company=company, as_of=as_of, thesis=thesis, run_id=run_id)
        short, long = selected
        short_weight, long_weight = _style_weights(thesis.investment_style)
        personalized_score = short.sentiment.score * short_weight + long.sentiment.score * long_weight
        personalized_confidence = short.sentiment.confidence * short_weight + long.sentiment.confidence * long_weight
        base_sentiment = SentimentScore(
            score=(short.sentiment.score + long.sentiment.score) / 2,
            confidence=(short.sentiment.confidence + long.sentiment.confidence) / 2,
        )
        negative_at, positive_at = _risk_thresholds(thesis.risk_tolerance)
        return PersonalizationResult(
            base_sentiment=base_sentiment,
            personalized_sentiment=PersonalizedSentiment(
                score=personalized_score,
                confidence=personalized_confidence,
                label=_label(personalized_score, negative_at=negative_at, positive_at=positive_at),
            ),
            evidence=_merge_evidence(selected),
            run_id=run_id,
            rule_version=RULE_VERSION,
        )

    def _select_snapshots(
        self,
        *,
        company: str,
        as_of: date,
        thesis: InvestmentThesis,
        run_id: str,
    ) -> tuple[CompanySentimentSnapshot, CompanySentimentSnapshot]:
        if thesis.investment_horizon is InvestmentHorizon.SHORT_TERM:
            windows = (SnapshotWindow.THIRTY_DAYS, SnapshotWindow.NINETY_DAYS)
        else:
            windows = (SnapshotWindow.NINETY_DAYS, SnapshotWindow.YEAR)
        available = {
            snapshot.window_days: snapshot
            for snapshot in self._snapshots.list_for_company(company, as_of=as_of)
            if snapshot.run_id == run_id
        }
        try:
            return available[windows[0]], available[windows[1]]
        except KeyError as error:
            raise MissingSnapshotError(f"required snapshot is missing for {company} and run {run_id}") from error


def _style_weights(style: InvestmentStyle) -> tuple[float, float]:
    if style is InvestmentStyle.ACTIVE:
        return 0.70, 0.30
    return 0.30, 0.70


def _risk_thresholds(risk: RiskTolerance) -> tuple[float, float]:
    return {
        RiskTolerance.LOW: (0.30, 0.70),
        RiskTolerance.MEDIUM: (0.40, 0.60),
        RiskTolerance.HIGH: (0.45, 0.55),
    }[risk]


def _label(score: float, *, negative_at: float, positive_at: float) -> SentimentLabel:
    if score <= negative_at:
        return SentimentLabel.NEGATIVE
    if score >= positive_at:
        return SentimentLabel.POSITIVE
    return SentimentLabel.NEUTRAL


def _merge_evidence(
    snapshots: tuple[CompanySentimentSnapshot, CompanySentimentSnapshot],
) -> tuple[PredictionEvidence, ...]:
    evidence: list[PredictionEvidence] = []
    seen: set[str] = set()
    for snapshot in snapshots:
        for item in snapshot.evidence:
            if item.chunk_id not in seen:
                seen.add(item.chunk_id)
                evidence.append(item)
    return sort_evidence(evidence)
