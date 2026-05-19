# ── Base ───────────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# System deps needed by numpy/scipy/matplotlib + curl for dolt install
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        libgomp1 \
        curl \
    && curl -L https://github.com/dolthub/dolt/releases/latest/download/install.sh | bash \
    && rm -rf /var/lib/apt/lists/*

# Install runtime deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Frontend build ────────────────────────────────────────────────────────────
FROM node:20-slim AS frontend

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# ── Production ─────────────────────────────────────────────────────────────────
FROM base AS prod

COPY src/       ./src/
COPY config/    ./config/
COPY scripts/   ./scripts/

# Copy React build output
COPY --from=frontend /frontend/dist ./frontend/dist

# Output directories + non-root user
RUN useradd -m -u 1000 appuser \
 && mkdir -p analysis_results mc_results exports data \
 && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "ui.app:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Development (includes tests + linting tools) ───────────────────────────────
FROM base AS dev

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY src/       ./src/
COPY config/    ./config/
COPY scripts/   ./scripts/
COPY tests/     ./tests/

RUN useradd -m -u 1000 appuser \
 && mkdir -p analysis_results mc_results exports data \
 && chown -R appuser:appuser /app

USER appuser

CMD ["python", "-m", "pytest", "tests/", "-v"]
