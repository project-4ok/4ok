# K3s Deployment Readiness

Purpose: hand off the smallest practical 4OK runtime contract for future K3s
deployment through the 4ok infrastructure repository. This is recon/prep, not a
remote deployment instruction.

Current recommendation: do not add 4OK Kubernetes manifests until the local
Docker Compose and Dagster runtime is promoted into a pinned image set and an
infrastructure engineer confirms the target service graph in
`/home/simon/Projects/project-4ok/4ok-infrastructure-prod`.

## Chosen Slice

Create a 4OK-owned readiness runbook and checklist. This keeps product/runtime
facts with the application repo while treating the infrastructure repo as
read-only deployment context.

No Helm, Kustomize, or manifest template is added here because the infra repo
already has:

- Flux reconciliation for customers through
  `clusters/prod/flux-system/prod-customers-kustomization.yaml`
- customer namespace layout at `clusters/prod/customers/4ok`
- existing customer workload groups under:
  - `clusters/prod/customers/4ok/etl`
  - `clusters/prod/customers/4ok/openviking`
  - `clusters/prod/customers/4ok/n8n`
- external secret manager operator-based secret sync patterns

## 4OK Runtime Surfaces

Application image:

- `docker/app.Dockerfile`
- entrypoint: `/app/.venv/bin/fourok`
- required command surface: `health`, `dashboard`, `run-live-ingestion`,
  `live-ingestion-status`, `postgres-backup`, `retention-status`,
  `purge-raw-retention`, `purge-audit-retention`, `purge-webhook-retention`,
  `purge-backup-retention`, `search-state`

Pipeline image:

- `docker/dagster.Dockerfile`
- Dagster definitions and config: `deploy/dagster/`
- code-server port in Compose: `4000`
- webserver port in Compose: `3001`, currently loopback-only for Compose

Local proof topology:

- `docker-compose.yml`
- `app` depends on PostgreSQL
- `postgres` uses `pgvector/pgvector:pg16`
- optional observability uses `grafana/otel-lgtm:0.28.0`
- Dagster pipeline profile uses separate Dagster PostgreSQL, code, webserver,
  and daemon services

## K3s Service Mapping

Minimum useful K3s mapping for 4OK:

- `fourok-app`: Deployment or Job image that runs `fourok` commands.
- `fourok-live-ingestion`: CronJob that runs `run-live-ingestion`.
- `fourok-live-ingestion-status`: operator check or scheduled health probe that
  runs `live-ingestion-status`.
- `fourok-postgres-backup`: CronJob that runs `postgres-backup` to the configured
  backup volume.
- `fourok-retention`: CronJob that runs the four purge commands.
- `fourok-dagster-code`: Deployment for the Dagster code server if K3s owns
  orchestration.
- `fourok-dagster-webserver`: internal-only Service if Dagster UI is needed.
- `fourok-dagster-daemon`: Deployment if schedules and sensors run in-cluster.

Keep `concurrencyPolicy: Forbid` on CronJobs that mutate source state, imports,
backups, or retention. The existing infra ETL CronJobs already use this pattern.

Do not expose 4OK publicly in the first K3s cut. If an ingress is needed for
Dagster, make it private/admin-only and follow the infra repo's existing admin
access pattern rather than adding a public Ingress.

## Configuration

Required non-secret or secret-backed environment variables:

- `FOUR_OK_DATABASE_URL`
- `FOUR_OK_CONFIG_PATH`
- `POSTGRES_PASSWORD` if PostgreSQL is provisioned by the same release path
- `OTEL_EXPORTER_OTLP_ENDPOINT` when telemetry is enabled
- `OTEL_SERVICE_NAME`

Runtime config file requirements:

- mount the TOML config read-only into the app container
- set `[raw_store].path` to `/var/lib/fourok/raw`
- set `[backup].path` to `/var/lib/fourok/backups`
- set `[scheduler]` retry and interval values explicitly
- set `[connectors].enabled` to only the sources approved for the environment
- set `[telemetry].enabled` only after the OTLP endpoint is reachable

Do not commit secret values, and do not print Kubernetes Secret contents during
validation; inspect object existence, controller status, and workload symptoms
instead.

## Persistent State

4OK needs persistent storage for:

- PostgreSQL data, unless an external PostgreSQL service is used
- `/var/lib/fourok/raw`
- `/var/lib/fourok/backups`
- Dagster PostgreSQL data if Dagster runs in-cluster
- Dagster compute logs and artifacts if Dagster runs in-cluster
- connector checkpoint/state volumes where a source needs local state

