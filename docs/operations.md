# Operations

Current local/prototype operations. Keep commands here current.

For the internal production v0 runbook, see
[internal-prod.md](internal-prod.md).

## Runtime Checks

```bash
uv run fourok health
uv run fourok dashboard
uv run python scripts/smoke_runtime.py
```

Host-side `fourok health` and `fourok operator-status` default to the intended local
Compose runtime database when `--state` and `--database-url` are omitted. The
commands resolve the same runtime configuration used by the app container, then
map the internal `postgres` hostname to `127.0.0.1` for host access. They do not
print the database URL or password.

Resolution order for these host-side operator checks:

1. `--database-url`, when provided.
2. Explicit `--state`, which keeps the command on SQLite and ignores ambient
   runtime database variables.
3. The running Compose `app` container's `FOUROK_DATABASE_URL`.
4. `.env` `FOUROK_DATABASE_URL`, then `.env` `POSTGRES_PASSWORD` composed into the
   local Postgres URL.
5. Compose runtime defaults.
6. Ambient shell `FOUROK_DATABASE_URL`.

If a stale exported `FOUROK_DATABASE_URL` or stale `.env` password disagrees with a
running app container, trust the running container first and refresh the stale
host setting after the smoke check passes.

Use this redacted check before debugging local operator DB drift:

```bash
uv run fourok-dev compose-env
uv run fourok health
uv run fourok operator-status
```

Use `--state` only when you intentionally want to inspect a SQLite state file:

```bash
uv run fourok health --state .local/context.sqlite
uv run fourok operator-status --state .local/context.sqlite
```

Use `--database-url` for an intentional override. Prefer setting it in the
environment and avoid pasting database URLs into logs or reports.

## Agent Diagnostics

Hermes/Codex agents should start local runtime triage with:

```bash
uv run fourok-dev agent-diagnostics --json
```

The command prints sanitized JSON with:

- `status`: `ok`, `warning`, or `failed`
- `recent_errors`: error-marker counts and file/line locations for project logs
  modified in the last hour; log message bodies are not printed
- `checks`: status for recent errors, Docker pipeline services, Dagster
  webserver reachability, database health, raw-store path, and search probe
- `next_commands`: stable follow-up commands for the failing or skipped surface

Use `--since-seconds` to widen the recent-error window. Use `--state`,
`--database-url`, and `--raw-store` to point the checks at a specific local
runtime. When database or raw-store paths are absent, the command reports those
surfaces as `skipped` rather than creating project state.

Search an existing governed runtime database without loading local fixtures:

```bash
uv run fourok search-state "refund cancellation" --database-url "$FOUROK_DATABASE_URL"
```

Inspect operator stats for an existing governed runtime database:

```bash
uv run fourok dashboard --database-url "$FOUROK_DATABASE_URL" --config fourok.toml
```

Connector job stats include `recent_failure_count` for retryable failures and
`recent_invalid_count` for malformed or unsupported source payloads.
The dashboard also includes an `alerts` section. Internal v0 alerts are
operator-visible signals, not a paging system: failed/invalid connector jobs,
pending/failed/invalid webhook events, and other state-bound issues are listed
with stable alert codes, counts, thresholds, and next-step commands. Treat any
alert item as work for the operator queue: inspect the named command first,
then retry, quarantine, or correct the source payload according to the alert
guidance.
When `--config` is provided, dashboard retry visibility uses `[scheduler]`
`retry_delay_seconds` and `max_attempts`. The dashboard also reports
`raw_sources`: the configured raw-store path, raw object count, source-record
raw refs, and unreferenced raw object count. It does not print raw payload
bodies.

## Scheduled Imports

Default operator path: live/internal connector imports.

For local recurring live ingestion, run the hourly-safe backfill command from a
host scheduler or manually while testing:

```bash
uv run fourok run-live-ingestion \
  --database-url "$FOUROK_DATABASE_URL" \
  --config fourok.toml
```

The command runs the current Dagster live connector path for Twenty, Slack,
Linear, and Google Drive, records one connector job per source, and prints only
source names, job IDs, status, artifact paths, and counts. It does not print raw
payloads or credentials. Use `--source slack`, `--source twenty`,
`--source linear`, or `--source google_drive` to isolate one connector while
debugging. Add `--verify-live-db` when the target runtime database should show
live source/retrieval row deltas during the proof.

Check freshness and idempotency status for every recurring live source:

```bash
uv run fourok live-ingestion-status \
  --database-url "$FOUROK_DATABASE_URL" \
  --config fourok.toml
```

