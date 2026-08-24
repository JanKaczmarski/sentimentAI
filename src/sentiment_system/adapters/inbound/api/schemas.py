"""API request and response schemas kept separate from domain entities."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sentiment_system.domain.accounts import normalize_email, normalize_username


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
