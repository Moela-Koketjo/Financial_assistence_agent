FROM python:3.11-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Default (30s) is tight on slow connections — package downloads time out
ENV UV_HTTP_TIMEOUT=180

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 8000

# Seed is idempotent — safe to run on every start
CMD ["sh", "-c", "uv run python -m db.seed && uv run uvicorn api.main:app --host 0.0.0.0 --port 8000"]
