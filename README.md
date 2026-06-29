# fourok

Governed company context retrieval for AI agents.

fourok helps a human-with-agent workflow answer questions from company context with
source-backed, permission-filtered evidence. It is not generic agent memory and
it does not ask the agent to make the business decision. The job is narrower:
ingest operational sources, preserve traceable source records, retrieve only
what the current role may see, and leave an audit trail.

```text
source data -> raw store -> source records -> governed retrieval -> evidence -> audit
```

## Why fourok exists

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

The installer clones or updates fourok, installs `uv` if needed, runs `uv sync`,
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
uv run fourok-dev check
```

That installs the project and runs the default local development gate: lint,
format check, tests, compose rendering validation, and whitespace checks.

Try a fixture-only retrieval path:

```bash
uv run fourok search "refund cancellation payment"
```

Try the source-record flow with a deterministic context snapshot:

```bash
uv run fourok import-context-fixture \
  --fixture tests/fixtures/context_substrate/source_snapshot_eval.json \
  --state .local/context-substrate.sqlite

uv run fourok search-state \
  "renewal meeting Thursday" \
  --state .local/context-substrate.sqlite \
  --role linear:team:sales
```

Run the local MCP retrieval server for stdio clients:

```bash
uv run fourok-mcp
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
- audit, dashboard, health, retention, backup/restore, recurring ingestion,
  webhooks, and local runtime checks
- stdio and HTTP MCP retrieval surfaces: `search_fourok(query)` and
  `operator_status()`

Deferred or intentionally out of scope for the active stage:

- generic long-term agent memory
- agent-made business decisions
- GDPR-complete reveal/tokenization workflows
- active `read_source`, `record_decision`, or entity-resolution tools

## Project map

```text
src/fourok/cli.py             public CLI entrypoint
src/fourok/cli_parts/         CLI parsers and command handlers
src/fourok/etl/extract/       source connectors, raw landing, fixture taps, document import
src/fourok/etl/load/          source changes, source records, context objects, retrieval records
src/fourok/etl/transform/     PII, token, and entity-linking transforms
src/fourok/storage/           config, raw store, health, backups, schema contracts, ORM models
src/fourok/retrieval/         API boundary, search/ranking, evidence packs, retrieval evaluation
src/fourok/retrieval/api.py   API-first retrieval boundary used by CLI, MCP, and clients
src/fourok/retrieval/cli.py   domain-owned retrieve/search CLI adapter
src/fourok/retrieval/clients/ thin wrappers for CLI, MCP, and future adapters
src/fourok/governance/        permissions, lifecycle, retention, reveal policy, audit behavior
src/fourok/runtime/           MCP, operator status, dashboards, observability, Dagster/runtime checks
src/fourok/orchestration/     Dagster resource wiring
src/fourok/devtools/          local development gates, diagnostics, Grafana status, and goal audits
src/fourok/secrets/           environment/secret loading helpers
tests/fixtures/              synthetic data for deterministic onboarding and tests
deploy/                      Docker, Compose, Meltano, systemd, and runtime deployment artifacts
docs/                        architecture, operations, compliance, and internal-v0 runbooks
```

## CLI shape

```bash
fourok onboard
fourok status
fourok retrieve "What changed this week?"
```

The client-facing CLI stays small: `retrieve` for daily source-backed context,
`status` for a non-technical readiness check, and `onboard` for guided setup.
Operator and maintenance commands live under `fourok admin ...`; project-local
developer commands stay in `fourok-dev ...`.

See [CLI shape](docs/cli-shape.md) for the command boundary.

## Onboarding path for contributors

1. Run `uv sync` and `uv run fourok-dev check`.
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
- [fourok MCP retrieval server](docs/mcp-retrieval.md)
- [Contracts](docs/contracts.md)
- [Compliance](docs/compliance.md)
- [K3s deployment readiness](docs/k3s-deployment-readiness.md)
- [Review log](docs/review.md)

## Status

Internal v0 is source-record-first and PostgreSQL-backed. The current focus is
keeping the runtime proof loop small and useful: `retrieve`, MCP retrieval,
operator status, scheduling, observability, backup/restore, and deployment
readiness.
