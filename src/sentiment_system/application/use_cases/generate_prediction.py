"""Use cases for assembling predictions and reading user-scoped history."""

from collections.abc import Iterable
from datetime import date
from hashlib import sha256

from sentiment_system.application.ports.repositories import (
    InvestmentThesisRepository,
    PredictionRepository,
    SnapshotRepository,
    UserAccountRepository,
)
from sentiment_system.application.use_cases.personalize_snapshots import (
    MissingSnapshotError,
    PersonalizeSnapshots,
)
from sentiment_system.domain.accounts import UserAccount
from sentiment_system.domain.predictions import CompanySentimentSnapshot, Prediction, SnapshotWindow


class PredictionAccountNotFoundError(ValueError):
    """Raised when a prediction request has no matching account."""


class PredictionThesisNotFoundError(ValueError):
    """Raised when an account has no thesis for the requested company."""


class PredictionUnavailableError(ValueError):
    """Raised when the requested company has no complete snapshot run."""


class InvalidForecastHorizonError(ValueError):
    """Raised when a request uses an unsupported forward horizon."""


class GeneratePrediction:
    """Generate and persist one prediction from reusable sentiment snapshots."""

    _ALLOWED_HORIZONS = {1, 5, 20, 60, 252}

    def __init__(
        self,
        accounts: UserAccountRepository,
        theses: InvestmentThesisRepository,
        snapshots: SnapshotRepository,
        predictions: PredictionRepository,
    ) -> None:
        self._accounts = accounts
        self._theses = theses
        self._snapshots = snapshots
        self._predictions = predictions
        self._personalize = PersonalizeSnapshots(snapshots)

    def execute(
        self,
        *,
        api_key: str,
        company: str,
        as_of: date,
        forecast_horizon_days: int,
    ) -> Prediction:
        if forecast_horizon_days not in self._ALLOWED_HORIZONS:
            raise InvalidForecastHorizonError("forecast_horizon_days must be one of 1, 5, 20, 60, or 252")
        account = self._account(api_key)
        ticker = company.upper()
        thesis = next(
            (item for item in self._theses.list_for_user(str(account.user_id)) if ticker in item.companies),
            None,
        )
        if thesis is None:
            raise PredictionThesisNotFoundError("thesis not found")

        result = None
        for run_id in reversed(_run_ids(self._snapshots.list_for_company(ticker, as_of=as_of))):
            try:
                result = self._personalize.execute(
                    company=ticker,
                    as_of=as_of,
                    thesis=thesis,
                    run_id=run_id,
                )
                break
            except MissingSnapshotError:
                continue
        if result is None:
            raise PredictionUnavailableError("prediction snapshots unavailable")

        prediction = Prediction(
            company=ticker,
            as_of=as_of,
            lookback_days=SnapshotWindow(thesis.lookback_days),
            forecast_horizon_days=forecast_horizon_days,
            base_sentiment=result.base_sentiment,
            personalized_sentiment=result.personalized_sentiment,
            confidence=result.personalized_sentiment.confidence,
            evidence=result.evidence,
            run_id=result.run_id,
            reasoning=(
                f"Applied {thesis.investment_horizon.value} horizon and "
                f"{thesis.investment_style.value} investment-style weighting."
            ),
            user_id=str(account.user_id),
        )
        self._predictions.save(prediction)
        return prediction

    def _account(self, api_key: str) -> UserAccount:
        account = self._accounts.get_by_api_key_digest(sha256(api_key.encode("utf-8")).hexdigest())
        if account is None:
            raise PredictionAccountNotFoundError("account not found")
        return account


class ListPredictionHistory:
    """Return prediction history only for the account selected by its API key."""

    def __init__(self, accounts: UserAccountRepository, predictions: PredictionRepository) -> None:
        self._accounts = accounts
        self._predictions = predictions

    def execute(self, *, api_key: str, user_id: str) -> tuple[Prediction, ...]:
        account = self._accounts.get_by_api_key_digest(sha256(api_key.encode("utf-8")).hexdigest())
        if account is None or str(account.user_id) != user_id:
            raise PredictionAccountNotFoundError("account not found")
        return self._predictions.list_for_user(str(account.user_id))


def _run_ids(predictions: Iterable[CompanySentimentSnapshot]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.run_id for item in predictions))
