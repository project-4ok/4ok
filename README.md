# 4ok

A governed context layer for organizational AI.

This is not generic agent memory. It is controlled retrieval for a human using
an agent.

## Product Boundary

The system ingests company context, normalizes it, and retrieves governed
evidence for internal testing. PII masking, tokenization, and reveal are
deferred from the active runtime while the source-record retrieval path is
being simplified.

Core flow:

```text
source data -> raw store -> source records -> permission-filtered retrieval -> evidence -> audit
```

The first bounded workflow is customer context from email. The system should
summarize evidence and provide source refs. It should not make the business
decision for the human.

## Active Agent Tools

- `search_context(query)`
- local stdio MCP wrapper: `uv run gcb-mcp`

No reveal, `read_source`, `record_decision`, or canonical entity-resolution
tool in the active internal stage.

## Current Stack

- Python, uv, pytest, ruff
- SQLAlchemy Core
- PostgreSQL target, SQLite local fallback
- Presidio for deferred PII experiments
- Cerbos for deferred policy experiments
- Infisical for connector credentials
- Meltano/Singer-style connector experiments
- pypdf for text-layer-only PDF import
- Docling only in isolated/container experiments for now

## Docs

- [Plan](docs/plan.md)
- [Architecture](docs/architecture.md)
- [Implemented architecture flow](docs/architecture-flow.md)
- [Contracts](docs/contracts.md)
- [Operations](docs/operations.md)
- [Internal production v0](docs/internal-prod.md)
- [GCB MCP retrieval server](docs/mcp-retrieval.md)
- [K3s deployment readiness](docs/k3s-deployment-readiness.md)
- [Compliance](docs/compliance.md)
- [Development](docs/development.md)
- [Review log](docs/review.md)
- [Changelog](CHANGELOG.md)

## Experiment Docs

- [Honcho experiment runbook](docs/honcho-experiment.md)

Agent instructions live in [AGENTS.md](AGENTS.md).

## Local Commands

Install dependencies:

```bash
uv sync
```

Run tests:

```bash
uv run pytest
```

Run the reusable local development gate:

```bash
uv run gcb-dev fast
```

Run formatting/lint checks:

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

Search an existing governed state:

```bash
uv run gcb search-state "refund cancellation payment"
```

Run the local MCP retrieval server for stdio clients:

```bash
uv run gcb-mcp
```

Import live/internal Gmail Singer records into governed state:

```bash
uv run gcb ingest-gmail-singer .local/gmail-pilot/tap-gmail-output.jsonl
```

Run the local golden-query retrieval/evidence check:

```bash
uv run gcb eval-retrieval
```

Fixture-only deterministic regression path:

Search local email fixtures:

```bash
uv run gcb search "refund cancellation payment"
```

Import and query the context-substrate fixture:

```bash
uv run gcb import-context-fixture \
  --fixture fixtures/context_substrate/source_snapshot_eval.json \
  --state .local/context-substrate.sqlite

uv run gcb search-state \
  "renewal meeting Thursday" \
  --state .local/context-substrate.sqlite \
  --role linear:team:sales
```

Prepare a repeatable ignored seed snapshot for acceptance runs:

```bash
uv run gcb prepare-seed-snapshot \
  --input fixtures/context_substrate/source_snapshot_eval.json \
  --output .local/seeds/context-substrate.json
```

Run the local human-with-agent workflow harness:

```bash
uv run gcb ask "refund iban canceled account" --role finance
```

Check runtime health:

```bash
uv run gcb health
```

Inspect operator import/link/lifecycle/audit stats:

```bash
uv run gcb dashboard
```

Process pending source-change webhook events:

```bash
uv run gcb webhook-process --max-attempts 3 --retry-delay-seconds 60
```

Ingest a PDF that already has an extractable text layer:

```bash
uv run gcb ingest-pdf ./contract.pdf --landing-dir .local/raw/pdf
```

Inspect runtime boundaries:

```bash
uv run gcb runtime-services
```

Check Docker Compose host-port exposure:

```bash
uv run gcb access-smoke
```

Run Docker-backed local services:

```bash
export GCB_IMAGE_TAG="$(git rev-parse --short HEAD)"
export POSTGRES_PASSWORD="local-dev-password"
export GCB_DATABASE_URL="postgresql+psycopg://gcb:${POSTGRES_PASSWORD}@postgres:5432/gcb"
docker compose up -d postgres cerbos
```

Start the resident app container when validating Compose restart behavior:

```bash
uv run gcb-dev app-up
uv run gcb-dev pipeline-ps
```

`app-up` is the short wrapper for the longer `docker compose up --build
--force-recreate -d postgres cerbos app` form. It loads project `.env`, derives
`GCB_IMAGE_TAG`, and supplies stable local Compose defaults so shell variables do
not have to be repeated.

The `app` service runs `gcb runtime-monitor` and uses `gcb health` as its
Compose healthcheck. Use `docker compose run --rm app ...` for one-off
operator commands.

Run local observability:

```bash
uv run gcb-dev observability-up
uv run gcb observability-smoke
```

Start the local Dagster pipeline from current source:

```bash
uv run gcb-dev pipeline-up
uv run gcb operator-status --database-url "$GCB_DATABASE_URL" --config gcb.toml
```

`pipeline-up` derives `GCB_IMAGE_TAG` from the current commit, rebuilds tagged
Dagster images, and recreates the pipeline containers. `operator-status` prints
compact imported item counts, retrieval counts, latest connector job status, and
per-source live ingestion freshness for local checks.

Run the internal v0 acceptance proof:

```bash
uv run gcb acceptance-proof \
  --config .local/gcb.toml \
  --fixture .local/seeds/context-substrate.json \
  --backup-database-url postgresql://gcb:gcb_dev_password@localhost:5432/gcb \
  --backup-output .local/backups/acceptance-proof.dump
```

This deterministic regression proof covers fixture import with raw-store
writes, webhook enqueue/process with raw payload landing, dashboard stats,
search/evidence, audit, Compose access-boundary smoke, OTel smoke, and
backup/restore command wiring. It is not the live operator import path.

Run PostgreSQL integration tests:

```bash
GCB_TEST_DATABASE_URL=postgresql+psycopg://gcb:gcb_dev_password@localhost:5432/gcb \
  uv run pytest tests/integration/test_postgres.py
```

## Status

Prototype moving toward internal production v0. The real Gmail pilot has run;
the next priority is a PostgreSQL-backed internal runtime with scheduling,
backup/restore, and operator runbook.
