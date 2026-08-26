"""Application entrypoint for the API and scheduler runtime."""

from pathlib import Path

from fastapi import FastAPI
from prometheus_client import make_asgi_app
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from sentiment_system.adapters.inbound.api.routes import router
from sentiment_system.bootstrap.container import ApplicationContainer, build_container

WEB_ROOT = Path(__file__).resolve().parents[3] / "web"


def redirect_to_ui() -> RedirectResponse:
    """Redirect the UI shorthand to the static application's entrypoint."""
    return RedirectResponse(url="/ui/")


def create_app(*, container: ApplicationContainer | None = None) -> FastAPI:
    """Create the minimal application used by local development and Compose."""
    app = FastAPI(
        title="Personalized Financial Sentiment System",
        version="0.1.0",
    )
    app.state.container = container if container is not None else build_container()
    app.include_router(router)
    app.mount("/metrics", make_asgi_app())
    app.add_api_route("/ui", redirect_to_ui, include_in_schema=False)
    app.mount("/ui", StaticFiles(directory=WEB_ROOT, html=True), name="ui")
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
