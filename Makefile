.PHONY: setup lint test clean lib-test lib-install-check docker-build-push compose-dev compose-prod auth ingest-sync ingest-backfill ingest-schedule report

# Python 3.12 virtual environment (using uv)
VENV = .venv
UV = /home/mark/.local/bin/uv

# Docker
DOCKER = docker

# Registry defaults (override on the command line)
REGISTRY ?= ghcr.io/yourname
APP_NAME ?= garmin-dash
TAG ?= latest

# Default target
.DEFAULT_GOAL := help

help:
	@echo "Garmin Dash — Development Commands"
	@echo ""
	@echo "  setup            Install Python dependencies (venv)"
	@echo "  lint             Run ruff + mypy"
	@echo "  test             Run pytest"
	@echo "  clean            Remove build artifacts"
	@echo ""
	@echo "  auth             Garmin auth: status | start | code <CODE>"
	@echo "  ingest-sync      Incremental sync (last 3 days)"
	@echo "  ingest-backfill  Backfill last N days (make ingest-backfill DAYS=90)"
	@echo "  ingest-schedule  Run the background sync scheduler"
	@echo "  report           CLI metrics report"
	@echo ""
	@echo "  compose-dev      Start dev containers (app + scheduler + signal-api profile)"
	@echo "  compose-prod     Start prod containers (RPi, see DEPLOY.md)"
	@echo "  docker-build-push Build multi-arch image and push to ghcr.io/yourname (no login needed)"

setup:
	$(UV) venv --clear $(VENV)
	$(UV) pip install -e ".[dev]"
	$(UV) pip install -e ./libs/signal_messenger
	@echo "✅ Dependencies installed"

lint:
	$(UV) run ruff check app libs tests
	$(UV) run mypy app libs tests --ignore-missing-imports

test:
	$(UV) run pytest tests -v --tb=short

lib-test:
	@echo "🧪 signal_messenger (standalone)"
	cd libs/signal_messenger && $(UV) run --with pytest pytest tests -v --tb=short

lib-install-check:
	@echo "📦 Standalone install check (scratch venv)"
	$(UV) venv /tmp/signal-messenger-venv --clear -q
	$(UV) pip install --python /tmp/signal-messenger-venv ./libs/signal_messenger
	/tmp/signal-messenger-venv/bin/python -c "from signal_messenger import SignalRestClient; print('✅ standalone import OK')"

clean:
	rm -rf $(VENV) build dist *.egg-info .pytest_cache
	rm -rf data/*.db* tests/fixtures/garmin
	@echo "✅ Cleaned"

# Garmin
auth:
	$(UV) run gdash auth $(ARGS)

ingest-sync:
	@echo "🔄 Incremental sync (last 3 days)"
	$(UV) run gdash ingest sync 3

ingest-backfill:
	@echo "📥 Backfill last $(DAYS) days"
	$(UV) run gdash ingest backfill $(DAYS)

ingest-schedule:
	@echo "📅 Running sync scheduler (CTRL+C to stop)"
	$(UV) run gdash ingest schedule

report:
	@echo "📊 Metrics Report"
	$(UV) run gdash report $(ARGS)

# Docker (see DEPLOY.md for the full Pi deployment walkthrough)
# Push access to ghcr.io/yourname is already managed — no login needed.
# Only set REGISTRY_USER/REGISTRY_TOKEN if that ever changes.
# Usage: make docker-build-push [TAG=v0.1.0]
docker-build-push:
	@cd docker && REGISTRY=$(REGISTRY) APP_NAME=$(APP_NAME) TAG=$(TAG) ./build-push.sh

compose-dev:
	$(DOCKER) compose -f docker/docker-compose.dev.yml up -d

compose-prod:
	$(DOCKER) compose -f docker/docker-compose.prod.yml up -d
