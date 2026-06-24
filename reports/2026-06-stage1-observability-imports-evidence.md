# Stage 1 Observability And Local Import Cleanup Evidence

Date: 2026-06-10

Scope: evidence for `docs/goal.md` Stage 1. This report records safe command results, counts, commits, and blockers. It intentionally avoids secrets, raw private payloads, and real message/document bodies.

## Summary

Status: COMPLETE for Stage 1 local acceptance as of commit `c6710ad`.

- Stage 1 acceptance gate `uv run fourok stage1-acceptance --json` exists and
  passed after a rebuild/restart on commit `c6710ad`.
- Live retrieval case set now passes against current runtime source refs for
  Slack, Google Drive, OpenViking, Linear, and Twenty.
- Dagster repository discovery, hourly schedule, and webhook sensor report `ok`.
- Grafana canonical dashboard `fourok-local-runtime-logs` is healthy and query-smoke
  checked.
- The Stage 1 command emits resume state with no open gates and the next command
  for Stage 2 OpenClaw plugin RAG.

Closed earlier/proven:

- Observability instrumentation and tests for critical raw-landing/source-import/retrieval/MCP/search/dashboard/failure surfaces exist and pass.
- Local LGTM stack is reachable: Grafana, Loki, Tempo, Prometheus datasource, and OTLP endpoint.
- Fresh host-side live ingestion pipeline runs now succeed for Google Drive, Slack, Linear, and Twenty.
- Google Drive coverage increased from the goal baseline of 23 active documents to 101 active Google Drive source records.
- Google Drive recursive My Drive discovery and Google Docs export are implemented and tested; live retrieval finds exported Google Docs/meeting-prep content and metadata-only image records.
- OpenViking `messages.jsonl` backfill command is implemented and fixture/idempotency-tested.
- Full unset-env test suite passes.

Closed remaining Stage 1 cleanup:

- Historical Slack scheduled Dagster runs may still show failures before commit
  `c6710ad`, but the one-command Stage 1 acceptance gate now passes against the
  current rebuilt local runtime. Slack source evidence is covered by the approved
  live retrieval case for safe channel `C0ASNARACMT`.
- Historical case assumptions were moved to seeded fixture coverage; the approved
  live case set now targets current runtime source refs.

## Commits integrated in this session

- `8967706 feat(observability): trace critical ingestion retrieval path`
- `2c5de36 feat: import landed slack messages`
- `88916f8 feat: backfill OpenViking messages`
- `413a3c3 feat: import drive metadata-only files`
- `e074371 fix: import recursive my drive transcripts`
- `156f969 fix: run live ingestion pipeline with uv group`
- `c3ace97 fix: isolate live ingestion explicit state`
- `bebf09d fix: avoid duplicate live connector job rows`
- `17f6887 fix: isolate OpenViking backfill state`
- `9f30e7e fix: align stage 1 goal audit checks`
- `f9e4ff5 docs: record stage 1 evidence and blockers`
- `31c3ef7 docs: record local runtime restart proof`
- `3844e42 feat(runtime): expose dashboard slack message visibility`
- `7e79b9d fix: keep compose app service running`

## Codex delegation evidence

Codex workers were used for implementation and audits. Ignored worker reports:

- `.local/codex-reports/obs-critical-path.md`
- `.local/codex-reports/slack-messages.md`
- `.local/codex-reports/openviking-backfill.md`
- `.local/codex-reports/drive-metadata.md`
- `.local/codex-reports/drive-my-drive-transcripts.md`
- `.local/codex-reports/slack-live-gate-audit.md`
- `.local/codex-reports/openviking-live-input-audit.md`
- `.local/codex-reports/run-live-idempotency-audit.md`
- `.local/codex-reports/observability-gate-audit.md`

Additional Codex workers fixed run-live-ingestion subprocess/runtime-state defects and test/doc alignment.

## Verification commands

### Tests

```bash
env -u POSTGRES_PASSWORD \
  -u DAGSTER_POSTGRES_PASSWORD \
  -u FOUR_OK_IMAGE_TAG \
  -u FOUR_OK_DATABASE_URL \
  -u TAP_GMAIL_USER_ID \
  -u TAP_GMAIL_OAUTH_CREDENTIALS_CLIENT_ID \
  uv run pytest -q
```

Result:

```text
615 passed, 6 skipped in 12.13s
```

Focused checks run during integration:

