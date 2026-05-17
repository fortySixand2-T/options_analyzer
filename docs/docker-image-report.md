# Docker Image Reuse Report

## Current Setup

Two images, shared by all services:

| Image | Builder service | Used by |
|---|---|---|
| `options_analyzer:prod` | `app` | app, scan, backtest, collect, collect-intraday, backfill, shadow-monitor, orchestrator, agent-backtest |
| `options_analyzer:dev` | `test` | test, shell |

**Before this change:** Each of the 10 services had its own `build:` block, producing up to 10 separate images (~1.3 GB each). A `docker-compose build` would build the same Dockerfile target 8 times for prod services alone.

**After this change:** Only `app` and `test` trigger builds. All other services reference the named image. `start.sh` auto-builds on first run if the image doesn't exist.

## Scenarios Where Separate Images Would Be Needed

### 1. Different Python dependencies per service
**When:** A service needs packages not in `requirements.txt` (e.g., a monitoring service needing `prometheus-client`, or a service needing `celery`).
**Solution:** Add a new Dockerfile target (e.g., `FROM base AS monitoring`) and a third named image.
**Current status:** Not needed — all services use the same dependency set.

### 2. Different base OS or Python version
**When:** A service requires Python 3.12+ features or a different OS (e.g., Alpine for smaller image size on a lightweight collector).
**Solution:** Separate Dockerfile with its own `FROM`.
**Current status:** Not needed — all services run Python 3.11.

### 3. Services with conflicting system-level dependencies
**When:** Two services need different versions of a C library (e.g., one needs `libta-lib` for technical analysis, another needs a specific `numpy` compiled against a different BLAS).
**Solution:** Separate build targets.
**Current status:** Not needed.

### 4. Security isolation between untrusted inputs
**When:** A service processes untrusted external data (e.g., a webhook receiver) and should run with a minimal image surface to reduce attack vectors.
**Solution:** Distroless or scratch-based image for the exposed service, full image for internal services.
**Current status:** Not needed — all services are internal, no public endpoints.

### 5. Frontend-only deployment
**When:** The React frontend is deployed separately (e.g., to a CDN or nginx container) from the Python backend.
**Solution:** A third image built from the `frontend` stage with nginx.
**Current status:** Not needed — frontend is bundled into the prod image and served by FastAPI.

### 6. GPU/ML workloads
**When:** A service needs CUDA or ML frameworks (e.g., running a neural network for volatility prediction).
**Solution:** Separate image based on `nvidia/cuda` or `pytorch`.
**Current status:** Not needed — all computation is CPU-based (Black-Scholes, Monte Carlo).

## Recommendation

The two-image setup covers all current and near-term needs. Monitor for scenario #1 (different dependencies) as the most likely trigger for a third image. If a service only needs one extra pip package, prefer adding it to `requirements.txt` over creating a new image — the build time and disk cost of a separate image outweighs a small dependency.
