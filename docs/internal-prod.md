# Internal Production V0

Goal: run the governed context system internally against real Gmail-derived
data, with durable state, restricted raw storage, governed search, source
evidence links, and audit.

This is not the final production platform. It is the smallest internal runtime
that lets us use the system on actual data and learn from operations.

## Scope

In scope:

- one controlled Gmail source
- env/.env-backed connector credentials
- PostgreSQL as the internal runtime database
- restricted filesystem raw store
- scheduled Gmail sync/retry
- governed search, evidence links, and audit
- backup/restore drill
- retention commands
- operator runbook

Out of scope for v0:

- Slack, Drive, Linear, Notion
- object storage
- Kubernetes
- message broker
- OpenSearch
- canonical entity resolution
- production UI
- broad PDF/attachment extraction

## Recommended Runtime Topology

Start with a single internal VM or host.

```text
systemd timers / manual operator commands
  -> docker compose run --rm app ...

Docker Compose services
  -> app service running gcb runtime-monitor
  -> Python app / gcb CLI image for one-off operator commands
  -> PostgreSQL with pgvector
  -> optional local observability profile

Host paths
  -> .local/gcb.toml
  -> /var/log/gcb

Compose volumes
  -> gcb-data mounted at /var/lib/gcb
  -> postgres-data mounted at /var/lib/postgresql/data
  -> observability-data mounted at /data
```

Use Docker Compose locally/on the host for PostgreSQL and the Python app. The resident `app` service runs `gcb runtime-monitor` so Compose restart
state reflects a real long-running process, while `gcb health` remains the
service healthcheck. The app container should be the only supported way to run
one-off `gcb` and Gmail pilot commands in internal prod. Build the image from
the checked-out release or pull a tagged image once releases exist.

The active Compose services use named persistent volumes for runtime state:

- `postgres-data`
- `observability-data`
- `gcb-local`
- `gcb-data`

Keep project-local `.local` paths for local commands, experiments, and explicit
host exports only. Internal-prod runtime state should live in Compose volumes
unless an operator intentionally exports it.

Do not add Kubernetes, a broker, or OpenSearch for v0.

## Network Boundary

Internal prod v0 has no public service surface.

- `app` does not publish an HTTP port; operators run `gcb` through
  `docker compose run --rm app ...`.
- PostgreSQL is bound to `127.0.0.1:5432` for local operator/debug access only.
- The optional observability profile binds Grafana and OTLP endpoints to
  `127.0.0.1`.
- OpenClaw should use a trusted internal plugin/service integration for the RAG
  hook. The agent should receive a short source summary before prompt assembly;
  it should not call the GCB CLI as the product path.

If remote operator access is needed, use host-level SSH/VPN access and keep
Compose ports loopback-bound.

## Runtime Configuration

Create a non-committed runtime config and mount it into the app container:

```bash
mkdir -p .local
export GCB_CONFIG_PATH="$PWD/.local/gcb.toml"
```

```toml
[retention]
raw_source_days = 90
audit_event_days = 365
backup_days = 14
webhook_backlog_days = 14

[raw_store]
backend = "filesystem"
path = "/var/lib/gcb/raw"

[backup]
path = "/var/lib/gcb/backups"

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
endpoint = "http://observability:4318"
service_name = "gcb-app"

[connectors]
enabled = ["gmail-singer"]
source_limit = 1000
```

`gcb webhook-process --config /etc/gcb/gcb.toml` uses `[webhooks]` values for
omitted processing flags. Explicit CLI flags still override them.

For scheduled imports, `[connectors].enabled` is an allowlist when non-empty,
and `[connectors].source_limit` caps loaded records before import.

Commands that accept `--config` use `[telemetry]` when `enabled = true`;
otherwise they fall back to the OpenTelemetry environment variables.

Set non-secret environment:

```bash
export GCB_IMAGE_TAG="$(git rev-parse --short HEAD)"
export GCB_DATABASE_URL="postgresql+psycopg://gcb:<password>@postgres:5432/gcb"
export POSTGRES_PASSWORD="<database-password>"
export GCB_EMBEDDING_PROVIDER="openai"
export GCB_OPENAI_EMBEDDING_MODEL="text-embedding-3-small"
export GCB_EMBEDDING_DIMENSIONS="256"
```

Set machine identity through the host secret mechanism:

```bash
export OPENAI_API_KEY="<openai-api-key>"
```

Do not use the local env-file fallback for internal prod.

## Bring-Up Checklist

1. Start PostgreSQL.

   ```bash
   docker compose up -d postgres
   docker compose build app
   ```

2. Verify database/schema and raw store.

   ```bash
   docker compose run --rm app \
     health --database-url "$GCB_DATABASE_URL"
   ```

3. Verify Gmail credentials without printing secrets.

   ```bash
   docker compose run --rm --entrypoint python app \
     scripts/run_gmail_pilot.py \
       --preflight \
   ```

4. Run the Gmail sync into PostgreSQL.

   ```bash
   docker compose run --rm --entrypoint python app \
     scripts/run_gmail_pilot.py \
       --inspect-output \
       --database-url "$GCB_DATABASE_URL"
   ```