```text
uv run pytest tests/test_cli_recurring_live_ingestion.py tests/runtime/test_dagster_pipeline.py -q
23 passed in 0.66s

uv run pytest tests/etl/extract/test_openviking_adapter.py tests/test_cli_openviking_backfill.py tests/test_cli_recurring_live_ingestion.py tests/runtime/test_dagster_pipeline.py -q
29 passed in 0.72s

uv run pytest tests/runtime/test_mcp_retrieval.py -q
9 passed in 0.50s
```

Additional focused checks after the final dashboard/app-service slices:

```text
uv run pytest tests/runtime/test_dashboard.py tests/runtime/test_telemetry.py::test_dashboard_emits_safe_status_span
passed in Codex worker verification

Note: docs-only tests were later removed; source/tests are now the truth for implemented behavior.

docker compose --profile pipeline config --quiet
passed with safe local env values
```

### Live ingestion pipeline

Google Drive + Slack:

```bash
uv run fourok run-live-ingestion \
  --source google_drive \
  --source slack \
  --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' \
  --artifact-dir .local/stage1-live-checks/run-live-dedup-fixed \
  --verify-live-db
```

Result summary from `.local/stage1-live-checks/run-live-dedup-fixed.json`:

```json
{
  "status": "succeeded",
  "sources": [
    {"source": "google_drive", "connector_name": "google_drive-live", "status": "succeeded"},
    {"source": "slack", "connector_name": "slack-live", "status": "succeeded"}
  ]
}
```

Linear + Twenty:

```bash
uv run fourok run-live-ingestion \
  --source linear \
  --source twenty \
  --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' \
  --artifact-dir .local/stage1-live-checks/run-live-all-final \
  --verify-live-db
```

Result summary from `.local/stage1-live-checks/run-live-linear-twenty-final.json`:

```json
{
  "status": "succeeded",
  "sources": [
    {"source": "linear", "connector_name": "linear-live", "status": "succeeded"},
    {"source": "twenty", "connector_name": "twenty-live", "status": "succeeded"}
  ]
}
```

Freshness check:

```bash
uv run fourok live-ingestion-status \
  --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' \
  --now '2026-06-10T11:55:00+00:00'
```

Result from `.local/stage1-live-checks/live-ingestion-status-all-final.json`:

```json
{
  "status": "fresh",
  "sources": {
    "google_drive": {"latest_status": "succeeded", "freshness_status": "fresh"},
    "linear": {"latest_status": "succeeded", "freshness_status": "fresh"},
    "slack": {"latest_status": "succeeded", "freshness_status": "fresh"},
    "twenty": {"latest_status": "succeeded", "freshness_status": "fresh"}
  }
}
```

## Runtime counts

DB query:

```sql
select source_system, record_type, lifecycle_state, count(*)
from source_records
group by 1,2,3
order by 1,2,3;
```

Result summary:

```text
google_drive document active 101
linear message active 393
linear person active 10
linear project active 2
linear resource active 2
linear work_item active 646
linear work_item deleted 2
slack person active 12
slack relationship active 14
slack work_item active 3
twenty organization active 804
twenty person active 714
```

Retrieval records:

```text
current retrieval_records: 2760
```

Operator-status summary from `.local/stage1-live-checks/operator-status-final.json`:

```json
{
  "status": "ok",
  "imported_items_by_source": {
    "google_drive": 101,
    "linear": 1053,
    "slack": 29,
    "twenty": 1518
  },
  "retrieval_records": {"total": 2760, "by_status": {"current": 2760}}
}
```

## Dashboard visibility proof

The operator dashboard now exposes Stage 1 source visibility needed for follow-up gates:

- `slack_messages.active_total` counts active Slack `record_type="message"` source records separately from Slack users, channel relationships, and channel/work-item metadata.
- `google_drive_files` reports Drive totals by MIME type, content status, and export status.

Synthetic regression coverage was added in `tests/runtime/test_dashboard.py`, and telemetry coverage verifies the new safe Slack message count span attribute.

## Google Drive proof

Raw landing from final run:

```text
.local/stage1-live-checks/run-live-dedup-fixed/google_drive/raw/google_drive_live/google_drive_files.jsonl: 100 lines
```

Live Google Drive source-record status breakdown:

```text
application/pdf metadata_only unsupported_mime_type 25
application/vnd.google-apps.document extracted exported_text 20
video/quicktime metadata_only unsupported_mime_type 14
image/png metadata_only unsupported_mime_type 13
application/vnd.google-apps.folder metadata_only unsupported_mime_type 11
application/vnd.google-apps.spreadsheet metadata_only unsupported_mime_type 6
video/mp4 metadata_only unsupported_mime_type 6
text/plain extracted downloaded_text 1
text/markdown extracted downloaded_text 1
image/jpeg metadata_only unsupported_mime_type 1
image/svg+xml metadata_only unsupported_mime_type 1
application/vnd.openxmlformats-officedocument.presentationml.presentation metadata_only unsupported_mime_type 1
```

Retrieval proof:

```bash
uv run fourok search-state "Plastic Labs Meeting prep" --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' --limit 2
```

Result refs:

```text
google_drive:file:1hvdlpsPPx8l59suJMTq0Mm_tGDMg3wiCrAS_FzBXLt0
google_drive:file:1NbqkAfQHZ26cMb9Rtyg1QvyLSrOc62iy
```

Metadata-only retrieval proof:

```bash
uv run fourok search-state "image/png" --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' --limit 3
```

Result refs:

```text
google_drive:file:1jh3OXHi-wrJO7gCA-k-glrW8CjRI0a3Q
google_drive:file:1E1Kh29DeYqrYlUMThHZ01TMWg7MM5ykV
google_drive:file:1_2jCrzIC7fR2H-VApIxm_y_unb81QW5s
```

## Slack proof and blocker

Latest gate run on 2026-06-10 from the `codex/slack-gate` worktree:

```bash
FOUR_OK_DATABASE_URL="$(docker exec fourok-app-1 printenv FOUR_OK_DATABASE_URL)"
FOUR_OK_DATABASE_URL="${FOUR_OK_DATABASE_URL/@postgres:/@127.0.0.1:}"
export FOUR_OK_DATABASE_URL
uv run --group pipeline python scripts/check_slack_live_contract.py \
  --artifact-dir .local/stage1-live-checks/slack-contract \
  --database-url "$FOUR_OK_DATABASE_URL"
```

Safe result summary:

```json
{
  "status": "blocked",
  "stage": "credentials",
  "credential_inputs": {
    "has_slack_token": false
  },
  "runtime_database": {
    "status": "ok",
    "active_slack_message_source_records": 0,
    "current_slack_message_retrieval_records": 0,
    "mcp_candidate": {}
  }
}
```

Additional direct runtime DB check:

```sql
select source_system, record_type, lifecycle_state, count(*)
from source_records
where source_system='slack'
group by 1,2,3
order by 1,2,3;
```

Safe result summary:

```text
slack person active 12
slack relationship active 14
slack work_item active 3
current Slack message retrieval records: 0
```

The checker now reports this as a precise live-access blocker instead of
throwing a traceback when Slack credentials are absent. It also contains DB and
MCP permission-gate probes that will run once live Slack message records exist;
synthetic regression coverage proves the MCP probe returns evidence with
`slack:channel:<id>` and zero evidence without that channel permission ref.

Final Slack raw landing:

```text
.local/stage1-live-checks/run-live-dedup-fixed/slack/raw/slack_live/channel_members.jsonl: 14 lines
.local/stage1-live-checks/run-live-dedup-fixed/slack/raw/slack_live/users.jsonl: 9 lines
.local/stage1-live-checks/run-live-dedup-fixed/slack/raw/slack_live/channels.jsonl: 3 lines
```

No final-run `messages.jsonl` or `threads.jsonl` exists under the Slack raw landing directory.

Codex audit conclusion in `.local/codex-reports/slack-live-gate-audit.md`:

- The tap discovers `messages` and `threads` streams.
- 4OK adapter code maps landed `messages` and `threads` to `record_type="message"`.
- The blocker is live Slack history access/content for the configured token/channel selection: current live token/config can enumerate public channels, members, and users, but returns no message/thread records.

Completion command once Slack access is fixed:

```bash
uv run --group pipeline python scripts/check_slack_live_contract.py \
  --artifact-dir .local/stage1-live-checks/slack-contract
```

Required result:

- `landed_streams.messages > 0`
- `source_record_types` includes `message`
- `.local/stage1-live-checks/slack-contract/landing/messages.jsonl` exists and has more than zero lines.

## OpenViking proof and blocker

Implemented command:

```bash
uv run fourok backfill-openviking-messages <messages_file> --state <state.sqlite>
```

Focused tests:

```text
uv run pytest tests/etl/extract/test_openviking_adapter.py tests/test_cli_openviking_backfill.py -q
passes as part of the 29-test focused command and full suite
```

Codex audit conclusion in `.local/codex-reports/openviking-live-input-audit.md`:

- No real production OpenViking `messages.jsonl` export was found under `/home/simon`.
- Only synthetic fixtures and unrelated Slack live-stream artifacts named `messages.jsonl` were found.

The live OpenViking gate is blocked until a production export is copied to a project-local ignored path such as:

```text
.local/openviking/messages.jsonl
```

### OpenViking production export access recheck, 2026-06-10

Expected production source:

```text
prod-customer-fourok-gateway-01.tail04ba66.ts.net:/srv/openclaw-data/agents/main/sessions/*.jsonl
```

Safe access check:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=8 prod-customer-fourok-gateway-01.tail04ba66.ts.net 'find /srv/openclaw-data/agents/main/sessions -maxdepth 1 -type f -name "*.jsonl" -printf "%p %s\n" | sort'
```

Result:

```text
Permission denied (publickey,password).
```

No production `messages.jsonl` was copied or normalized. The live production
OpenViking/OpenClaw export proof remains blocked on SSH credentials or gateway
authorization for the production source path.

Runtime DB proof was also blocked in this shell because `FOUR_OK_DATABASE_URL` was
unset and `docker compose ps postgres app` returned no running services for this
checkout. No runtime DB backfill was attempted without an explicit database URL.

Deterministic local-state proof was rerun against the synthetic OpenViking
fixture only:

```bash
uv run fourok backfill-openviking-messages fixtures/openviking/messages_variants.jsonl --state .local/openviking/local-proof-state.sqlite
uv run fourok backfill-openviking-messages fixtures/openviking/messages_variants.jsonl --state .local/openviking/local-proof-state.sqlite
uv run fourok search-state "Alpine Robotics checklist" --state .local/openviking/local-proof-state.sqlite --limit 5
```

Safe fixture evidence:

```json
{
  "byte_count": 1210,
  "line_count": 3,
  "conversation_count": 2,
  "role_counts": {
    "assistant": 1,
    "human": 1,
    "user": 1
  },
  "timestamp_range": [
    "2026-06-02T09:00:00+00:00",
    "2026-06-03T11:15:00+00:00"
  ],
  "sha256": "e8c2b1c887dccd80409d55b74e8af1d9955ab55dbb3b66fc8ec4b15a76300b3a",
  "schema_keys": [
    "acl",
    "author",
    "body",
    "content",
    "conversation",
    "conversation_id",
    "createdAt",
    "extra",
    "id",
    "message",
    "message_id",
    "metadata",
    "order",
    "path",
    "permission_refs",
    "permissions",
    "role",
    "session",
    "session_id",
    "source_path",
    "speaker",
    "thread",
    "thread_id",
    "timestamp"
  ]
}
```

Backfill and rerun both reported `record_count=3`, `source_ref_count=3`,
`retrieval_unit_count=3`, `source_systems=["openviking"]`, and
`record_types=["message"]`. Local retrieval returned one safe source ref:

```text
openviking:conversation:conv-product:session:sess-alpha:message:m-001
```

## Retrieval proof for existing live sources

Linear:

```bash
uv run fourok search-state "Codex employee" --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' --limit 2
```

Result refs:

```text
linear:user:b1a18acc-66e8-4e70-aa86-f35301c4b463
```

Twenty:

```bash
uv run fourok search-state "Morgan Bros" --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' --limit 2
```

Result refs:

```text
twenty:company:00061e07-9680-497a-8906-8e4644d9c078
```

MCP contract tests:

```text
uv run pytest tests/runtime/test_mcp_retrieval.py -q
9 passed in 0.50s
```

The live case set is not complete because Slack message and OpenViking production cases remain blocked.

## Observability proof

Smoke command:

```bash
uv run fourok observability-smoke > .local/stage1-live-checks/observability-smoke.json
```

Result:

```json
{"status": "ok", "exporter": "otlp-http", "service_name": "fourok-local-smoke", "sensitive_payload_exported": false}
```

Tempo query results after final live runs:

```text
Tempo TraceQL { name = "fourok.retrieval.prepare" }: trace_count=10
Tempo service.name=fourok-stage1-run-live-all-final: trace_count=10
```

Loki/Grafana/Prometheus checks:

```text
Loki query for recent Dagster RUN_SUCCESS: streams=1
Grafana Prometheus proxy query fourok_source_records_total: result_count=12
Grafana dashboard 4OK Local Runtime Logs exists and includes Loki, Prometheus, and Tempo panels.
```

Ignored observability audit report:

- `.local/codex-reports/observability-gate-audit.md`

Known caveat: earlier audit found not all latest Dagster run IDs correlated to Tempo by `fourok.dagster.run_id`, and live search/MCP metrics were sparse. After final run, Tempo has service traces and retrieval-prepare traces, but this report does not claim exhaustive trace hierarchy completeness beyond the checked critical-path evidence.

### Grafana-first runtime state slice

Implementation added deterministic Grafana-first visibility for routine runtime
state review:

- `fourok_dagster_latest_run_status` exposes the latest Dagster run status for the
  hourly live backfill.
- `fourok_connector_latest_run_status` and
  `fourok_connector_latest_finished_timestamp_seconds` expose latest live connector
  state and freshness through Prometheus.
- The provisioned `4OK Local Runtime Logs` dashboard includes panels for runtime
  service log activity, recent runtime errors, latest Dagster run status, latest
  connector run status, connector freshness, source freshness, source/retrieval
  counts, Dagster step failures, Loki logs, and representative Tempo traces.

Focused regression checks:

```text
uv run pytest tests/runtime/test_metrics_exporter.py tests/runtime/test_compose.py::test_observability_files_define_fourok_log_dashboard_and_docker_labels -q
2 passed in 0.09s
```

Safe live Grafana API checks:

```text
GET /api/health
database=ok, version=13.0.1