`freshness_status` is `fresh`, `stale`, `missing`, `failed`, or `invalid`.
`idempotency_status` is recorded from the latest succeeded source run. The
default stale window is `[scheduler].import_interval_minutes`, which is 60
minutes unless configured otherwise.

Local Dagster also exposes:

- `fourok_hourly_live_backfill`: hourly asset job for the four live connector
  backfills.
- `fourok_hourly_live_backfill_schedule`: `0 * * * *` reconciliation schedule.
- `fourok_webhook_backlog_sensor`: polling event bridge for pending durable
  webhook events.
- `fourok_process_webhook_backlog`: asset job that processes queued webhook
  events and refreshes derived/searchable rows.

Use host cron or systemd timers to call one scheduler-safe import command
against the approved internal connector output:

```bash
uv run fourok run-imports \
  --connector gmail-singer \
  --singer-file .local/gmail-pilot/tap-gmail-output.jsonl \
  --database-url "$FOUROK_DATABASE_URL"
```

Retry a failed connector job after its backoff window is due:

```bash
uv run fourok run-imports \
  --connector gmail-singer \
  --singer-file .local/gmail-pilot/tap-gmail-output.jsonl \
  --database-url "$FOUROK_DATABASE_URL" \
  --retry-failed \
  --retry-base-delay-seconds 300
```

The command records connector job state, persists a compact output checkpoint,
uses a database-backed per-connector running-job guard, and prints sanitized
JSON for dashboards and scheduler logs. Gmail Singer imports record connector
job state and checkpoint output so repeated scheduled imports can be inspected
through `connector-jobs`, `connector-checkpoint`, and `dashboard`.

Pass `--config fourok.toml` to `run-imports`, `import-context-fixture`,
`ingest-gmail-singer`, or `ingest-pdf` to apply configured retrieval-unit chunk
settings and `[raw_store]` during import. For retry runs, omitted
`run-imports --retry-failed` retry flags use `[scheduler]` values:
`retry_delay_seconds` and `max_attempts`. Explicit CLI flags override config
values where a flag exists. If `[connectors].enabled` is non-empty,
`run-imports` only runs connectors in that list. `[connectors].source_limit`
caps loaded records before they enter the import pipeline.

Fixture-only deterministic regression path:

```bash
uv run fourok run-imports \
  --connector context-fixture \
  --fixture tests/fixtures/context_substrate/source_snapshot_eval.json \
  --database-url "$FOUROK_DATABASE_URL"
```

Use this only for narrow local regression checks where deterministic fixture
records are the behavior under test.

Malformed or unsupported connector payloads are recorded as `invalid` connector
jobs with the source file path in `raw_output_ref` and a visible error. They are
not retried by `--retry-failed`; fix or skip the source payload before running
the connector again.

## OpenClaw Capture

The first OpenClaw integration boundary is local and explicit:

- adapt captured OpenClaw turns with `openclaw_messages_to_source_records`
- or call `capture_openclaw_messages` to adapt and ingest in one step
- keep retrieval follow-up through normal fourok commands and existing agent
  workflows, not plugin-level explicit search tools
- do not expose reveal in this stage

The product path is: user message -> fourok capture -> indexed retrieval. Keep
retrieval results available for follow-up through normal review commands and
workflow UX. Do not add an OpenClaw plugin RAG hook or explicit OpenClaw search
tool until the default `fourok retrieve` output is strong enough to use manually.

CLI checks are operator/dev smoke equivalents only, for example:

```bash
uv run fourok search-state "refund cancellation" --state .local/context.sqlite
uv run fourok health --state .local/context.sqlite --raw-store .local/raw
```

When chat capture is wired into an OpenClaw runtime, call the adapter after
agent turns and before compaction/reset, matching the hook timing documented in
`docs/contracts.md`.

## Webhook Backlog

Land a source-change webhook event into the durable database-backed backlog:

```bash
uv run fourok webhook-enqueue .local/webhooks/linear-issue-updated.json \
  --state .local/context.sqlite \
  --raw-store .local/raw/webhooks
```

Process pending webhook events through the same source-change applier used by
connector imports:

```bash
uv run fourok webhook-process \
  --state .local/context.sqlite \
  --raw-store .local/raw/webhooks \
  --config fourok.toml \
  --max-attempts 3 \
  --retry-delay-seconds 60
```

When `--config` is provided, omitted processing flags use `[webhooks]`
defaults: `process_limit`, `max_attempts`, and `retry_delay_seconds`. Explicit
CLI flags override the config values.

Inspect backlog status:

