"""HTTP routes for accounts, Investment Theses, predictions, history, and batches."""

from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status

from sentiment_system.adapters.inbound.api.schemas import (
    AccountCreateRequest,
    AccountCreateResponse,
    BatchRunRequest,
    BatchRunResponse,
    FixtureCommunicationRequest,
    FixtureIngestionResponse,
    InvestmentThesisRequest,
    InvestmentThesisResponse,
    PredictionEvidenceResponse,
    PredictionHistoryResponse,
    PredictionResponse,
    SentimentResponse,
    ThesisListResponse,
    ThesisWriteResponse,
)
from sentiment_system.application.use_cases.create_account import (
    AccountEmailInUseError,
    AccountUsernameInUseError,
    CreateAccount,
)
from sentiment_system.application.use_cases.generate_prediction import (
    GeneratePrediction,
    InvalidForecastHorizonError,
    ListPredictionHistory,
    PredictionAccountNotFoundError,
    PredictionThesisNotFoundError,
    PredictionUnavailableError,
)
from sentiment_system.application.use_cases.ingest_fixture_communication import IngestFixtureCommunication
from sentiment_system.application.use_cases.manage_investment_theses import (
    AccountNotFoundError,
    ManageInvestmentTheses,
    ThesisNotFoundError,
    UnsupportedCompanyError,
)
from sentiment_system.application.use_cases.run_batch import BatchExecutionError, RunBatch
from sentiment_system.domain.companies import APPROVED_COMPANY_REGISTRY
from sentiment_system.domain.investment_thesis import InvestmentThesis
from sentiment_system.domain.predictions import Prediction

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


def get_generate_prediction(request: Request) -> GeneratePrediction:
    """Resolve the prediction generation use case."""
    use_case = cast(GeneratePrediction | None, request.app.state.container.generate_prediction)
    if use_case is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="prediction service unavailable")
    return use_case


def get_list_prediction_history(request: Request) -> ListPredictionHistory:
    """Resolve the user-scoped prediction history use case."""
    use_case = cast(ListPredictionHistory | None, request.app.state.container.list_prediction_history)
    if use_case is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="history service unavailable")
    return use_case


def get_fixture_ingestion(request: Request) -> IngestFixtureCommunication:
    """Resolve fixture communication ingestion from the composition root."""
    use_case = cast(IngestFixtureCommunication | None, request.app.state.container.ingest_fixture_communication)
    if use_case is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="ingestion service unavailable")
    return use_case


def get_run_batch(request: Request) -> RunBatch:
    """Resolve the manual batch use case from the application container."""
    use_case = cast(RunBatch | None, request.app.state.container.run_batch)
    if use_case is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="batch service unavailable")
    return use_case


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


@router.get("/companies/{company}/prediction", response_model=PredictionResponse, tags=["prediction"])
def get_prediction(
    company: str,
    api_key: str,
    use_case: Annotated[GeneratePrediction, Depends(get_generate_prediction)],
    forecast_horizon_days: int = 20,
    as_of: date | None = None,
) -> PredictionResponse:
    """Generate and return the latest personalized prediction for a company."""
    try:
        prediction = use_case.execute(
            api_key=api_key,
            company=company,
            as_of=as_of or date.today(),
            forecast_horizon_days=forecast_horizon_days,
        )
    except (PredictionAccountNotFoundError, PredictionThesisNotFoundError, PredictionUnavailableError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except InvalidForecastHorizonError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return _prediction_response(prediction)


@router.get("/user/history/{user_id}", response_model=PredictionHistoryResponse, tags=["prediction"])
def get_prediction_history(
    user_id: str,
    api_key: str,
    use_case: Annotated[ListPredictionHistory, Depends(get_list_prediction_history)],
) -> PredictionHistoryResponse:
    """Return only the authenticated user's stored prediction history."""
    try:
        predictions = use_case.execute(api_key=api_key, user_id=user_id)
    except PredictionAccountNotFoundError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="history not found") from error
    return PredictionHistoryResponse(predictions=tuple(_prediction_response(item) for item in predictions))


@router.post(
    "/companies/{company}",
    response_model=FixtureIngestionResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["ingestion"],
)
def ingest_company_fixture(
    company: str,
    request: FixtureCommunicationRequest,
    use_case: Annotated[IngestFixtureCommunication, Depends(get_fixture_ingestion)],
) -> FixtureIngestionResponse:
    """Normalize and persist one fixture-based company communication."""
    try:
        ticker = APPROVED_COMPANY_REGISTRY.lookup(company).ticker
        result = use_case.execute(company=ticker, **request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)) from error
    return FixtureIngestionResponse(
        status="success",
        document_id=result.documents[0].document_id,
        chunk_count=len(result.chunks),
    )


@router.post("/batch/run", response_model=BatchRunResponse, tags=["batch"])
def run_batch(
    request: BatchRunRequest,
    use_case: Annotated[RunBatch, Depends(get_run_batch)],
) -> BatchRunResponse:
    """Trigger one deterministic POC batch without investor-specific scoring."""
    try:
        result = use_case.execute(as_of=request.as_of or date.today(), company=request.company)
    except BatchExecutionError as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"batch run failed: {error.run_id}",
        ) from error
    return BatchRunResponse(
        status="completed",
        run_id=result.run_id,
        document_count=result.document_count,
        chunk_count=result.chunk_count,
        indexed_chunk_count=result.indexed_chunk_count,
        scored_chunk_count=result.scored_chunk_count,
        snapshot_count=result.snapshot_count,
        companies=result.companies,
    )


def _prediction_response(prediction: Prediction) -> PredictionResponse:
    return PredictionResponse(
        company=prediction.company,
        as_of=prediction.as_of,
        lookback_days=int(prediction.lookback_days),
        forecast_horizon_days=prediction.forecast_horizon_days,
        base_sentiment=SentimentResponse(
            score=prediction.base_sentiment.score,
            label=prediction.base_sentiment.label.value,
            confidence=prediction.base_sentiment.confidence,
        ),
        personalized_sentiment=SentimentResponse(
            score=prediction.personalized_sentiment.score,
            label=prediction.personalized_sentiment.label.value,
            confidence=prediction.personalized_sentiment.confidence,
        ),
        confidence=prediction.confidence,
        reasoning=prediction.reasoning,
        evidence=tuple(
            PredictionEvidenceResponse(
                chunk_id=item.chunk_id,
                published_at=item.published_at,
                importance_score=item.importance_score,
                excerpt=item.excerpt,
            )
            for item in prediction.evidence
        ),
        run_id=prediction.run_id,
        user_id=prediction.user_id,
    )