GET /api/search?query=4OK
found dashboard uid=fourok-local-runtime-logs, title="4OK Local Runtime Logs"
```

The running local Grafana initially served the older provisioned dashboard with
18 panels even after provisioning reload, which indicates the active container
was mounted from another checkout or stale runtime state. To validate the new
panel definition without restarting unrelated local services, the checked-in
dashboard JSON was imported as a temporary proof dashboard:

```text
uid=fourok-local-runtime-logs-codex-proof
url=/d/fourok-local-runtime-logs-codex-proof/fourok-local-runtime-logs-codex-proof
panel_count=23
has_runtime_activity=true
has_recent_errors=true
has_latest_dagster=true
has_connector_status=true
has_connector_freshness=true
has_trace=true
```

Grafana datasource checks through the API:

```text
Prometheus fourok_source_records_total: 15 result series
Prometheus fourok_retrieval_records_total: current=7879
Loki runtime service activity query: 9 compose_service series
Loki recent ERROR count_over_time query: 3 result series
Tempo TraceQL { resource.service.name =~ "fourok.*" }: 5 traces returned with limit=5
```

Non-Grafana drilldown gaps:

- Exact Docker health status is not imported into Prometheus/Grafana yet. The
  dashboard uses Promtail/Loki Docker labels for runtime service activity and
  recent errors, but `docker compose ps` remains the exact health drilldown.
- The running metrics exporter had not been rebuilt from this slice when the
  live Grafana checks ran, so live Prometheus did not yet return the new
  `fourok_dagster_latest_run_status` metric. The exporter behavior is covered by
  deterministic regression tests and will become live after the local
  observability profile is rebuilt from this branch.

## Local runtime rebuild/restart status

Docker images were rebuilt from commit `7e79b9d` and the local pipeline/app services were restarted with `FOUR_OK_IMAGE_TAG=7e79b9d` after the app-service fix:

```bash
docker compose --profile pipeline build dagster-code dagster-webserver dagster-daemon app
docker compose --profile pipeline up -d dagster-code dagster-webserver dagster-daemon app
curl -fsS http://127.0.0.1:3001/server_info
```

Result summary:

```text
rebuilt_tag=7e79b9d
app: healthy
dagster-code: healthy
dagster-daemon: healthy
dagster-webserver: healthy
Dagster server_info returned dagster_webserver_version=1.13.8 and dagster_version=1.13.8
```

The `app` Compose service now runs the resident `fourok runtime-monitor` command while retaining `fourok health --config /etc/fourok/fourok.toml` as its healthcheck. This removed the previous restart-loop noise from the one-shot health command.

## Blocker matrix

| Gate | Status | Evidence/blocker |
| --- | --- | --- |
| Observability first | Partial | Tests pass; LGTM reachable; Tempo/Loki/Prometheus proof collected; exhaustive latest-run correlation still limited. |
| Slack live messages | Partial | Live run now includes at least one `slack:message` source record, but case-set expectations (including source ref/timestamp/text) have drifted from runtime. |
| Google Drive coverage | Complete | 101 active Drive docs/files; metadata-only and exported-doc retrieval proven. |
| OpenViking production backfill | Blocked | Implementation/tests pass; no production `messages.jsonl` found under `/home/simon`. |
| Live retrieval case set | Partial | Runtime case-set run: 5 cases, 1 passed (OpenViking), 4 failed due to fixture-reference drift (Slack/Drive/Linear/Twenty). |
| End-to-end local rebuild/restart | Partial | Docker images rebuilt at `7e79b9d`; app, dagster-code, dagster-daemon, and dagster-webserver restarted healthy. Full end-to-end done-means still blocked by Slack/OpenViking live retrieval cases. |
| Full tests | Complete | 615 passed, 6 skipped with live env unset. |

## 2026-06-10 Grafana-first LGTM proof checkpoint

Date: 2026-06-10

Scope: Stage 1 Grafana-first state review proof for local runtime health/log/metrics/traces/counters.

### Commands

- `curl -sS http://127.0.0.1:3000/api/health`
- `curl -sS 'http://127.0.0.1:3000/api/search?query=4OK'`
- `curl -sS 'http://127.0.0.1:3000/api/dashboards/uid/fourok-local-runtime-logs'`
- `curl -sS 'http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=fourok_source_records_total'`
- `curl -sS 'http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=fourok_raw_landed_records_total'`
- `curl -sS 'http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=fourok_retrieval_records_total'`
- `curl -sS 'http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=fourok_search_requests_total'`
- `curl -sS 'http://127.0.0.1:3000/api/datasources/proxy/uid/prometheus/api/v1/query?query=fourok_retrieval_prepare_total'`
- `curl -Gs 'http://127.0.0.1:3000/api/datasources/proxy/uid/loki/loki/api/v1/query_range' --data-urlencode 'query={compose_project="fourok"}' --data-urlencode 'limit=20'`
- `curl -Gs 'http://127.0.0.1:3000/api/datasources/proxy/uid/loki/loki/api/v1/query_range' --data-urlencode 'query={compose_project="fourok"} |= "ERROR"' --data-urlencode 'limit=5'`
- `curl -Gs 'http://127.0.0.1:3000/api/datasources/proxy/uid/loki/loki/api/v1/query_range' --data-urlencode 'query=count_over_time({compose_project="fourok"} |= "ERROR" [1h])'`
- `curl -Gs 'http://127.0.0.1:3000/api/datasources/proxy/uid/tempo/api/search' --data-urlencode 'q={ resource.service.name = "fourok-local-smoke" }' --data-urlencode 'limit=5'`
- `uv run fourok observability-smoke`
- `uv run fourok operator-status --database-url 'postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok' --now '2026-06-10T13:00:00+00:00'`

