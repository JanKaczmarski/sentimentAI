"""API request and response schemas kept separate from domain entities."""

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
