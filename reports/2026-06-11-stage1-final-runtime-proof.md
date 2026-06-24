# Stage 1 Final Runtime Proof

Date: 2026-06-11

Scope: final evidence for `docs/goal.md` Stage 1 freshness/check closure after discovering that previous acceptance checks could pass while Dagster had failed or stale hourly runs. This report avoids secrets and raw private source payloads.

## Summary

Status: PASS on local runtime after rebuild/restart at commit `92fd453`.

- Corrected Stage 1 acceptance now fails on current Dagster run failures, incomplete required steps, or stale hourly success freshness.
- Dagster image/app image were rebuilt with `FOUR_OK_IMAGE_TAG=92fd453` and local runtime services restarted.
- Manual `fourok_hourly_live_backfill` run succeeded after rebuild.
- Grafana/Prometheus freshness reported the successful hourly backfill within SLA.
- `uv run fourok stage1-acceptance --json` exited 0 and all checks were `ok`.

## Fixes committed

- `83dddde fix(runtime): fail stage1 on stale dagster runs`
  - Adds `runtime_status` to `fourok-dev dagster-status`.
  - Fails Stage 1 Dagster gate unless latest hourly run is successful, required steps are successful, and latest success is fresh.
  - Fails Grafana gate when `[Pipeline] Minutes since successful hourly backfill` is stale.
- `92fd453 fix(slack): preserve textless live messages`
  - Preserves live Slack messages without `text` as metadata records instead of failing source-record import.

## Deterministic checks

```text
uv run pytest tests/etl/extract/test_connectors_ingest.py::test_slack_singer_messages_feed_source_record_adapter tests/etl/extract/test_slack_connectors.py::test_slack_message_adapter_preserves_textless_live_messages_as_metadata_records -q
2 passed in 0.36s

git commit hook for 92fd453:
142 passed in 1.44s
7 passed in 0.57s
```

## Runtime proof

Rebuild/restart:

```text
uv run fourok-dev pipeline-up
FOUR_OK_IMAGE_TAG=92fd453 docker compose --profile observability up --build --force-recreate -d fourok-metrics-exporter promtail
```

Manual Dagster run:

```text
docker exec 4ok-dagster-webserver-1 dagster job launch -w /opt/dagster/dagster_home/workspace.yaml -j fourok_hourly_live_backfill --tags '{"manual":"hermes-stage1-proof","image":"92fd453"}'
```

Latest run result from `uv run fourok-dev dagster-status`:

```json
{
  "latest_run_id": "c28e9004-fe3c-46b8-b346-8abcc31d7a33",
  "latest_run_status": "SUCCESS",
  "latest_success_run_id": "c28e9004-fe3c-46b8-b346-8abcc31d7a33",
  "minutes_since_success": 0.11157543261845906,
  "failed_or_incomplete_steps": {},
  "required_steps": "all SUCCESS"
}
```

Corrected Stage 1 acceptance:

```text
uv run fourok stage1-acceptance --json --report .local/stage1-live-checks/stage1-final.md > .local/stage1-live-checks/stage1-final.json
STAGE1_RC=0
```

Summary from `.local/stage1-live-checks/stage1-final.json`:

```json
{
  "status": "ok",
  "checks": {
    "dagster": "ok",
    "grafana": "ok",
    "health": "ok",
    "permission": "ok",
    "retrieval": "ok"
  },
  "dagster": {
    "latest_run_id": "c28e9004-fe3c-46b8-b346-8abcc31d7a33",
    "latest_run_status": "SUCCESS",
    "minutes_since_success": 0.3418092449506124,
    "failed_or_incomplete_steps": {}
  },
  "grafana": {
    "status": "ok",
    "dashboard_uid": "fourok-local-runtime-logs",
    "minutes_since_successful_hourly_backfill": 0.34317803382873535
  }
}
```

## Remaining before declaring repo done

- Commit this report and final `docs/goal.md` checkbox updates.
- Push local commits.
- Verify `git status --short --branch` has no uncommitted work and no `ahead` marker.
