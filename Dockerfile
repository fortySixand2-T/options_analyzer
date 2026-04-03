# ── Base ───────────────────────────────────────────────────────────────────────
FROM python:3.9-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

# System deps needed by numpy/scipy/matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install runtime deps (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Production ─────────────────────────────────────────────────────────────────
FROM base AS prod

COPY src/       ./src/
COPY config/    ./config/
COPY examples/  ./examples/

# Output directories expected by CLI runners
RUN mkdir -p analysis_results/mc_demo mc_results exports

CMD ["python", "src/options_test_runner.py", "--help"]

# ── Development (includes tests + linting tools) ───────────────────────────────
FROM base AS dev

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY src/       ./src/
COPY config/    ./config/
COPY examples/  ./examples/
COPY tests/     ./tests/

RUN mkdir -p analysis_results/mc_demo mc_results exports

CMD ["python", "-m", "pytest", "tests/", "-v"]
