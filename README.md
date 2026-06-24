# 4ok

Governed company context retrieval for AI agents.

4ok helps a human-with-agent workflow answer questions from company context with
source-backed, permission-filtered evidence. It is not generic agent memory and
it does not ask the agent to make the business decision. The job is narrower:
ingest operational sources, preserve traceable source records, retrieve only
what the current role may see, and leave an audit trail.

```text
source data -> raw store -> source records -> governed retrieval -> evidence -> audit
```

## Why 4ok exists

Teams are connecting agents to email, CRM, documents, issues, and chat. The hard
part is not another vector search demo; it is making retrieval safe enough for
real work:

- every answer points back to source records
- permissions and lifecycle state filter retrieval output before the agent sees it
- raw payloads are preserved for replay and operator inspection when available
- derived indexes can be rebuilt from source records
- audits show what was searched or surfaced

## One-command local onboarding

Start from a fresh machine with Docker installed:

```bash
curl -fsSL https://raw.githubusercontent.com/project-4ok/4ok/main/install.sh | bash
```

The installer clones or updates 4ok, installs `uv` if needed, runs `uv sync`,
validates Docker Compose, and starts the local runtime, observability, and
pipeline containers with safe local defaults.

It does not configure secrets, API keys, external secret manager, or live connectors. Add
credentials later when you are ready to connect real sources.

## Manual quick start

Prerequisites: Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/project-4ok/4ok.git
cd 4ok
uv sync
uv run four-ok-dev fast
```

That installs the project and runs the default local development gate: lint,
format check, tracked tests, goal audit, and whitespace checks.

Try a fixture-only retrieval path:

```bash
uv run four-ok search "refund cancellation payment"
```

Try the source-record flow with a deterministic context snapshot:

```bash
uv run four-ok import-context-fixture \
  --fixture fixtures/context_substrate/source_snapshot_eval.json \
  --state .local/context-substrate.sqlite

uv run four-ok search-state \
  "renewal meeting Thursday" \
  --state .local/context-substrate.sqlite \
  --role linear:team:sales
```

Run the local MCP retrieval server for stdio clients:

```bash
uv run four-ok-mcp
```

## What is implemented now

The current internal v0 is a source-record-first retrieval runtime:

- Singer-style connector experiments for Gmail, Google Drive, Linear, Twenty,
  Slack, fixtures, PDFs, and OpenClaw chat capture
- raw landing plus stable `SourceRecord` envelopes
- source-change import behavior for upsert, restore, restrict, delete,
  supersede, and duplicate operations
- derived retrieval units with source refs
- permission/lifecycle-filtered search and retrieval augmentation
- audit, dashboard, health, retention, backup/restore, and local runtime checks
- stdio MCP tool surface: `search_4ok(query, limit?)`

Deferred or intentionally out of scope for the active stage:

- generic long-term agent memory
- agent-made business decisions
- GDPR-complete reveal/tokenization workflows
- active `read_source`, `record_decision`, or entity-resolution tools

## Project map

```text
src/fourok/etl/extract/      source connectors, raw landing, fixture taps, PDF text import
src/fourok/etl/load/         source changes, source records, context objects, retrieval records
src/fourok/api/              API-first retrieval boundary used by all clients
src/fourok/clients/          thin client wrappers for CLI, MCP, and future adapters
src/fourok/storage/          config, ORM models, health, raw store, PostgreSQL utilities
src/fourok/retrieval/        search, evidence packs, retrieval evaluation
src/fourok/governance/       permissions, lifecycle, retention, audit behavior
src/fourok/runtime/          MCP server, operator runtime, observability, Dagster support
src/fourok/devtools/         repeatable local development and operator commands
fixtures/                 synthetic data for deterministic onboarding and tests
docs/                     architecture, operations, compliance, and internal-v0 runbooks
```

## Common commands

```bash
# default local gate for development
uv run four-ok-dev fast

# full release-style local gate
uv run four-ok-dev full

# run a narrow test target
uv run four-ok-dev test tests/retrieval -q

# inspect CLI surfaces
uv run four-ok --help
uv run four-ok-dev --help

# local golden-query retrieval/evidence evaluation
uv run four-ok eval-retrieval

# operator health and dashboard checks
uv run four-ok health
uv run four-ok dashboard

# Docker Compose config check with safe local placeholders
uv run four-ok-dev compose-config
```

## Onboarding path for contributors

1. Run `uv sync` and `uv run four-ok-dev fast`.
2. Read [Architecture](docs/architecture.md) for the source-record contract.
3. Read [Development](docs/development.md) for the local gates.
4. Pick a small vertical slice and prove it with a fixture, CLI command, or
   executable acceptance check.
5. Keep changes small: source records are truth; retrieval indexes are derived.

Agent contributors should also read [AGENTS.md](AGENTS.md). The project prefers
test-first, observable acceptance criteria, small diffs, and no broad refactors
mixed with behavior changes.

## Documentation

- [Architecture](docs/architecture.md)
- [Implemented architecture flow](docs/architecture-flow.md)
- [Development](docs/development.md)
- [Operations](docs/operations.md)
- [Internal production v0](docs/internal-prod.md)
- [4OK MCP retrieval server](docs/mcp-retrieval.md)
- [Contracts](docs/contracts.md)
- [Compliance](docs/compliance.md)
- [K3s deployment readiness](docs/k3s-deployment-readiness.md)
- [Review log](docs/review.md)
- [Changelog](CHANGELOG.md)

## Status

Prototype moving toward internal production v0. The live Gmail pilot has run;
the current focus is a PostgreSQL-backed runtime with repeatable local gates,
scheduling, observability, backup/restore, and operator-facing proof commands.