5. Ingest Gmail Singer records into governed state.

   ```bash
   docker compose run --rm app \
     ingest-gmail-singer \
       .local/gmail-pilot/tap-gmail-output.jsonl \
       --database-url "$GCB_DATABASE_URL" \
       --config /etc/gcb/gcb.toml
   ```

6. Validate operator queries.

   ```bash
   docker compose run --rm app audit-summary --database-url "$GCB_DATABASE_URL"
   docker compose run --rm app connector-jobs --database-url "$GCB_DATABASE_URL"
   docker compose run --rm app retention-status --config /etc/gcb/gcb.toml
   docker compose run --rm app dashboard --database-url "$GCB_DATABASE_URL" --config /etc/gcb/gcb.toml
   docker compose run --rm app search-state "refund cancellation" --database-url "$GCB_DATABASE_URL"
   docker compose run --rm app access-smoke --compose-file /app/docker-compose.yml
   ```

   The dashboard output includes an `alerts` section with stable codes and
   counts for operator-visible problems such as failed or invalid connector jobs
   and pending, failed, or invalid webhook events. Each alert also includes the
   threshold that triggered it and a next-step command for investigation. With
   `--config`, connector retry visibility uses the configured scheduler backoff
   and max-attempt values. The `raw_sources` section shows the configured
   raw-store path, raw object count, source-record raw refs, and unreferenced
   raw object count without printing raw payload bodies.

7. Run the deterministic internal v0 regression proof.

   ```bash
   docker compose run --rm app \
     prepare-seed-snapshot \
       --input /app/fixtures/context_substrate/source_snapshot_eval.json \
       --output /app/.local/seeds/context-substrate.json
   ```

   ```bash
   docker compose run --rm app \
     acceptance-proof \
       --database-url "$GCB_DATABASE_URL" \
       --config /etc/gcb/gcb.toml \
       --fixture /app/.local/seeds/context-substrate.json \
       --backup-database-url "$GCB_DATABASE_URL" \
       --backup-output /app/.local/backups/acceptance-proof.dump \
       --observability-endpoint http://observability:4318
   ```

   This fixture-backed regression proof checks config loading, health, raw-store
   writes, webhook enqueue/process/backlog visibility with raw payload landing,
   retention visibility, retrieval-unit rebuild, dashboard stats,
   search/evidence-pack shape, `search` and `source_access` audit records,
   source lifecycle restrict/restore/delete propagation, safe OTel smoke export,
   Compose access-boundary smoke, and PostgreSQL backup and restore command
   wiring without printing raw source bodies or credentials. It is not the live
   operator import path. In short, it proves backup and restore command wiring
   without executing a destructive restore.
   The proof report includes top-level `alerts` for operator-visible failures
   and also summarizes dashboard alert status/count so backlog/import issues,
   failed OTel smoke export, and failed backup or restore-drill command wiring
   are visible from one command. Top-level proof alerts include the trigger
   threshold and a next-step command for the operator.

   If the observability profile is not running, use `console` only for a local
   CLI smoke. Do not use console output as the internal-prod Compose proof.

8. Run a backup and restore drill before calling the runtime usable.

9. Check static internal-prod readiness.

   ```bash
   uv run gcb internal-prod-readiness
   ```

   This checks the active Compose services, pinned image/tag policy, restart
   policies, health checks, persistent volumes, app environment contract, no
   `.reference` runtime dependency, runbook coverage, dependency-contract
   registry, goal audit, and access boundary.

## Scheduling

Use systemd timers or cron for v0.

Suggested jobs:

- source import every 15-60 minutes through `gcb run-imports`
- source retry every 5-15 minutes through `gcb run-imports --retry-failed`
- raw-source retention daily
- audit retention daily
- PostgreSQL backup nightly
- audit summary/report daily

Template units live in `deploy/systemd/`:

- `gcb-run-imports.service`
- `gcb-run-imports.timer`
- `gcb-retry-imports.service`
- `gcb-retry-imports.timer`
- `gcb-postgres-backup.service`
- `gcb-postgres-backup.timer`
- `gcb-retention.service`
- `gcb-retention.timer`

Copy them to the host systemd unit directory, set `WorkingDirectory`,
`GCB_IMAGE_TAG`, `GCB_CONFIG_PATH`, and connector-specific arguments for the
deployed source. Copy `deploy/systemd/gcb.env.example` to `/etc/gcb/gcb.env`,
set the real database URL and external secret manager machine identity there, restrict it to
the operator/service account, and do not commit it:

```bash
sudo install -d -m 0750 /etc/gcb
sudo install -m 0640 deploy/systemd/gcb.env.example /etc/gcb/gcb.env
sudo editor /etc/gcb/gcb.env
```

Then enable the timers:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now gcb-run-imports.timer
sudo systemctl enable --now gcb-retry-imports.timer
sudo systemctl enable --now gcb-postgres-backup.timer
sudo systemctl enable --now gcb-retention.timer
systemctl list-timers 'gcb-*'
```

The committed service templates schedule the internal Gmail Singer path. Update
the `--singer-file` path if the approved live connector lands raw output
somewhere else on the app volume.

Example Docker Compose command for a scheduled internal Gmail import:

```bash
docker compose run --rm app \
  run-imports \
    --connector gmail-singer \
    --singer-file /var/lib/gcb/raw/gmail/tap-gmail-output.jsonl \
    --database-url "$GCB_DATABASE_URL"
