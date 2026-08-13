# Garmin Dash — Multi-stage, multi-arch Dockerfile
# Build: docker buildx build --platform linux/amd64,linux/arm64 -t garmin-dash:latest .

FROM python:3.12-slim-bookworm AS base

# Environment
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r garmin && useradd -r -g garmin garmin

# Set working directory
WORKDIR /app

# Copy requirements first for layer caching
COPY pyproject.toml .
COPY app/app.py .
COPY app/settings.py .
COPY app/cli.py .

# Install Python dependencies
RUN pip install --no-cache-dir \
    -e .

# Standalone Signal messenger library (Phase 4)
COPY libs/signal_messenger/ ./libs/signal_messenger/
RUN pip install --no-cache-dir ./libs/signal_messenger

# Copy application code
COPY app/ ./app/
COPY tests/ ./tests/

# Set ownership
RUN chown -R garmin:garmin /app

# Switch to non-root user
USER garmin

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')" || exit 1

# Expose port
EXPOSE 8000

# Run the application (PORT overridable via env)
CMD ["sh", "-c", "uvicorn app.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
