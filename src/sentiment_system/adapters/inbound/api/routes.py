"""HTTP routes for accounts, Investment Theses, predictions, history, and batches."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sentiment_system.adapters.inbound.api.schemas import (
    AccountCreateRequest,
    AccountCreateResponse,
    InvestmentThesisRequest,
    InvestmentThesisResponse,
    ThesisListResponse,
    ThesisWriteResponse,
)
from sentiment_system.application.use_cases.create_account import (
    AccountEmailInUseError,
    AccountUsernameInUseError,
    CreateAccount,
)
from sentiment_system.application.use_cases.manage_investment_theses import (
    AccountNotFoundError,
    ManageInvestmentTheses,
    ThesisNotFoundError,
    UnsupportedCompanyError,
)
from sentiment_system.domain.investment_thesis import InvestmentThesis

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


def get_manage_investment_theses(request: Request) -> ManageInvestmentTheses:
    """Resolve the thesis CRUD use case from the application composition root."""
    manage_theses = cast(ManageInvestmentTheses | None, request.app.state.container.manage_investment_theses)
    if manage_theses is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="thesis service unavailable")
    return manage_theses


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


@router.post("/user/strategy", response_model=ThesisWriteResponse, status_code=status.HTTP_201_CREATED, tags=["user"])
def create_strategy(
    request: InvestmentThesisRequest,
    api_key: str,
    use_case: Annotated[ManageInvestmentTheses, Depends(get_manage_investment_theses)],
) -> ThesisWriteResponse:
    """Create a structured thesis for the account selected by its API key."""
    try:
        thesis = use_case.create(api_key=api_key, **request.model_dump())
    except AccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found") from error
    return ThesisWriteResponse(status="success", thesis_id=thesis.thesis_id)


@router.put("/user/strategy/{thesis_id}", response_model=ThesisWriteResponse, tags=["user"])
def update_strategy(
    thesis_id: str,
    request: InvestmentThesisRequest,
    api_key: str,
    use_case: Annotated[ManageInvestmentTheses, Depends(get_manage_investment_theses)],
) -> ThesisWriteResponse:
    """Update one thesis owned by the account selected by its API key."""
    try:
        thesis = use_case.update(api_key=api_key, thesis_id=thesis_id, **request.model_dump())
    except AccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found") from error
    except ThesisNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="thesis not found") from error
    return ThesisWriteResponse(status="success", thesis_id=thesis.thesis_id)


@router.get("/user/strategy", response_model=ThesisListResponse, tags=["user"])
def list_strategies(
    api_key: str,
    use_case: Annotated[ManageInvestmentTheses, Depends(get_manage_investment_theses)],
) -> ThesisListResponse:
    """List all theses owned by the account selected by its API key."""
    try:
        theses = use_case.list_for_user(api_key=api_key)
    except AccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found") from error
    return ThesisListResponse(theses=tuple(_thesis_response(thesis) for thesis in theses))


@router.get("/user/strategy/{company}", response_model=ThesisListResponse, tags=["user"])
def list_strategies_for_company(
    company: str,
    api_key: str,
    use_case: Annotated[ManageInvestmentTheses, Depends(get_manage_investment_theses)],
) -> ThesisListResponse:
    """List the account's theses that apply to one approved company."""
    try:
        theses = use_case.list_for_company(api_key=api_key, company=company)
    except AccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="account not found") from error
    except UnsupportedCompanyError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return ThesisListResponse(theses=tuple(_thesis_response(thesis) for thesis in theses))


def _thesis_response(thesis: InvestmentThesis) -> InvestmentThesisResponse:
    return InvestmentThesisResponse(
        thesis_id=thesis.thesis_id,
        companies=thesis.companies,
        risk_tolerance=thesis.risk_tolerance,
        investment_horizon=thesis.investment_horizon,
        investment_style=thesis.investment_style,
        description=thesis.description,
    )
