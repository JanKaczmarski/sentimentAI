"""Tests for sentiment score, label, and confidence rules."""

import pytest

from sentiment_system.domain.sentiment import SentimentLabel, SentimentScore


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, SentimentLabel.NEGATIVE),
        (0.399, SentimentLabel.NEGATIVE),
        (0.4, SentimentLabel.NEUTRAL),
        (0.6, SentimentLabel.NEUTRAL),
        (0.601, SentimentLabel.POSITIVE),
        (1.0, SentimentLabel.POSITIVE),
    ],
)
def test_score_derives_label(score: float, expected: SentimentLabel) -> None:
    assert SentimentScore(score=score, confidence=0.8).label is expected


def test_score_rejects_values_outside_zero_to_one() -> None:
    with pytest.raises(ValueError, match="score must be between 0 and 1"):
        SentimentScore(score=1.1, confidence=0.8)


def test_confidence_rejects_values_outside_zero_to_one() -> None:
    with pytest.raises(ValueError, match="confidence must be between 0 and 1"):
        SentimentScore(score=0.5, confidence=-0.1)
