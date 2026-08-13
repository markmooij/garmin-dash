.PHONY: setup lint test clean lib-test lib-install-check compose-dev compose-prod build-push auth ingest-sync ingest-backfill ingest-schedule report

# Python 3.12 virtual environment (using uv)
VENV = .venv
UV = /home/mark/.local/bin/uv

# Docker
DOCKER = docker

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
	@echo "  compose-dev      Start dev containers (app + signal-api)"
	@echo "  compose-prod     Start prod containers (RPi profile)"
	@echo "  build-push       Build multi-arch images and push to GHCR"

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

# Docker
compose-dev:
	$(DOCKER) compose -f docker/docker-compose.dev.yml up -d

compose-prod:
	$(DOCKER) compose -f docker/docker-compose.prod.yml up -d

build-push:
	$(DOCKER) buildx build --push \
		--platform linux/amd64,linux/arm64 \
		--build-arg REGISTRY=$(REGISTRY) \
		--build-arg APP_NAME=$(APP_NAME) \
		-t $(REGISTRY)/$(APP_NAME):latest \
		-f docker/Dockerfile \
		.
