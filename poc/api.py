"""
FastAPI routes for the Sentiment Analysis POC.

Endpoints:
  POST /users                         — create user profile
  GET  /users                         — list all users
  GET  /users/{user_id}               — get user profile
  GET  /users/{user_id}/predictions   — get latest sentiment predictions
  GET  /companies/{ticker}/prediction — get prediction for a ticker (requires user_id query param)
  POST /batch/run                     — trigger batch manually
  GET  /batch/status                  — get latest batch run status
  GET  /system/info                   — vector store stats + system info
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException

from poc.batch import run_batch
from poc.database import Database
from poc.models import UserProfileCreate
from poc.vector_store import VectorStore

router = APIRouter()

# These will be injected by main.py via app.state
_db: Database | None = None
_vs: VectorStore | None = None


def init_api(db: Database, vs: VectorStore):
    """Inject dependencies into the API module."""
    global _db, _vs
    _db = db
    _vs = vs


def _get_db() -> Database:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


def _get_vs() -> VectorStore:
    if _vs is None:
        raise RuntimeError("VectorStore not initialized")
    return _vs


# --- User endpoints ---

@router.post("/users", tags=["users"])
def create_user(data: UserProfileCreate):
    db = _get_db()
    user = db.create_user(data)
    return {"status": "success", "user": user.model_dump(mode="json")}


@router.get("/users", tags=["users"])
def list_users():
    db = _get_db()
    users = db.get_all_users()
    return {"users": [u.model_dump(mode="json") for u in users]}


@router.get("/users/{user_id}", tags=["users"])
def get_user(user_id: str):
    db = _get_db()
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user.model_dump(mode="json")


@router.get("/users/{user_id}/predictions", tags=["predictions"])
def get_user_predictions(user_id: str, batch_date: Optional[str] = None):
    db = _get_db()
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    dt = date.fromisoformat(batch_date) if batch_date else None
    results = db.get_sentiments_for_user(user_id, dt)

    return {
        "user_id": user_id,
        "user_name": user.name,
        "predictions": [r.model_dump(mode="json") for r in results],
    }


# --- Company predictions ---

@router.get("/companies/{ticker}/prediction", tags=["predictions"])
def get_company_prediction(ticker: str, user_id: str):
    db = _get_db()
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    result = db.get_latest_sentiment(user_id, ticker.upper())
    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No prediction found for {ticker}. Run a batch first.",
        )

    return result.model_dump(mode="json")


# --- Batch endpoints ---

@router.post("/batch/run", tags=["batch"])
def trigger_batch():
    db = _get_db()
    vs = _get_vs()
    batch_run = run_batch(db, vs)
    return {
        "status": batch_run.status,
        "batch_id": batch_run.batch_id,
        "results_generated": batch_run.results_generated,
        "tickers_processed": batch_run.tickers_processed,
        "users_processed": batch_run.users_processed,
    }


@router.get("/batch/status", tags=["batch"])
def batch_status():
    db = _get_db()
    latest = db.get_latest_batch_run()
    if not latest:
        return {"status": "no_runs", "message": "No batch runs yet."}
    return latest.model_dump(mode="json")


# --- System ---

@router.get("/system/info", tags=["system"])
def system_info():
    vs = _get_vs()
    return {
        "vector_store": vs.get_collection_info(),
    }
