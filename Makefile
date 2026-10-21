.PHONY: run dev dev-backend dev-backend-http dev-backend-https dev-frontend build test lint check migrate venv

# Address the dev servers bind to. Override with `make dev-backend BIND_HOST=0.0.0.0` to reach it from the LAN
# (the dashboard has a login, but see docs/security-review.md before exposing it).
BIND_HOST ?= 127.0.0.1

venv:
	cd backend && uv sync --extra dev

# One-command way to run the app from the repo root with uv. There is no
# root-level Python project (binding decision, see CLAUDE.md/docs/architecture.md)
# so this is a thin `cd` wrapper around the same `uv run banana` entrypoint
# make dev-backend-https/deploy/banana.service use - not a separate codepath.
# Serves the prebuilt frontend/dist too; run `make build` first if it's stale.
run:
	cd backend && uv run banana

# The dashboard is served over TLS 1.3 only with an elliptic-curve certificate and AES-256-GCM (see
# backend/app/tls.py). That policy is applied by `python -m app.main`; the uvicorn CLI cannot apply it, so the
# HTTPS dev target runs the production entrypoint and has no autoreload - restart it after backend changes.
# The self-signed certificate is generated under backend/certificates/ on first run.
dev-backend:
	cd backend && BANANA_HOST=$(BIND_HOST) uv run python -m app.main

# Plain HTTP with autoreload, an explicit opt-out of the TLS policy for local development.
dev-backend-http:
	cd backend && uv run uvicorn app.main:app --reload --host $(BIND_HOST) --port 8000

# Same codepath as dev-backend (and deploy/banana.service); kept as an alias.
dev-backend-https: dev-backend

dev-frontend: frontend/node_modules
	cd frontend && npm run dev

dev:
	@echo "Run 'make dev-backend' and 'make dev-frontend' in separate terminals."

build: frontend/node_modules
	cd frontend && npm run build

frontend/node_modules: frontend/package-lock.json
	cd frontend && npm ci

test: frontend/node_modules
	cd backend && uv run --extra dev pytest
	cd frontend && npm run test -- --run

lint: frontend/node_modules
	cd backend && uv run --extra dev ruff check . && uv run --extra dev mypy app
	cd frontend && npm run lint

check: lint test

migrate:
	cd backend && for db in app metrics credentials; do uv run alembic -c alembic_$$db.ini upgrade head; done
