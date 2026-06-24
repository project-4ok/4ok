# syntax=docker/dockerfile:1.7
FROM ghcr.io/astral-sh/uv:python3.13-bookworm AS dagster-deps

WORKDIR /app

ENV UV_LINK_MODE=copy
ENV UV_CACHE_DIR=/root/.cache/uv
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:${PATH}"

COPY pyproject.toml uv.lock README.md docker-compose.yml meltano.yml ./

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-group dev --group pipeline --no-install-project


FROM dagster-deps AS dagster-code

COPY src ./src
COPY fixtures ./fixtures
COPY deploy/dagster ./deploy/dagster

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-group dev --group pipeline

EXPOSE 4000

HEALTHCHECK --timeout=2s --start-period=5s --interval=5s --retries=20 \
  CMD ["dagster", "api", "grpc-health-check", "-p", "4000"]

CMD ["dagster", "code-server", "start", "-h", "0.0.0.0", "-p", "4000", "-f", "/app/deploy/dagster/definitions.py"]
