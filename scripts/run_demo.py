"""Branch-local Groq demo using fixtures and ephemeral storage."""

import os
from pathlib import Path

from dotenv import load_dotenv


def configure_demo() -> None:
    """Read only demo settings and explicitly select the existing adapters."""
    load_dotenv(Path(__file__).resolve().parents[1] / ".env.demo")
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Set GROQ_API_KEY in .env.demo (see .env.demo.example).")
    os.environ.update(
        APP_ENV="development",
        DATABASE_URL="",
        QDRANT_URL="",
        SENTIMENT_DATA_ROOT="",
        LLM_BACKEND="ollama",
        LLM_BASE_URL="https://api.groq.com/openai/v1",
        LLM_API_KEY=api_key,
        LLM_MODEL=os.environ.get("DEMO_MODEL", "openai/gpt-oss-20b"),
        EMBEDDING_BACKEND=os.environ.get("DEMO_EMBEDDING_BACKEND", "mock"),
        EMBEDDING_MODEL="BAAI/bge-small-en-v1.5",
    )


def main() -> None:
    configure_demo()
    import uvicorn

    uvicorn.run("sentiment_system.bootstrap.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
