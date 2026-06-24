# fourok local runtime, observability, import counts, and MCP retrieval goal

Use this file as the authoritative implementation prompt for the next Hermes `/goal` run. The goal is **not** complete until the real local system is operator-visible and retrieval is testable through an MCP server/tool path.

## Context

- Main repo: `/home/simon/Projects/project-fourok/fourok`
- Worktree root for Codex workers: `/home/simon/Projects/project-fourok/fourok.worktrees`
- Current relevant commits when this prompt was updated: `9c3ea66 feat: add runtime metrics and trace dashboard`, `a23017b chore: aggregate local docker logs in Loki`, `2c9c228 chore: add local runtime dx helpers`
- Local source of truth:
  - Runtime Postgres container: `fourok-postgres-1`
  - Dagster webserver: `http://127.0.0.1:3001`
  - Observability container: `fourok-observability-1`
  - Grafana: `http://127.0.0.1:3000`
  - Loki API: host `http://127.0.0.1:3100`, inside observability container `http://localhost:3100`
  - Tempo API: host `http://127.0.0.1:3200`, inside observability container `http://localhost:3200`
  - fourok local runtime dashboard: `http://127.0.0.1:3000/d/fourok-local-runtime-logs/fourok-local-runtime-logs`
  - fourok metrics exporter: `fourok-metrics-exporter:9108/metrics`, scraped by Prometheus job `fourok-dagster-runtime`
- User preference constraints:
  - Use live connector/data evidence where possible. Do not default to fixture/synthetic data except narrow deterministic regression tests.
  - Do not claim completion from commits/tests alone.
  - Do not edit Hermes source or Hermes runtime state for this project goal.
  - Prefer Codex/worktree orchestration for substantial fourok coding; direct edits are acceptable for small integration/debug fixes when needed.
  - Do not preserve or print credentials. Redact passwords/tokens/API keys as `[REDACTED]`.

## Current state and known gaps

The previous work found and partially fixed real issues. This file was updated after adding local log aggregation and runtime metrics/traces dashboard support.

1. Dagster schedules/sensors are currently running and the latest inspected `fourok_hourly_live_backfill` run succeeded:
   - Latest inspected successful run ID: `de36c858-93ec-4e2d-9cbb-fe890b21812b`
   - Job: `fourok_hourly_live_backfill`
   - Status: `SUCCESS`
   - Successful steps included all live Meltano raw landing assets, all live source-record conversion assets, `fourok_retrieval_records`, and `fourok_operator_dashboard`.
2. The hourly backfill job includes retrieval rebuild and operator dashboard and uses the in-process executor.
3. Observability is now substantially improved and should be kept green while continuing product implementation:
   - Docker stdout/stderr logs are aggregated by Promtail into Loki with labels including `compose_project`, `compose_service`, and `container_name`.
   - Grafana dashboard `fourok Local Runtime Logs` is provisioned and has Loki, Prometheus, and Tempo panels.
   - `fourok-metrics-exporter` is running and Prometheus target `fourok-dagster-runtime` is `up`.
   - OTLP metrics export was smoke-tested with `fourok_smoke_requests_total`.
4. The Dagster lineage still shows red/unmaterialized assets for non-live/legacy/example assets, including the inspected asset nodes with no latest materialization:
   - `fourok_audit_metadata`
   - `fourok_canonical_objects_and_entity_links`
   - `fourok_golden_retrieval_eval`
   - `fourok_google_drive_source_records_from_raw_landing`
   - `fourok_linear_source_records_from_raw_landing`
   - `fourok_slack_source_records_from_raw_landing`
   - `fourok_source_records_from_raw_landing`
   - `fourok_twenty_source_records_from_raw_landing`
   - `fourok_webhook_backlog`
   These red nodes make the product/operator lineage incomplete even though the live hourly backfill path is partly green. The next implementation effort must either implement/materialize these assets, retire/hide obsolete non-product assets from the main Dagster Definitions, or split demo/fixture assets into a non-default group so the product lineage is green and honest.