```bash
uv run fourok webhook-events --state .local/context.sqlite
uv run fourok webhook-events --state .local/context.sqlite --status invalid
uv run fourok webhook-events --state .local/context.sqlite --status failed
```

`invalid` events are permanently malformed or unsupported source payloads and
should be reviewed manually. `failed` events exhausted retry attempts after
transient processing errors.

## Text-Layer PDF Import

Ingest a PDF only when it already has extractable text. This path uses `pypdf`
for text-layer extraction and does not run OCR, image understanding, layout
reconstruction, or table extraction.

```bash
uv run fourok ingest-pdf ./contract.pdf \
  --state .local/context.sqlite \
  --landing-dir .local/raw/pdf
```

The command lands the raw PDF bytes by checksum, creates a `Document`
`SourceRecord`, and imports it through the same governed source-record pipeline
as connectors and webhooks.

Docker-backed local services:

```bash
export FOUROK_IMAGE_TAG="$(git rev-parse --short HEAD)"
export POSTGRES_PASSWORD="local-dev-password"
export FOUROK_DATABASE_URL="postgresql+psycopg://fourok:${POSTGRES_PASSWORD}@postgres:5432/fourok"
docker compose up -d postgres
```

For rebuild/restart checks, start the resident app service too:

```bash
uv run fourok-dev app-up
uv run fourok-dev pipeline-ps
```

`app-up` wraps the long direct Compose form (`docker compose up --build
--force-recreate -d postgres app`) and injects the same project `.env`,
`FOUROK_IMAGE_TAG`, `POSTGRES_PASSWORD`, `DAGSTER_POSTGRES_PASSWORD`, and
`FOUROK_DATABASE_URL` defaults used by the other `fourok-dev` Docker helpers.

## Dagster Pipeline

Dagster runs under the Docker Compose `pipeline` profile. It is an internal
operator surface, not a public service.

Start the pipeline services through the local dev wrapper. It loads project
`.env`, maps external secret manager aliases for the Dagster code container, and supplies
stable local-only Compose defaults so direct `docker compose` interpolation does
not fail when password variables are absent from the shell. It derives
`FOUROK_IMAGE_TAG` from the current Git commit, rebuilds tagged Dagster images, and
recreates the pipeline containers so Dagster loads current source rather than a
stale local image:

```bash
uv run fourok-dev pipeline-up
```

Equivalent direct Compose form when debugging the wrapper:

```bash
export FOUROK_IMAGE_TAG="$(git rev-parse --short HEAD)"
export POSTGRES_PASSWORD="local-check"
export DAGSTER_POSTGRES_PASSWORD="local-check"
export FOUROK_DATABASE_URL="postgresql+psycopg://fourok:${POSTGRES_PASSWORD}@postgres:5432/fourok"

docker compose up -d \
  --build \
  --force-recreate \
  postgres \
  dagster-postgres \
  dagster-code \
  dagster-webserver \
  dagster-daemon
```

Operator access:

- Dagster UI: `http://127.0.0.1:3001`
- Dagster webserver: loopback-bound only
- Dagster code server and daemon: internal Compose network only
- Dagster metadata database: `dagster-postgres` volume only
- fourok runtime database: `postgres` service, loopback-bound on `127.0.0.1:5432`

Check service health:

```bash
uv run fourok-dev pipeline-ps
uv run python - <<'PY'
import urllib.request
print(urllib.request.urlopen("http://127.0.0.1:3001/server_info", timeout=5).read().decode())
PY
```

Confirm the operator-visible runtime counts:

```bash
uv run fourok health
uv run fourok operator-status
```

From the host, the no-arg operator commands use the runtime database URL from
the running Compose `app` container when available, then fall back through
`.env`, Compose defaults, and ambient shell `FOUROK_DATABASE_URL`; the container
hostname is rewritten to `127.0.0.1`. Keep `--database-url` for deliberate
overrides and `--state` for intentional SQLite checks.

The compact JSON reports:

- `imported_items_by_source`
- `retrieval_records.total` and `retrieval_records.by_status`
- latest connector job status, timestamps, and raw output ref
- latest connector checkpoint and finished timestamps
- `freshness.live_ingestion.sources`, with per-source fresh, stale, missing, or
  failed status

Confirm the Dagster repository loaded the current definitions:

```bash
curl -s http://127.0.0.1:3001/graphql \
  -H 'content-type: application/json' \
  --data '{"query":"{ repositoriesOrError { ... on RepositoryConnection { nodes { name schedules { name } sensors { name } pipelines { name } } } } }"}' \
  | python -m json.tool
```