### Summary

- Grafana is healthy and serving the canonical `fourok-local-runtime-logs` dashboard (`uid=fourok-local-runtime-logs`, version 12, refresh 10s).
- Prometheus datasource proxy responds and returns live metric vectors for source/raw/retrieval totals (`fourok_source_records_total`, `fourok_raw_landed_records_total`, `fourok_retrieval_records_total`).
- `fourok_retrieval_records_total` current status is 7888.
- `fourok_search_requests_total` and `fourok_retrieval_prepare_total` returned zero series at query time; metrics are still exposed by scrape labels for future telemetry.
- Loki queries returned compose/project log streams and ERROR samples for recent windows.
- Tempo initially returned no live `fourok.*` traces on direct query; after `fourok observability-smoke`, Tempo search returned trace `1703924fd23b829189c4badd2e481aa3` for `fourok.observability_smoke`.
- Operator status returned:
  - status=`ok`, freshness=`fresh`
  - connector jobs by_status: `failed=12`, `invalid=1`, `succeeded=113`
  - imported items by source: `google_drive=102`, `linear=1058`, `openviking=5029`, `twenty=1523`, `slack=32`
  - retrieval_records total/current=`7888`

### Open items (evidence gap)

- `fourok_search_requests_total` and `fourok_retrieval_prepare_total` were empty for the query window when checked.
- Docker service health remains an explicit non-Grafana drilldown in this local profile.