5. Operator-visible counts/freshness are still the main product gap:
   - `fourok operator-status`, `fourok-dev logs-status`, the metrics exporter, Grafana panels, and MCP `operator_status` must agree on the same live DB-backed source of truth.
   - Freshness must reflect the latest successful Dagster live backfill or an explicitly documented unified source of truth.
   - The Twenty pagination/truncation bug must not be treated as isolated: audit the Slack, Linear, and Google Drive live extractors for the same class of bug (default limits, API page caps, missing/incorrect pagination cursors, and latest-snapshot vs append-log count semantics), then either add fixes with regressions or document tool-backed proof that each extractor is not affected.
6. MCP retrieval server code/tests exist, but the proof is not strong enough:
   - Google Drive query previously returned results.
   - A quick Slack query previously returned results even without a Slack channel role, so permission gating through the MCP path needs stricter regression coverage and real proof.
   - Linear and Twenty retrieval proofs through the MCP/server path remain required.

## Operating rules

- Start by inspecting current git state, container state, Dagster runs/schedules/sensors, operator status, MCP server code, and observability config. Do not assume the state from this prompt is still current.
- Keep an evidence report updated at:
  - `reports/2026-06-09-local-runtime-observability-mcp-evidence.md`
- The evidence report must include commands run, important outputs/counts, run IDs, URLs/API queries, commit SHAs, failures, and remaining blockers.
- If a gate is blocked, write `NOT COMPLETE` in the report and final response with the exact blocker.
- Treat tests as necessary but insufficient. Every live/runtime/dashboard/MCP claim needs real tool-backed evidence.
- Use project-adjacent Codex worktrees for substantial changes:
  - `/home/simon/Projects/project-fourok/fourok.worktrees/<task-slug>/`
- Keep changes atomic and commit them with conventional commit messages.

## Done means ALL gates below are satisfied

### Gate 1 — Dagster recurring local runtime is actually working

Required proof:

1. `uv run fourok-dev pipeline-up` succeeds from the fourok repo.
2. Dagster GraphQL proves:
   - repository loads successfully,
   - `fourok_hourly_live_backfill_schedule` is `RUNNING`,
   - `fourok_webhook_backlog_sensor` is `RUNNING`,
   - `fourok_hourly_live_backfill` exists,
   - latest manually launched or scheduled `fourok_hourly_live_backfill` run is `SUCCESS`.
3. The successful run includes evidence that live source import assets, `fourok_retrieval_records`, and `fourok_operator_dashboard` actually executed after the live import assets.
4. A regression test prevents the backfill job from excluding retrieval/dashboard or running them before live source imports.
5. If the schedule itself is expected to fire hourly, prove either:
   - a schedule-created run appears after waiting for the next tick, or
   - the schedule tick API/UI reports a successful tick and launched run.

### Gate 1B — Dagster product lineage is green and honest

Required proof:

1. Query Dagster asset nodes after a rebuild/restart and classify every visible asset as one of:
   - product/live asset with a fresh successful materialization,
   - intentionally inactive/demo/fixture asset hidden or separated from the default product lineage,
   - known blocker with explicit reason.
2. The main product Dagster lineage shown to the operator has no unexplained red assets.
3. Specifically address these currently red/unmaterialized assets:
   - `fourok_audit_metadata`
   - `fourok_canonical_objects_and_entity_links`
   - `fourok_golden_retrieval_eval`
   - `fourok_*_source_records_from_raw_landing` non-live variants
   - `fourok_source_records_from_raw_landing`
   - `fourok_webhook_backlog`
4. If the correct product decision is to remove/hide/split obsolete assets rather than implement them, document why and add tests so they do not reappear in the default product Definitions unintentionally.
5. Save before/after asset-node evidence in the evidence report.

### Gate 2 — Operator-visible import counts and freshness work

Required proof:

1. There is an operator command/API/dashboard surface that reports current imported item counts by source for live data:
   - `twenty`
   - `slack`
   - `linear`
   - `google_drive`
