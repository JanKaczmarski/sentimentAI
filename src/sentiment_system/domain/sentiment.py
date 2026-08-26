"""Sentiment polarity, labels, confidence, and score conversion rules."""

from dataclasses import dataclass
from enum import Enum
from math import isfinite


class SentimentLabel(str, Enum):
    """Categorical label derived from a continuous polarity score."""

    NEGATIVE = "NEGATIVE"
    NEUTRAL = "NEUTRAL"
    POSITIVE = "POSITIVE"


@dataclass(frozen=True, slots=True)
class SentimentScore:
    """Continuous polarity and model confidence, both normalized to ``0..1``."""

    score: float
    confidence: float

    def __post_init__(self) -> None:
        self._validate_range("score", self.score)
        self._validate_range("confidence", self.confidence)

    @property
    def label(self) -> SentimentLabel:
        """Return the configured three-class label for this polarity score."""
        if self.score < 0.4:
            return SentimentLabel.NEGATIVE
        if self.score > 0.6:
            return SentimentLabel.POSITIVE
        return SentimentLabel.NEUTRAL

    @staticmethod
    def _validate_range(name: str, value: float) -> None:
        if not isfinite(value) or not 0 <= value <= 1:
            raise ValueError(f"{name} must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class PersonalizedSentiment:
    """A sentiment value with a thesis-specific decision label."""

    score: float
    confidence: float
    label: SentimentLabel

    def __post_init__(self) -> None:
        SentimentScore._validate_range("score", self.score)
        SentimentScore._validate_range("confidence", self.confidence)
        if not isinstance(self.label, SentimentLabel):
            raise ValueError("label must be a SentimentLabel")