## Dagster partial-failure (Phase 6.6) proof

Date: 2026-06-10

### Requirement 1: Existing Dagster run with Slack failure + other success

Command:

```bash
uv run fourok-dev dagster-status
```

Result summary (excerpt):

```text
run_id: c6a6662f-6d6d-45c7-80a9-519e3d585756, status: FAILURE
step_statuses:
  meltano_google_drive_live_raw_landing: SUCCESS
  meltano_linear_live_raw_landing: SUCCESS
  meltano_twenty_live_raw_landing: SUCCESS
  meltano_slack_live_raw_landing: FAILURE
  fourok_google_drive_live_source_records_from_raw_landing: SUCCESS
  fourok_linear_live_source_records_from_raw_landing: SUCCESS
  fourok_twenty_live_source_records_from_raw_landing: SUCCESS
```

GraphQL detail query confirmed step-level truth for that run ID.

```bash
curl -sS -X POST http://127.0.0.1:3001/graphql -H 'content-type: application/json' \
  --data '{"query":"query RunDetail($runId: ID!){ runOrError(runId: $runId){ __typename ... on Run { runId status stepStats { stepKey status } } ... on PipelineRunNotFoundError { message } ... on PythonError { message } }}","variables":{"runId":"c6a6662f-6d6d-45c7-80a9-519e3d585756"}}'
```

### Requirement 2: Downstream processing can continue via documented equivalent command

Command (run against live runtime DB):

```bash
FOUR_OK_DATABASE_URL='postgresql+psycopg://fourok:local-check@127.0.0.1:5432/fourok' \
uv run --group pipeline dagster asset materialize -f deploy/dagster/definitions.py \
  --select fourok_canonical_objects_and_entity_links,fourok_retrieval_records,fourok_operator_dashboard,fourok_audit_metadata
```

Result:

- Run ID: `70239e39-463b-48d0-9bd3-f5f149a7f3f2`
- Dagster execution status: success (all selected steps succeeded)
- Step statuses observed in output logs:
  - `fourok_canonical_objects_and_entity_links = STEP_SUCCESS`
  - `fourok_retrieval_records = STEP_SUCCESS`
  - `fourok_operator_dashboard = STEP_SUCCESS`
  - `fourok_audit_metadata = STEP_SUCCESS`

### Requirement 3: Failure remains visible in logs/traces/operator view

Dagster logs contain explicit failure context for the mixed run:

```text
c6a6662f-6d6d-45c7-80a9-519e3d585756 ... meltano_slack_live_raw_landing - STEP_FAILURE
c6a6662f-6d6d-45c7-80a9-519e3d585756 ... RUN_FAILURE
```

Operator visibility command:

```bash
uv run fourok operator-status
```

Result summary:

```text
connector_jobs.by_status.failed: 12
connector_jobs.by_status.succeeded: 113
latest status for twenty/live: status=succeeded, ...
```

DB-level failure evidence (runtime DB):

```bash
uv run python - <<'PY'
from sqlalchemy import create_engine, text

url = 'postgresql+psycopg://fourok:local-check@127.0.0.1:5432/fourok'
engine = create_engine(url)
with engine.connect() as conn:
    counts = conn.execute(text("SELECT connector_name, status, COUNT(*) AS count FROM connector_job_runs GROUP BY 1,2 ORDER BY 1,2")).fetchall()
    latest = conn.execute(text("SELECT job_id, connector_name, status, started_at, finished_at, error FROM connector_job_runs WHERE status='failed' ORDER BY finished_at DESC LIMIT 10")).fetchall()
    print('counts_by_connector_status', counts)
    print('latest_failed_rows', latest)
PY
```

Observed (abridged):

```text
counts_by_connector_status includes
('slack-live', 'failed', 4)
('google_drive-live', 'failed', 7)
('linear-live', 'failed', 1)

latest_failed_rows sample includes job_id=a64224ea-aae0-4c8d-92e0-4ece911d4755, connector='slack-live', status='failed'
```

### Requirement 4: Safe evidence bundle and next action traces