2. The counts are backed by the runtime DB, not stale CLI artifacts.
3. Freshness reflects the latest successful Dagster live backfill or an explicitly documented unified source of truth.
4. The operator surface shows:
   - source record totals by source,
   - retrieval record total/status counts,
   - latest successful run/freshness per live source,
   - latest failure if present.
5. Add/keep regression tests for the count/freshness behavior.
6. Investigate every other live extractor for the same failure mode found in Twenty:
   - `slack`
   - `linear`
   - `google_drive`
   Required proof for each extractor:
   - identify its configured default limit and API page-size behavior,
   - verify whether it paginates correctly through all live pages or intentionally uses a documented bounded sample,
   - compare live upstream/API totals where available against raw landing/imported active DB counts,
   - add regression tests and fixes for any truncation/missing-pagination bug found,
   - record the outcome in the evidence report.

### Gate 3 — Grafana/Loki/Tempo observability is operator-usable

Required proof:

1. Loki has recent logs for fourok services using a working **range** query, e.g. `{service_name="fourok-dagster-code"}`.
2. Tempo has recent traces for fourok services, e.g. `resource.service.name="fourok-dagster-code"`.
3. Grafana dashboards or documented Explore links/queries let the user see:
   - recent Dagster/code logs,
   - recent traces,
   - current import/retrieval counts or a link/panel to the operator status surface.
4. If existing Grafana dashboards are broken, update or add dashboards/provisioning so the panels work after `uv run fourok-dev pipeline-up`.
5. Add/keep regression/config tests where feasible for dashboard/provisioning/query labels.

### Gate 4 — MCP retrieval server is real and usable by an agent

Required proof:

1. The fourok repo contains an MCP server implementation with tools at least:
   - `search_fourok`
   - `operator_status`
2. Tool schemas are discoverable by tests without launching the full server.
3. The server can be launched via a documented command from the repo, and there is an exact Hermes MCP config snippet or command showing how to wire it as a native MCP server.
4. A real invocation path is tested, preferably one of:
   - an MCP client calling the stdio server, or
   - Hermes native MCP connected to the server, or
   - a documented fallback that exercises the same server tool handlers and explains why full MCP client invocation is blocked.
5. Retrieval proof via MCP/server path includes live DB-backed results for:
   - Google Drive query returning real Google Drive evidence,
   - Linear query returning real Linear evidence,
   - Twenty query returning real Twenty evidence,
   - Slack allowed query returning results with the correct `slack:channel:<id>` role.
6. Slack denied query returns `0` evidence items without the required channel role for the same channel-specific content.
7. Add/keep regression tests for Slack allowed/denied behavior through the MCP handler/tool contract.

### Gate 5 — End-to-end local proof survives restart/rebuild

Required proof:

1. Rebuild/restart the local stack with `uv run fourok-dev pipeline-up` after changes.
2. Run or wait for a fresh live backfill.
3. Verify after restart:
   - Dagster run success,
   - operator counts present and fresh,
   - Loki logs present,
   - Tempo traces present,
   - MCP retrieval works,
   - Slack permission gate works.
4. Save exact command outputs or summarized JSON excerpts in the evidence report.

### Gate 6 — Final reporting is honest and auditable

Final response must include:

- `COMPLETE` only if all gates are satisfied.
- Otherwise `NOT COMPLETE` and the exact remaining blockers.
- Evidence report path.
- Commit SHA(s).
- Key run IDs.
- Verified counts by source.
- Grafana/Loki/Tempo query proof.
- MCP server launch/config instructions.
- MCP retrieval proof summary.

## Not done until

- Every gate above has fresh tool-backed evidence in the evidence report.
- The final response does not imply unverified deployment, data, retrieval, observability, or permission behavior.
- Slack permission gating is proven through the same MCP/server retrieval contract an agent would use.
- Operator-visible counts/freshness reflect the current live backfill source of truth, not stale unrelated artifacts.
