.DEFAULT_GOAL := help

UV ?= uv
COMPOSE ?= docker compose
PROJECT_PATHS := src tests scripts

.PHONY: help sync install format format-check lint test test-unit test-integration compile build audit governance compose-config lock-check diff-check check deploy up down logs status run

help:
	@printf '%s\n' \
		"make sync             Install locked project dependencies" \
		"make test             Run the local test suite without Docker" \
		"make check            Run fast checks without Docker" \
		"make format           Format source, tests, and scripts" \
		"make compose-config   Validate Compose configuration explicitly" \
		"make deploy           Start the local Docker Compose stack in the background" \
		"make up               Start the local Docker Compose stack in the foreground" \
		"make down             Stop the local Docker Compose stack" \
		"make logs             Follow local service logs" \
		"make status           Show local service status"

sync:
	$(UV) sync --locked

install: sync

format:
	$(UV) run black $(PROJECT_PATHS)
	$(UV) run isort $(PROJECT_PATHS)

format-check:
	$(UV) run black --check $(PROJECT_PATHS)
	$(UV) run isort --check-only $(PROJECT_PATHS)

lint:
	$(UV) run ruff check $(PROJECT_PATHS)
	$(UV) run mypy

test:
	$(UV) run pytest

test-unit:
	$(UV) run pytest tests/unit

test-integration:
	$(UV) run pytest tests/integration

compile:
	$(UV) run python -m compileall -q src tests scripts

build:
	$(UV) build

audit:
	$(UV) run pip-audit

governance:
	$(UV) run python -m scripts.check_required_docs
	$(UV) run python -m scripts.validate_features

compose-config:
	$(COMPOSE) config --quiet

lock-check:
	$(UV) lock --check

diff-check:
	git diff --check

check: format-check lint test compile build audit governance lock-check diff-check

# This is a local Docker Compose deployment, not a production deployment.
deploy:
	$(COMPOSE) up --build --detach

up:
	$(COMPOSE) up --build

down:
	$(COMPOSE) down --remove-orphans

logs:
	$(COMPOSE) logs --follow --tail=100

status:
	$(COMPOSE) ps

run:
	$(UV) run uvicorn sentiment_system.bootstrap.main:app --reload