The current infra repo has a Google Drive ETL PVC at
`clusters/prod/customers/4ok/etl/pvc-etl-state-google-drive.yaml`. Treat that
as a source-specific precedent, not as a 4OK database or raw-store volume.

## Network Policy

Expected first-pass NetworkPolicy posture:

- default deny for 4OK namespaces
- egress to DNS
- egress to external secret manager API
- egress to approved source APIs for enabled connectors
- egress from 4OK to PostgreSQL
- optional egress from 4OK to OTLP collector
- no public ingress for `fourok-app`
- private/admin-only ingress for Dagster UI only if explicitly approved

The infra repo already uses `NetworkPolicy` under
`clusters/prod/customers/4ok/etl`, `clusters/prod/customers/4ok/openviking`,
and `clusters/prod/customers/4ok/n8n`.

## Secrets

Use the infra repo's existing `external secret managerSecret` pattern rather than committing
Kubernetes Secret values.

Relevant infra pointers:

- `docs/runbooks/customer-secret-sync-validation.md`
- `docs/reference/4ok-etl-secret-contract-v1.md`

Infrastructure engineer checklist:

- confirm the external secret manager source path for 4OK runtime secrets
- confirm whether 4OK shares an existing customer path or receives a dedicated
  path
- create the bootstrap Universal Auth Kubernetes Secret out-of-band
- verify the external secret manager operator watches the target namespace
- verify the `external secret managerSecret` object reconciles before enabling 4OK workloads
- validate secret availability by workload readiness/errors, not by printing
  values

## Health Checks

Container health:

```bash
fourok health
```

Operator checks:

```bash
fourok dashboard --database-url "$FOUR_OK_DATABASE_URL" --config "$FOUR_OK_CONFIG_PATH"
fourok live-ingestion-status --database-url "$FOUR_OK_DATABASE_URL" --config "$FOUR_OK_CONFIG_PATH"
fourok retention-status --database-url "$FOUR_OK_DATABASE_URL" --config "$FOUR_OK_CONFIG_PATH"
```

Pipeline checks if Dagster is enabled:

```bash
dagster api grpc-health-check -p 4000
dagster-daemon liveness-check
```

Pre-deployment local proof should still be run in 4OK before the infra repo is
asked to deploy the workload:

```bash
uv run fourok internal-prod-readiness --compose-file docker-compose.yml
uv run fourok-dev fast
```

## Rollback Assumptions

The first K3s rollout should be reversible by:

- suspending 4OK CronJobs
- scaling 4OK Deployments to zero
- reverting the Flux commit that introduced or enabled 4OK resources
- preserving PostgreSQL, raw-store, backup, Dagster, and checkpoint PVCs
- restoring PostgreSQL from a `postgres-backup` artifact if schema/data changes
  need rollback

Rollback should not delete PVCs by default. Deletion of raw stores, backups, or
connector checkpoints needs a separate retention/deletion decision.

## Infrastructure Engineer Checklist

- [ ] Confirm the target namespace layout for 4OK in the infra repo.
- [ ] Decide whether 4OK is a new customer workload group or part of existing
      `clusters/prod/customers/4ok/etl`.
- [ ] Confirm image registry, tag, and digest policy for `docker/app.Dockerfile`.
- [ ] Confirm whether `docker/dagster.Dockerfile` is deployed in the first K3s
      cut or deferred.
- [ ] Confirm PostgreSQL location: in-cluster StatefulSet, existing managed
      service, or external host.
- [ ] Create 4OK config as a ConfigMap or secret-backed rendered file without
      embedding credentials.
- [ ] Wire `external secret managerSecret` for 4OK runtime secrets.
- [ ] Add PVCs for `/var/lib/fourok/raw` and `/var/lib/fourok/backups`.
- [ ] Add health probes using `fourok health`.
- [ ] Add CronJobs for imports, backups, and retention with
      `concurrencyPolicy: Forbid`.
- [ ] Keep all 4OK services private until an explicit ingress decision exists.
- [ ] Run `fourok dashboard`, `fourok live-ingestion-status`, and
      `fourok retention-status` after the first reconcile.
- [ ] Record any unresolved external-service or retention risks in
      `docs/review.md`.

## Not Ready Yet

Open deployment questions:

- final 4OK namespace and ownership boundary in the infra repo
- image publication path and immutable digest/tag convention
- PostgreSQL deployment target and backup restore drill location
- whether Dagster moves to K3s immediately or stays Compose/host-operated
- exact external secret manager path and key names for the 4OK runtime
- private operator access path for Dagster, if enabled
- retention policy for PVC-backed raw stores and backups
