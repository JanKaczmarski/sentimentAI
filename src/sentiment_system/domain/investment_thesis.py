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

    thesis_id: str
    user_id: str
    companies: tuple[str, ...]
    risk_tolerance: RiskTolerance
    investment_horizon: InvestmentHorizon
    investment_style: InvestmentStyle
    description: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_string("thesis_id", self.thesis_id)
        _require_non_empty_string("user_id", self.user_id)
        if not isinstance(self.companies, tuple) or not self.companies:
            raise ValueError("at least one company is required")
        if any(not isinstance(company, str) or not company.strip() for company in self.companies):
            raise ValueError("companies must contain non-empty strings")
        if not isinstance(self.risk_tolerance, RiskTolerance):
            raise ValueError("risk_tolerance must be a RiskTolerance")
        if not isinstance(self.investment_horizon, InvestmentHorizon):
            raise ValueError("investment_horizon must be an InvestmentHorizon")
        if not isinstance(self.investment_style, InvestmentStyle):
            raise ValueError("investment_style must be an InvestmentStyle")
        if self.description is not None and not isinstance(self.description, str):
            raise ValueError("description must be a string")

    @property
    def lookback_days(self) -> int:
        """Return the initial company-sentiment window selected by the thesis."""
        if self.investment_horizon is InvestmentHorizon.SHORT_TERM:
            return 30
        return 365


def _require_non_empty_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