The response should include `fourok_hourly_live_backfill_schedule`,
`fourok_webhook_backlog_sensor`, and the `__ASSET_JOB` pipeline. If schedules or
sensors are missing, restart with `uv run fourok-dev pipeline-up` before debugging
Dagster code.

Dagster pipeline services default `FOUROK_OBSERVABILITY_ENABLED=true` and export
OTLP to `http://observability:4318` with service names
`fourok-dagster-code`, `fourok-dagster-webserver`, and `fourok-dagster-daemon`. Start the
observability profile before running live proofs when Grafana traces/logs are
part of the check:

```bash
docker compose --profile observability up -d observability
```

Inspect the asset graph without starting Docker:

```bash
uv run --group pipeline python scripts/check_dagster_pipeline.py
```

Run the internal live ingestion operator command:

```bash
uv run fourok-dev operator-live
```

Use the dry-run first when checking local wiring or credentials:

```bash
uv run fourok-dev operator-live --dry-run
```

The command loads project `.env`, passes external secret manager settings through to the
Dagster live assets, starts and checks the local Dagster Compose services, runs
the live Slack, Twenty, Linear, and Google Drive landing/import assets, and
prints JSON with the raw landing path, redacted fourok database URL, source-record
counts by source system, retrieval count, and Dagster status. Output must not
contain secret values. Live materialization requires configured source
credentials or external secret manager settings; without them, use the dry-run and connector
contract checks below.

The lower-level live Dagster proof remains available when debugging asset
selection directly. Materialize live connector assets through Dagster with
env/.env-backed credentials:

```bash
uv run --group pipeline python scripts/check_dagster_pipeline.py \
  --materialize-live-connectors
```

This is the operator/default Dagster direction: live connector raw landing and
source-record assets run with runtime credentials, while metadata stays
sanitized.

Materialize deterministic fixture assets through Dagster for regression only:

```bash
uv run --group pipeline python scripts/check_dagster_pipeline.py \
  --materialize \
  --verify-retrieval \
  --verify-webhook
```

This proves the repository definitions expose the raw extraction,
source-record import, canonical-object/entity-link, and retrieval-record
assets plus webhook backlog, operator dashboard, golden retrieval eval, and
audit metadata assets. The fixture-backed materialization proves only the
deterministic regression path: local fixture taps can reach fourok through the
Dagster materialization path, the resulting fourok state has retrieval units,
search results, evidence items, and search/source-access audit events, and a
seeded webhook event is processed through the durable backlog into searchable
source material.

The raw Singer landing target preserves the latest Singer `STATE` message as
`state.json` inside each landing directory when a tap emits state. Dagster raw
landing materializations expose the checkpoint file path and top-level
checkpoint keys as metadata. Full connector job checkpoint history remains in
the fourok connector state tables for scheduler-safe imports.

Check the configured Singer tap contract for deterministic adapter regression
coverage:

```bash
uv run python scripts/check_connector_contracts.py
```

The proof lands the configured Gmail, Slack, Twenty, Linear, and Google Drive
fixture tap output, verifies required streams, Singer state checkpoints,
SourceRecord adaptation, source systems, record types, and adapter failure
behavior. This is a fixture-backed tap-boundary regression proof only; live
SaaS auth and incremental semantics are covered by the live connector proofs
below before production credentials are wired.

Check the live Slack tap contract with env/.env-backed credentials:

```bash
uv run --group pipeline python scripts/check_slack_live_contract.py
```

This runs `tap-slack` config validation, discovery, and SDK test-record mode,
lands the Singer output into `.local/test-artifacts/slack-live-contract`, and
adapts the landed `channels`, `users`, `messages`, or `threads` streams into
Slack `SourceRecord`s. Landed `channel_members` data is intentionally ignored
because channel-membership records were noisy and not useful as canonical
relationship objects. Output reports counts, stream names, record types, and
artifact paths only; it must not print Slack message text or credential values.

Slack live extraction always requests every readable conversation type:
`["public_channel","private_channel","mpim","im"]`. `TAP_SLACK_SELECTED_CHANNELS`
and `TAP_SLACK_CHANNEL_TYPES` operator overrides are intentionally ignored so
the import cannot be narrowed to a hand-picked channel subset. Public-channel
history is included for public channels the Slack app is already invited into;
channels the app has not joined remain outside the bot token's readable scope.

Check the live Twenty connector contract with env/.env-backed credentials:

```bash
uv run --group pipeline python scripts/check_twenty_live_contract.py
```

