FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.2 /uv /uvx /bin/

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY web ./web
COPY demo ./demo

RUN uv sync --frozen --no-dev

EXPOSE 8000

CMD ["uv", "run", "--no-sync", "uvicorn", "sentiment_system.bootstrap.main:app", "--host", "0.0.0.0", "--port", "8000"]
