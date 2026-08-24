"""HTTP routes for accounts, Investment Theses, predictions, history, and batches."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sentiment_system.adapters.inbound.api.schemas import AccountCreateRequest, AccountCreateResponse
from sentiment_system.application.use_cases.create_account import (
    AccountEmailInUseError,
    AccountUsernameInUseError,
    CreateAccount,
)

router = APIRouter()


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return a lightweight process health response for local tooling."""
    return {"status": "ok"}


def get_create_account(request: Request) -> CreateAccount:
    """Resolve the account use case from the application composition root."""
    create_account = cast(CreateAccount | None, request.app.state.container.create_account)
    if create_account is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="account service unavailable")
    return create_account


@router.post(
    "/user/account",
    response_model=AccountCreateResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_409_CONFLICT: {
            "description": "An account already uses the supplied email or username.",
            "content": {
                "application/json": {
                    "examples": {
                        "email_in_use": {"value": {"detail": "email in use"}},
                        "username_in_use": {"value": {"detail": "username in use"}},
                    }
                }
            },
        }
    },
    tags=["user"],
)
def create_account(
    request: AccountCreateRequest,
    use_case: Annotated[CreateAccount, Depends(get_create_account)],
) -> AccountCreateResponse:
    """Create an investor account and return its API key once."""
    try:
        created_account = use_case.execute(email=request.email, username=request.username)
    except AccountEmailInUseError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email in use") from error
    except AccountUsernameInUseError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username in use") from error

    return AccountCreateResponse(
        status="success",
        user_id=created_account.user_id,
        api_key=created_account.api_key,
    )