There is no suitable `tap-twenty` extractor in Meltano Hub, so internal v0 uses
the narrow repository-owned `tap-fourok-twenty` Singer-compatible extractor for
Twenty companies and people. The proof runs the extractor through Meltano,
lands raw JSONL, verifies state, and adapts landed records into fourok
`SourceRecord`s. Output reports counts and stream names only; it must not print
CRM field values or credential values.

Check the live Linear connector contract with env/.env-backed credentials:

```bash
uv run --group pipeline python scripts/check_linear_live_contract.py
```

Meltano Hub has a public `tap-linear`, but it requires a separate Python 3.12
runtime. Internal v0 therefore uses the narrow repository-owned
`tap-fourok-linear` Singer-compatible extractor for Linear users, issues, and
comments so it runs inside the project Python 3.13 app image. The proof runs
the extractor through Meltano, lands raw JSONL, verifies state, and adapts
landed records into fourok `SourceRecord`s. Output reports counts and stream names
only; it must not print Linear field values or credential values.

Check the live Google Drive connector contract with env/.env-backed OAuth
credentials:

```bash
uv run --group pipeline python scripts/check_google_drive_live_contract.py
```

Internal v0 uses the narrow repository-owned `tap-fourok-google-drive`
Singer-compatible extractor for Drive files that already have retrievable text.
It lists Drive files, exports Google Docs as `text/plain`, downloads plain text
files, lands raw JSONL, verifies state, and adapts landed records into fourok
`SourceRecord`s. OCR, binary PDFs, images, and layout reconstruction remain
outside this connector proof. Output reports counts and stream names only; it
must not print document text or credential values.

Dagster's own CLI is the operator/agent control surface for this stage:

```bash
uv run --group pipeline dagster definitions validate -f deploy/dagster/definitions.py
uv run --group pipeline dagster asset list -f deploy/dagster/definitions.py
uv run --group pipeline dagster asset materialize \
  -f deploy/dagster/definitions.py \
  --select meltano_slack_raw_landing,fourok_slack_source_records_from_raw_landing
```

Use the UI to view the asset graph, inspect materialization metadata, read run
logs, rerun failed assets, and trigger manual materializations. Use
`docker compose logs dagster-code dagster-webserver
dagster-daemon` when the UI cannot load a code location.

## Source-Record Fixture Regression

Import the current Linear/Twenty/Slack context-substrate fixture into local
state for deterministic regression checks only:

```bash
uv run fourok import-context-fixture \
  --fixture tests/fixtures/context_substrate/source_snapshot_eval.json \
  --state .local/context-substrate.sqlite
```

Query that imported state:

```bash
uv run fourok search-state \
  "renewal meeting Thursday" \
  --state .local/context-substrate.sqlite \
  --role linear:team:sales
```

Prepare a repeatable ignored seed snapshot for local or Docker Compose
acceptance checks:

```bash
uv run fourok prepare-seed-snapshot \
  --input tests/fixtures/context_substrate/source_snapshot_eval.json \
  --output .local/seeds/context-substrate.json
```

The retrieval output includes:

- `results`
- `result_candidates`
- `evidence_items`
- `primary_objects`
- `related_objects`
- `related_object_groups`
- `entities`
- `unresolved_candidates`
- `limitations`
- `audit_ref`

## Retrieval Evaluation

Run the local golden-query check against the active governed context retrieval
path:

```bash
uv run fourok eval-retrieval
```

By default this imports the fixture records into an in-memory governed context
store, runs `search_context`, and verifies expected source refs, evidence pack
assembly, search audit refs, and source-access audit events for returned
evidence. Cases may also define `unacceptable_source_refs`; those fail the
evaluation when lifecycle filtering, permissions, or ranking surface a known
bad candidate. It uses:

- `tests/fixtures/context_substrate/source_snapshot_eval.json`
- `tests/fixtures/context_substrate/evidence_baseline_cases.json`

To evaluate a bounded live source snapshot instead, use env/.env-backed
credentials and pass `--live-sources`:

```bash
uv run fourok eval-retrieval \
  --live-sources \
  --sources linear,twenty,slack
```

Run the same fixture regression import against the Docker Compose PostgreSQL
service:

```bash
export FOUROK_IMAGE_TAG="$(git rev-parse --short HEAD)"
export POSTGRES_PASSWORD="local-dev-password"
export FOUROK_DATABASE_URL="postgresql+psycopg://fourok:${POSTGRES_PASSWORD}@postgres:5432/fourok"
docker compose up -d postgres

docker compose build app

docker compose run --rm app \
  import-context-fixture \
  --fixture /app/tests/fixtures/context_substrate/source_snapshot_eval.json
```

The active Compose services use named volumes for internal runtime state:
`postgres-data`, `observability-data`, `fourok-local`, and `fourok-data`.