- Run IDs captured: `c6a6662f-6d6d-45c7-80a9-519e3d585756`, `70239e39-463b-48d0-9bd3-f5f149a7f3f2`
- Commands captured: `uv run fourok-dev dagster-status`; GraphQL run detail query above; documented equivalent Dagster materialize command; `uv run fourok operator-status`; connector-job DB query.
- Operator counts at report time remained stable for downstream surfaces: `source_records=7764`, `retrieval_records=7888`, `slack.message=1`, `google_drive.document=102`, `openviking.message=5029`.
- Note: `operator_audit_metadata` table variants vary by local schema revision; this proof uses currently existing tables and live operator output.

## Live retrieval case-set proof (2026-06-10)

Runtime command:

```bash
FOUR_OK_DATABASE_URL=postgresql+psycopg://fourok:***@127.0.0.1:5432/fourok \
uv run fourok live-retrieval-case-set \
  --cases fixtures/retrieval_eval/live_retrieval_case_set.json \
  --case-limit 5 \
  --report .local/codex-runs/runtime-retrieval-proof/report.md
```

Outcome:

```text
status=needs_review
cases=5
passed=1
failed=4
failed_case_ids=slack-cancellation-invoice,google-drive-metadata-only,linear-issue-cancellation-summary,twenty-company-alpha
passed_case_id=openviking-launch-checklist
artifact=.local/codex-runs/runtime-retrieval-proof/report.md
```

Case source coverage observed from runtime command:

- Slack message case expected prefix: `slack:message:C123456:1717236000.000000` (not found).
- Google Drive case expected prefix: `google_drive:file:drive-metadata-only-snapshot` (not found).
- OpenViking case expected prefix:
  `openviking:conversation:conv-product:session:sess-alpha:message:m-001` (found).
- Linear case expected prefix: `linear:issue:OPS-123` (not found).
- Twenty case expected prefix: `twenty:company:company-alpha` (not found).

Source/retrieval counts at proof time:

```text
source_records counts:
google_drive/document=102
linear/message=395
linear/person=10
linear/project=2
linear/resource=2
linear/work_item=649
openviking/message=5029
slack/message=1
slack/person=12
slack/relationship=15
slack/work_item=4
twenty/organization=806
twenty/person=717
retrieval_records=7888
```

Safety notes:

- Permission gating check executed on Slack query token `dev-jules-codex-auth-e2e-20260610-1059`
  with `slack:channel:C0ASNARACMT`:
  - with role: 1 evidence item from
    `slack:message:C0ASNARACMT:1781089083.931829`.
  - without role: 0 evidence items.
- `search-state` artifacts were not persisted to avoid raw message/document body capture.


## 2026-06-11 Stage 1 one-command acceptance closure

Commit under test: `c6710ad feat(runtime): add stage1 acceptance gate`.

Final restart/rebuild proof:

```bash
uv run fourok-dev app-up
uv run fourok-dev pipeline-up
uv run fourok-dev observability-up
FOUR_OK_IMAGE_TAG=$(git rev-parse --short HEAD) \
  docker compose --profile observability up --build --force-recreate -d \
  fourok-metrics-exporter promtail
uv run fourok stage1-acceptance --json \
  --report reports/stage1-acceptance-live-retrieval.md
```

Result summary:

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
  "resume": {
    "blockers": [],
    "last_verification": "uv run fourok stage1-acceptance --json",
    "next_command": "Start Stage 2 OpenClaw plugin before-prompt RAG summary.",
    "open_gates": []
  }
}
```

Live retrieval case-set result:

```text
status=ok; cases=5; passed=5; failed=0
```

Covered current runtime refs:

- Slack: `slack:message:C0ASNARACMT:1781089083.931829`
- Google Drive: `google_drive:file:1OxsH8MoJYVtudzlNFfJvRUSoXajH0urTBcn46HP_qXw`
- OpenViking: `openviking:conversation:b63d391a-27fa-4165-a5fe-4da648b01409-topic-1781095303.717729:session:b63d391a-27fa-4165-a5fe-4da648b01409-topic-1781095303.717729:message:9b12b014`
- Linear: `linear:issue:4OK-697`
- Twenty: `twenty:person:8878cbe4-761c-4183-9817-15e4539e3c8a`

Focused regression proof:

```text
uv run pytest tests/runtime/test_stage1_acceptance.py \
  tests/test_live_retrieval_case_set.py tests/runtime/test_acceptance.py -q
7 passed
```

Commit-hook proof during `c6710ad`:

```text
format/lint passed
139 tracked tests passed
7 focused tests passed
```
