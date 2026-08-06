"""HTTP routes for accounts, Investment Theses, predictions, history, and batches."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["system"])
def health() -> dict[str, str]:
    """Return a lightweight process health response for local tooling."""
    return {"status": "ok"}