Query the Docker Compose PostgreSQL state:

```bash
docker compose run --rm app \
  search-state \
  "renewal meeting Thursday" \
  --role linear:team:sales
```

Check that Docker Compose only exposes the intended loopback-bound internal
ports:

```bash
docker compose run --rm app access-smoke --compose-file /app/docker-compose.yml
```

Prepare the same seed inside the Docker Compose app volume:

```bash
docker compose run --rm app \
  prepare-seed-snapshot \
    --input /app/tests/fixtures/context_substrate/source_snapshot_eval.json \
    --output /app/.local/seeds/context-substrate.json
```

Run the internal v0 acceptance proof against the Docker Compose app image:

```bash
docker compose run --rm app \
  acceptance-proof \
    --config /etc/fourok/fourok.toml \
    --fixture /app/.local/seeds/context-substrate.json \
    --query "Robin Scharf" \
    --backup-database-url "$FOUROK_DATABASE_URL" \
    --backup-output /app/.local/backups/acceptance-proof.dump \
    --observability-endpoint http://observability:4318
```

Run this proof against a fresh/reset acceptance database. Reusing a database
that already contains `acceptance-webhook-1` can make the webhook idempotency
check correctly claim zero new events and fail the proof.

The proof checks config loading, health, fixture import with raw-store writes,
webhook enqueue/process/backlog visibility with raw payload landing, retention
visibility, retrieval-unit rebuild, dashboard stats, search/evidence-pack
shape, audit records, source lifecycle restrict/restore/delete propagation,
safe OTel smoke export, and PostgreSQL backup and restore command wiring
without printing raw source bodies or credentials. It also runs the Compose
access-boundary smoke check so broad host-port exposure is visible. In short,
it proves backup and restore command wiring without executing a destructive
restore.
The proof report includes top-level `alerts` for operator-visible failures and
also summarizes dashboard alert status/count so backlog/import issues, failed
OTel smoke export, and failed backup or restore-drill command wiring are visible
from one command. Top-level proof alerts include the trigger threshold and a
next-step command for the operator.

Recorded Docker Compose proof on 2026-06-07 used app image
`fourok-app:772cba5` and ran:

```bash
docker compose run --rm app \
  prepare-seed-snapshot \
    --input /app/tests/fixtures/context_substrate/source_snapshot_eval.json \
    --output /app/.local/seeds/context-substrate.json

docker compose run --rm app \
  acceptance-proof \
    --config /etc/fourok/fourok.toml \
    --fixture /app/.local/seeds/context-substrate.json \
    --query "Robin Scharf" \
    --backup-database-url "$FOUROK_DATABASE_URL" \
    --backup-output /app/.local/backups/acceptance-proof.dump \
    --observability-endpoint http://observability:4318
```

The acceptance report returned top-level `status: ok`. All checks were `ok`:
`access`, `audit`, `backup_command`, `config`, `dashboard`, `health`,
`import`, `lifecycle`, `observability`, `rebuild`, `restore_command`,
`retention`, `search`, and `webhook`.

Limitations:

- This fixture import is a deterministic local substrate check, not a live
  connector sync.
- Related object expansion currently uses source-backed entity links,
  same-thread records, and same-project records. Broader relationship
  expansion is still future work.
- Entity candidate output currently covers deterministic ambiguous first-name
  matches across visible person objects. Broader entity resolution is still
  future work.
- Source-record imports prepare derived `retrieval_records` for all record
  types. Keyword search and vector indexing read those retrieval units and join
  back to `source_records` for metadata, permissions, lifecycle state, and
  evidence. The active source-change path no longer populates legacy
  `email_chunks`.
- The acceptance proof intentionally exercises idempotency-sensitive records.
  Use a fresh acceptance database or a controlled reset path for repeated proof
  runs.

## Local Observability

Start the local OpenTelemetry backend:

```bash
export FOUROK_IMAGE_TAG="$(git rev-parse --short HEAD)"
export POSTGRES_PASSWORD="local-dev-password"
export FOUROK_DATABASE_URL="postgresql+psycopg://fourok:${POSTGRES_PASSWORD}@postgres:5432/fourok"

docker compose --profile observability up -d observability
```

Grafana is available at `http://localhost:3000` with `admin` / `admin`.
The local OTLP HTTP endpoint is `http://localhost:4318`.

Emit a safe smoke trace and log without application payloads:

```bash
uv run fourok observability-smoke
```

Trace CLI runs into the local backend:

```bash
FOUROK_OBSERVABILITY_ENABLED=true \
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 \
OTEL_SERVICE_NAME=fourok-local \
  uv run fourok health
```

Implemented runtime spans use safe operational attributes only:

- `fourok.run_imports` for scheduled connector imports
- `fourok.source_records.ingest` for SourceRecord import/adaptation boundaries
- `fourok.retrieval.prepare` for retrieval-unit preparation
- `fourok.search_context` for search and evidence-pack assembly
- `fourok.dashboard` for operator dashboard checks
- `fourok.openclaw.capture` for OpenClaw chat capture

`fourok.run_imports` includes:

- `fourok.connector.name`
- `fourok.connector.attempt`
- `fourok.import.status`
- `fourok.import.record_count`
- `fourok.import.deleted_record_count`
- `fourok.import.restricted_count`

Other spans use the same pattern: counts, limits, statuses, and booleans. They
must not include raw queries, raw source text, chat message content, credentials,
or connector payloads.

Trace the Docker `app` service when the observability profile is running:

```bash
FOUROK_OBSERVABILITY_ENABLED=true \
docker compose run --rm app \
  observability-smoke \
    --endpoint http://observability:4318 \
    --service-name fourok-compose-smoke
```

Expected smoke output includes `status: ok`, `exporter: otlp-http`, and
`sensitive_payload_exported: false`.

Recorded local proof on 2026-06-07 used app image
`fourok-app:b75b3b9` and ran:

```bash
FOUROK_IMAGE_TAG=b75b3b9 \
POSTGRES_PASSWORD=local-check \
FOUROK_DATABASE_URL=postgresql+psycopg://fourok:local-check@postgres:5432/fourok \
  docker compose run --rm app \
    observability-smoke \
      --endpoint http://observability:4318 \
      --service-name fourok-compose-smoke
```

The command returned `status: ok`, `exporter: otlp-http`, and
`sensitive_payload_exported: false`.

Commands that accept `--config` use `[telemetry]` when `enabled = true`;
otherwise they fall back to `FOUROK_OBSERVABILITY_ENABLED`,
`OTEL_EXPORTER_OTLP_ENDPOINT`, and `OTEL_SERVICE_NAME`.

Limitations:

- This stack is for local development and debugging, not production monitoring.
- Do not put secrets, raw source text, customer data, or connector payloads in
  span attributes or log messages.
- Use domain-safe attributes such as source type, status, counts, durations,
  job ids, and policy decision metadata.

## PostgreSQL

Production direction is PostgreSQL. SQLite remains a fast local fallback.

Backup:

```bash
uv run fourok postgres-backup \
  --database-url "$FOUROK_DATABASE_URL" \
  --output .local/backups/fourok.dump
```

Internal v0 includes a nightly systemd template:

```bash
sudo install -d -m 0750 /etc/fourok
sudo install -m 0640 deploy/systemd/fourok.env.example /etc/fourok/fourok.env
sudo editor /etc/fourok/fourok.env
sudo systemctl enable --now fourok-postgres-backup.timer
```

The timer runs the Docker Compose app image and writes timestamped dumps under
`/var/lib/fourok/backups`. Systemd services read database and external secret manager settings
from `/etc/fourok/fourok.env`; do not put real passwords into committed unit files.
Backup retention, encryption, and off-host copy policy remain operator
decisions for this internal stage.

Restore drill:

```bash
uv run fourok postgres-restore-drill \
  --database-url "$FOUROK_DATABASE_URL" \
  --restore-database-url "$FOUROK_RESTORE_DATABASE_URL" \
  --backup-output .local/backups/fourok.dump
```

The restore drill refuses to run when the restore database URL points at the
source database. It backs up the source, restores into the separate drill
database, and then verifies the restored schema health without printing
passwords in command arguments.

Recorded local evidence:

- Date: 2026-06-07
- App image tag: `9ae4026`
- Command: `docker compose run --rm app postgres-restore-drill ...`
- Result: `status=completed`, restored database health `status=ok`,
  `source_record_count=20`

## Raw Source Retention

Configure:

```toml
[retention]
raw_source_days = 90
audit_event_days = 365
backup_days = 14
webhook_backlog_days = 14

[raw_store]
backend = "filesystem"
path = ".local/raw"

[backup]
path = ".local/backups"

[retrieval]
max_words = 900
overlap_words = 100

[scheduler]
import_interval_minutes = 60
retry_interval_minutes = 15
max_attempts = 3
retry_delay_seconds = 300

[webhooks]
process_limit = 10
max_attempts = 3
retry_delay_seconds = 60

[telemetry]
enabled = false
endpoint = "http://localhost:4318"
service_name = "fourok-local"

[connectors]
enabled = ["gmail-singer"]
source_limit = 1000
```

