"""Company/group Investment Thesis entities and deterministic personalization rules."""

from dataclasses import dataclass
from enum import Enum


class RiskTolerance(str, Enum):
    """Investor tolerance for risk."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class InvestmentHorizon(str, Enum):
    """Supported thesis lookback horizons."""

    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"


class InvestmentStyle(str, Enum):
    """High-level investment style used by personalization rules."""

    PASSIVE = "passive"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class InvestmentThesis:
    """Structured thesis assigned to one or more companies."""

    user_id: str
    companies: tuple[str, ...]
    risk_tolerance: RiskTolerance
    investment_horizon: InvestmentHorizon
    investment_style: InvestmentStyle
    description: str | None = None

    def __post_init__(self) -> None:
        if not self.user_id:
            raise ValueError("user_id is required")
        if not self.companies:
            raise ValueError("at least one company is required")

    @property
    def lookback_days(self) -> int:
        """Return the initial company-sentiment window selected by the thesis."""
        if self.investment_horizon is InvestmentHorizon.SHORT_TERM:
            return 30
        return 365
