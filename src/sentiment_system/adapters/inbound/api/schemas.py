"""API request and response schemas kept separate from domain entities."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiSchema(BaseModel):
    """Apply the common public-API validation policy."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AccountCreateRequest(ApiSchema):
    """Input for creating an unauthenticated investor account."""

    email: str = Field(min_length=1)
    username: str = Field(min_length=1)


class AccountCreateResponse(ApiSchema):
    """Account creation result; the API key is returned only once."""

    status: Literal["success"]
    user_id: UUID
    api_key: str
