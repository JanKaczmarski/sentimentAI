# Local Browser UI Decision

**Status:** Decided

**Date:** 2026-08-26

## Decision

- Provide a small same-origin browser UI for local API smoke testing.
- Serve plain HTML, CSS, and JavaScript from the FastAPI application at `/ui/`.
- Reuse the existing REST API contracts instead of duplicating business logic in
  the browser.
- Keep the UI limited to local account and Investment Thesis workflows until
  `FEAT-014` defines the prediction, history, and fixture-ingestion contracts.
- Do not introduce a separate frontend service, build system, production
  authentication, or account recovery flow.

## Rationale

The UI removes the friction of testing the current API with curl while keeping
the modular monolith and local Docker Compose boundary unchanged. A no-build
same-origin implementation is sufficient for the thesis development workflow
and avoids adding a second runtime before the prediction API exists.
