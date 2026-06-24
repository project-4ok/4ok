# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.13-bookworm

WORKDIR /app

ENV UV_LINK_MODE=copy
ENV UV_CACHE_DIR=/root/.cache/uv
ENV UV_HTTP_TIMEOUT=120
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-group dev --no-install-project

COPY src ./src
COPY scripts ./scripts
COPY fixtures ./fixtures

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-group dev \
    && uv pip install graphiti-core==0.29.1

ENTRYPOINT ["/app/.venv/bin/python", "scripts/run_graphiti_context_eval.py"]
