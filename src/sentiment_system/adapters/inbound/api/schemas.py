"""API request and response schemas kept separate from domain entities."""

from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentiment_system.domain.accounts import normalize_email, normalize_username
from sentiment_system.domain.companies import APPROVED_COMPANY_REGISTRY
from sentiment_system.domain.investment_thesis import InvestmentHorizon, InvestmentStyle, RiskTolerance


class ApiSchema(BaseModel):
    """Apply the common public-API validation policy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountCreateRequest(ApiSchema):
    """Input for creating an unauthenticated investor account."""

    email: str = Field(min_length=1)
    username: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        """Validate and canonicalize the account email before the use case."""
        return normalize_email(value)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """Validate and canonicalize the account username before the use case."""
        return normalize_username(value)


class AccountCreateResponse(ApiSchema):
    """Account creation result; the API key is returned only once."""

    status: Literal["success"]
    user_id: UUID
    api_key: str


class InvestmentThesisRequest(ApiSchema):
    """Input for a structured company or company-group Investment Thesis."""

    companies: tuple[str, ...] = Field(min_length=1)
    risk_tolerance: RiskTolerance
    investment_horizon: InvestmentHorizon
    investment_style: InvestmentStyle
    description: str | None = None

    @field_validator("companies")
    @classmethod
    def validate_companies(cls, companies: tuple[str, ...]) -> tuple[str, ...]:
        """Normalize every submitted ticker against the canonical registry."""
        return tuple(APPROVED_COMPANY_REGISTRY.lookup(company).ticker for company in companies)


class ThesisWriteResponse(ApiSchema):
    """Stable identifier returned after creating or updating a thesis."""

    status: Literal["success"]
    thesis_id: str


class InvestmentThesisResponse(ApiSchema):
    """One stored structured Investment Thesis."""

    thesis_id: str
    companies: tuple[str, ...]
    risk_tolerance: RiskTolerance
    investment_horizon: InvestmentHorizon
    investment_style: InvestmentStyle
    description: str | None


class ThesisListResponse(ApiSchema):
    """All theses visible to the account selected by the API key."""

    theses: tuple[InvestmentThesisResponse, ...]


class FixtureCommunicationRequest(ApiSchema):
    """Input for fixture-based company communication ingestion."""

    document_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    published_at: date
    document_type: str = Field(min_length=1)
    raw_content: str = Field(min_length=1)


class FixtureIngestionResponse(ApiSchema):
    """Summary of one normalized fixture communication."""

    status: Literal["success"]
    document_id: str
    chunk_count: int


class BatchRunRequest(ApiSchema):
    """Optional scope for a manual source-to-prediction batch."""

    company: str | None = None
    as_of: date | None = None

    @field_validator("company")
    @classmethod
    def validate_company(cls, company: str | None) -> str | None:
        """Normalize an optional company against the canonical registry."""
        return None if company is None else APPROVED_COMPANY_REGISTRY.lookup(company).ticker


class BatchRunResponse(ApiSchema):
    """Counts and run identity returned by a completed manual batch."""

    status: Literal["completed"]
    run_id: str
    document_count: int
    chunk_count: int
    indexed_chunk_count: int
    scored_chunk_count: int
    snapshot_count: int
    companies: tuple[str, ...]


class SentimentResponse(ApiSchema):
    """Public sentiment score and derived label."""

    score: float
    label: str
    confidence: float


class PredictionEvidenceResponse(ApiSchema):
    """Public source evidence attached to a prediction."""

    chunk_id: str
    published_at: date
    sentiment: SentimentResponse
    importance_score: float
    excerpt: str


class PredictionResponse(ApiSchema):
    """Public prediction with base, personalized, and audit fields."""

    company: str
    as_of: date
    lookback_days: int
    forecast_horizon_days: int
    base_sentiment: SentimentResponse
    personalized_sentiment: SentimentResponse
    confidence: float
    reasoning: str | None
    evidence: tuple[PredictionEvidenceResponse, ...]
    run_id: str
    user_id: str | None


class PredictionHistoryResponse(ApiSchema):
    """Prediction history for one authenticated user."""

    predictions: tuple[PredictionResponse, ...]
