.PHONY: setup lint test clean compose-dev compose-prod build-push setup-garmin auth ingest-backfill report

# Python 3.12 virtual environment (using uv)
VENV = .venv
UV = /home/mark/.local/bin/uv

# Docker
DOCKER = docker
COMPOSE_DEV = docker-compose.dev.yml
COMPOSE_PROD = docker-compose.prod.yml

# Default target
.DEFAULT_GOAL := help

help:
	@echo "Garmin Dash — Development Commands"
	@echo ""
	@echo "  setup          Install Python dependencies"
	@echo "  lint           Run ruff + mypy"
	@echo "  test           Run pytest"
	@echo "  clean          Remove build artifacts"
	@echo "  compose-dev    Start dev containers (app + signal-api)"
	@echo "  compose-prod   Start prod containers (RPi profile)"
	@echo "  build-push     Build multi-arch images and push to GHCR"
	@echo "  setup-garmin   Configure Garmin client (MFA + token cache)"
	@echo "  auth           Interactive MFA login, save token cache"
	@echo "  ingest-backfill  Backfill last 90 days to JSON fixtures"
	@echo "  report         CLI metrics report (--today)"

setup: $(VENV)
	$(PYTHON) -m pip install -e ".[dev]"
	@echo "✅ Dependencies installed"

$(VENV):
	$(UV) venv --clear $(VENV)
	$(UV) pip install -e ".[dev]"
	@echo "✅ Virtual environment created"

lint:
	$(UV) run ruff check app libs tests
	$(UV) run mypy app libs tests --ignore-missing-imports

test:
	$(UV) run pytest tests -v --tb=short

clean:
	rm -rf $(VENV) build dist *.egg-info .pytest_cache
	rm -rf data/*.db* tests/fixtures/*.json
	@echo "✅ Cleaned"

# Docker
compose-dev:
	$(DOCKER) compose -f $(COMPOSE_DEV) up -d

compose-prod:
	$(DOCKER) compose -f $(COMPOSE_PROD) up -d

build-push:
	$(DOCKER) buildx build --push \
		--platform linux/amd64,linux/arm64 \
		--build-arg REGISTRY=$(REGISTRY) \
		--build-arg APP_NAME=$(APP_NAME) \
		--build-arg SIGNAL_API_NAME=$(SIGNAL_API_NAME) \
		-t $(REGISTRY)/$(APP_NAME):latest \
		.

setup-garmin:
	@echo "🔐 Garmin Client Setup"
	@echo "This will configure garth for MFA login and create a token cache."
	$(PYTHON) -m app.auth.setup --config-dir data/garmin

auth:
	@echo "🔐 Garmin MFA Login"
	$(PYTHON) -m app.auth.cli --login

ingest-backfill:
	@echo "📥 Backfill last 90 days to JSON fixtures"
	$(PYTHON) -m app.ingestion.backfill

report:
	@echo "📊 Metrics Report"
	$(PYTHON) -m app.metrics.cli --today