Run:

```bash
uv run fourok retention-status --config fourok.toml
uv run fourok purge-raw-retention --config fourok.toml
uv run fourok purge-audit-retention --config fourok.toml
uv run fourok purge-webhook-retention --config fourok.toml
uv run fourok purge-backup-retention --config fourok.toml
```

Internal v0 includes a daily systemd retention template:

```bash
sudo systemctl enable --now fourok-retention.timer
```

`retention-status` is non-destructive. It reports configured raw, audit,
webhook backlog, and backup windows, deletion-eligible counts, and
lifecycle/status coverage for source records and retrieval units. Telemetry is
reported as externally managed by the configured observability backend.

## Rebuild Derived Retrieval State

During internal development, derived retrieval units can be recreated from
stored source records:

```bash
uv run fourok rebuild-retrieval-units --config fourok.toml --confirm-rebuild
```

This deletes and recreates `retrieval_records` only. It does not restore old
schema versions, roll back source records, or recover deleted raw data.

## Secrets

Use external secret manager for connector credentials.

Dagster/Meltano runtime secret injection is controlled by non-committed
environment variables on the host or service manager:


Supported auth:

- Universal Auth:

The Dagster code container receives these variables from Compose and uses the
Python env/.env secret loading in process. Fetched key/value secrets are merged into the
environment of the `meltano run ...` subprocess only. Dagster materialization
metadata exposes only the count of injected secret keys, never values.

Singer tap credential names must follow the tap executable's normal environment
mapping. For this repo, use source-specific prefixes so credentials stay
portable between direct Meltano runs and Dagster-triggered runs:

- Slack: `SLACK_BOT_TOKEN`, plus any selected tap-specific `TAP_SLACK_*` keys.
- Linear: `LINEAR_API_KEY`, plus any selected tap-specific `TAP_LINEAR_*` keys.
- Twenty: `TWENTY_API_KEY`, `TWENTY_BASE_URL`, plus any selected
  tap-specific `TAP_TWENTY_*` keys.
- Google Drive/Docs: `GOOGLE_APPLICATION_CREDENTIALS`,
  `GOOGLE_SERVICE_ACCOUNT_JSON`, or selected tap-specific `TAP_GOOGLE_*` /
  `TAP_GOOGLE_DRIVE_*` keys depending on the chosen tap.

trailing `/api`, the Gmail pilot preflight normalizes it before calling the
Python SDK.

Gmail pilot secret keys:

- `TAP_GMAIL_USER_ID`
- `TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID`
- `TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_SECRET`
- `TAP_GMAIL_OAUTH_CREDENTIALS_REFRESH_TOKEN`

Preflight:

```bash
uv run python scripts/run_gmail_pilot.py \
  --preflight \
```

Never print or commit secrets, raw connector output, local DBs, generated
indexes, or `.local` artifacts.

## Gmail Pilot

Run after preflight:

```bash
uv run python scripts/run_gmail_pilot.py \
  --inspect-output \
  --state-path .local/gmail-pilot/gmail-pilot.sqlite
```

The runner:

- records connector job runs
- persists latest Singer `STATE`
- passes stored state back through `--state`
- writes redacted inspection summaries
- can retry the latest failed job when its backoff window is due

Still unvalidated without a real mailbox:

- Gmail thread/source URL shape
- attachment metadata
- deletion/restriction lifecycle behavior
- permission snapshot mapping
- real incremental state semantics

Retry a failed Gmail pilot job:

```bash
uv run python scripts/run_gmail_pilot.py \
  --inspect-output \
  --state-path .local/gmail-pilot/gmail-pilot.sqlite \
  --retry-failed
```

Tune the retry backoff base delay:

```bash
uv run python scripts/run_gmail_pilot.py \
  --inspect-output \
  --state-path .local/gmail-pilot/gmail-pilot.sqlite \
  --retry-failed \
  --retry-base-delay-seconds 300
```

Retry behavior:

- `--retry-failed` only retries when the latest `gmail-pilot` job failed and its retry window is due.
- If the retry window is not due yet, the runner exits successfully without starting the tap and prints sanitized JSON with `status: retry_not_due`, the next `attempt`, and `earliest_retry_at`.
- When a retry does run, the runner writes the prior stored connector checkpoint to the `--state-input-path` file and passes that path back to the tap through `--state`.
- Redacted inspection summaries remain safe to review; raw Singer output and other local artifacts stay under `.local/` and should not be copied into docs, logs, or commits.