```

Example retry command:

```bash
docker compose run --rm app \
  run-imports \
    --connector gmail-singer \
    --singer-file /var/lib/gcb/raw/gmail/tap-gmail-output.jsonl \
    --database-url "$GCB_DATABASE_URL" \
    --config /etc/gcb/gcb.toml \
    --retry-failed \
    --retry-base-delay-seconds 300
```

When `--config` is provided, omitted retry controls use `[scheduler]`
`retry_delay_seconds` and `max_attempts`. Explicit CLI flags still override
configured values where a flag exists.

`gcb run-imports` refuses to start a second run for the same connector while a
previous connector job is still marked `running`. The guard is enforced by a
partial unique database index, so competing cron/systemd workers for the same
connector resolve to one running job. Keep host timers simple and let the
command own connector job state, retry timing, and dashboard visibility.

`gcb-postgres-backup.timer` runs nightly at 02:15 and writes timestamped dump
files under `/var/lib/gcb/backups` in the app container volume. Backup
retention can be enforced with `gcb purge-backup-retention`; encryption and
off-host copy policy are still operator decisions for internal v0.

`gcb-retention.timer` runs daily at 03:15 and applies the configured raw
source, audit-event, terminal webhook backlog, and backup dump retention
windows from `/etc/gcb/gcb.toml`.

## Internal Rebuild Path

During fast internal development, derived retrieval units can be recreated from
stored source records:

```bash
docker compose run --rm app \
  rebuild-retrieval-units \
    --config /etc/gcb/gcb.toml \
    --confirm-rebuild
```

This only rebuilds derived retrieval rows. It is not rollback, legacy
compatibility, or recovery for deleted source/raw data.

## Backup And Restore

Run backup:

```bash
docker compose run --rm app \
  postgres-backup \
    --database-url "$GCB_DATABASE_URL" \
    --output /var/lib/gcb/backups/gcb-$(date +%Y%m%d-%H%M%S).dump
```

Purge expired backup dumps:

```bash
docker compose run --rm app \
  purge-backup-retention \
    --config /etc/gcb/gcb.toml
```

Restore drill:

```bash
docker compose run --rm app \
  postgres-restore-drill \
    --database-url "$GCB_DATABASE_URL" \
    --restore-database-url "$GCB_RESTORE_DATABASE_URL" \
    --backup-output /var/lib/gcb/backups/restore-drill.dump
```

The drill refuses to run if `GCB_RESTORE_DATABASE_URL` points at the same
database as `GCB_DATABASE_URL`. It runs a fresh backup, restores it into the
separate drill database, and verifies the restored database schema health
without printing database passwords in command arguments.

Recorded local evidence:

- Date: 2026-06-07
- App image tag: `9ae4026`
- Result: `status=completed`, restored database health `status=ok`,
  `source_record_count=20`

For manual follow-up after the drill, verify:

```bash
docker compose run --rm -e GCB_DATABASE_URL="$GCB_RESTORE_DATABASE_URL" app health
docker compose run --rm -e GCB_DATABASE_URL="$GCB_RESTORE_DATABASE_URL" app connector-jobs
docker compose run --rm -e GCB_DATABASE_URL="$GCB_RESTORE_DATABASE_URL" app audit-summary
```

## Access Model

Internal prod v0 should be operator-only.

- only trusted internal users can run commands
- no agent gets direct shell/database access
- no Compose service is exposed as an unauthenticated public endpoint
- normal search returns raw internal evidence with source links
- no reveal tool or context-level reveal API is active in this temporary stage
- search and source-access decisions are audited

Real SSO and group mapping can come later, but the operator group must be
explicitly controlled now.

## Current Known Gaps

- Gmail permission snapshots are still missing and therefore records are
  restricted by default unless source permission mapping is added.
- Current pilot sample had no attachments; attachment behavior still needs a
  seeded sample.
- `gcb run-imports` prevents overlapping runs for the same connector with a
  database-backed running-job guard. A broader lock/lease is still a future
  hardening option if multiple worker types appear.
- No production object store exists.
- No UI or HTTP API exists; CLI/operator workflow only.

## Internal Prod V0 Acceptance Criteria

- `gcb health` passes against PostgreSQL and configured raw store.
- App commands run through the Docker Compose `app` service.
- `gcb retention-status` reports configured raw/audit/webhook/backup windows,
  current deletion-eligible counts, and source-record/retrieval-unit lifecycle
  coverage before destructive purge commands are run.
- Gmail preflight passes through external secret manager.
- Gmail sync writes job history and connector checkpoint to PostgreSQL.
- Gmail records ingest into governed state.
- Search, audit, and evidence links work against PostgreSQL.
- Restricted/missing-permission records do not leak through search.
- Backup and restore drill succeeds.
- Scheduler is configured without overlapping sync jobs.
- Runtime commands and environment are documented for operators.
