FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# OpenCV (via pipeline.py's cv2 import) needs these at runtime on a slim base image
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY pipeline.py app.py ./

# Cloud Run injects $PORT (default 8080) and expects the container to listen on it.
# Shell form (not exec-form array syntax) is required for the ${PORT:-8080} expansion.
CMD exec uv run uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}
