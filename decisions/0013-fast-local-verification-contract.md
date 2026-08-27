# Fast Local Verification Contract

**Status:** Accepted
**Date:** 2026-08-27

## Purpose

Keep ordinary implementation feedback fast and independent of containerized
infrastructure while retaining explicit Compose and end-to-end validation for
CI and human demonstrations.

## Decision

- `make test` and `make check` are local, Docker-free commands.
- Local unit, API, batch, cached-data, formatting, lint, typing, build, and audit
  checks use `uv`, in-memory repositories, fake providers, or local data.
- PostgreSQL, Qdrant, Docker Compose, and containerized application checks run
  only as explicit infrastructure/e2e validation, human demonstrations,
  long-lived local servers, or GitHub Actions CI.
- The default feature verification profile contains no Docker command.
- Compose validation remains available through `make compose-config` and CI.

## Consequences

Source edits no longer require rebuilding the application image or starting
containers. Infrastructure regressions are still covered by dedicated CI and
explicit deployment checks, but they are not hidden inside the fast local loop.
