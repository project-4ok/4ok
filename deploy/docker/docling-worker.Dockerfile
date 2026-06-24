# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.13-bookworm

WORKDIR /app

ENV UV_LINK_MODE=copy
ENV UV_CACHE_DIR=/root/.cache/uv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock README.md ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-group dev --no-install-project

COPY src ./src
COPY scripts/evaluate_document_extraction.py ./scripts/evaluate_document_extraction.py

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-group dev \
    && uv pip install docling

ENTRYPOINT ["/app/.venv/bin/python", "scripts/evaluate_document_extraction.py"]
