# syntax=docker/dockerfile:1
ARG UV_VERSION=0.13.1
FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv_bin

FROM python:3.11-slim

ARG UV_VERSION=0.13.1
# Note: UV_VERSION matches the uv version (0.13.1) that generated uv.lock.

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.11 \
    UV_PROJECT_ENVIRONMENT=/app/services/backend/.venv \
    PATH="/app/services/backend/.venv/bin:$PATH"

WORKDIR /app

# Copy uv binary from pinned official image
COPY --from=uv_bin /uv /uvx /bin/

# Copy contracts at /app/contracts so bus.py (_find_contracts_dir) locates them by traversing parents
COPY contracts/ /app/contracts/

# Copy backend service files preserving relative layout so store.py (parents[2]/migrations) resolves
COPY services/backend/pyproject.toml services/backend/uv.lock /app/services/backend/
COPY services/backend/migrations/ /app/services/backend/migrations/
COPY services/backend/src/ /app/services/backend/src/

WORKDIR /app/services/backend

# Synchronize dependencies frozen to lockfile, excluding dev group
RUN uv sync --frozen --no-dev

# Create non-root system user and configure permissions
RUN useradd -u 10001 -m -s /bin/bash appuser && \
    chown -R 10001:10001 /app

USER 10001

EXPOSE 8000

CMD ["/app/services/backend/.venv/bin/fridge-backend"]
