"""Tests for public API request and response contracts."""

from uuid import UUID

import pytest
from pydantic import ValidationError

from sentiment_system.adapters.inbound.api.schemas import AccountCreateRequest, AccountCreateResponse


def test_account_schemas_preserve_the_documented_http_contract() -> None:
    request = AccountCreateRequest(email=" investor@example.com ", username=" investor ")
    response = AccountCreateResponse(
        status="success",
        user_id=UUID("a66b7cd0-e219-4e17-8729-4c49b0a65624"),
        api_key="returned-once-server-generated-api-key",
    )

    assert request.email == "investor@example.com"
    assert request.username == "investor"
    assert response.model_dump(mode="json") == {
        "status": "success",
        "user_id": "a66b7cd0-e219-4e17-8729-4c49b0a65624",
        "api_key": "returned-once-server-generated-api-key",
    }


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"username": "investor"}, "email"),
        ({"email": "investor@example.com"}, "username"),
        ({"email": "investor@example.com", "username": "investor", "ignored": True}, "ignored"),
    ],
)
def test_account_create_request_rejects_missing_or_unknown_fields(payload: dict[str, object], field: str) -> None:
    with pytest.raises(ValidationError) as error:
        AccountCreateRequest.model_validate(payload)

    assert error.value.errors()[0]["loc"] == (field,)
