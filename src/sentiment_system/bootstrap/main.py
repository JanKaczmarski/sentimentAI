"""Application entrypoint for the API and scheduler runtime."""

from fastapi import FastAPI
from prometheus_client import make_asgi_app

from sentiment_system.adapters.inbound.api.routes import router


def create_app() -> FastAPI:
    """Create the minimal application used by local development and Compose."""
    app = FastAPI(
        title="Personalized Financial Sentiment System",
        version="0.1.0",
    )
    app.include_router(router)
    app.mount("/metrics", make_asgi_app())
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
