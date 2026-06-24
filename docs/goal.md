# Goal: Deploy GCB Runtime and CLI for Internal Agent Use

Source code and executable tests are truth; this file tracks only current gates.

## Current Gates

- [x] Refresh the approved live retrieval case set so Slack, Google Drive,
  OpenViking, Linear, and Twenty cases match current runtime source refs.
  Proof: `uv run gcb live-retrieval-case-set ...` returns `status=ok`.
- [x] Add one Stage 1 acceptance command with JSON pass/fail output.
  Proof: `uv run gcb stage1-acceptance --json` exits 0 locally and reports
  health, retrieval, permission, Dagster, and Grafana checks.
- [x] Prove Grafana/Dagster freshness and canonical dashboard state.
  Proof: `reports/2026-06-11-stage1-final-runtime-proof.md` records successful
  run `c28e9004-fe3c-46b8-b346-8abcc31d7a33`, all required Dagster steps
  successful, dashboard `gcb-local-runtime-logs`, and Grafana hourly-backfill
  freshness at ~0.34m.
- [x] Improve DX/AX resume state.
  Proof: one command or concise state file shows open gates, last verification,
  blockers, and next command for a fresh Hermes/Codex session.
- [x] Complete only behavior-preserving refactors that reduce Stage 1
  verification cost.
  Proof: focused regression tests and `git diff --check`.
- [x] Fix the Stage 1 acceptance/check commands so they cannot pass while Dagster
  still has current failures or stale hourly backfills.
  Proof: `83dddde` adds Dagster `runtime_status`; `uv run gcb stage1-acceptance
  --json` now fails on current run failures, failed/incomplete required steps, or
  stale hourly success freshness, and passed after successful run
  `c28e9004-fe3c-46b8-b346-8abcc31d7a33`.
- [x] Run final end-to-end restart proof.
  Proof through local evidence is complete in
  `reports/2026-06-11-stage1-final-runtime-proof.md`; final git proof is
  `git status --short --branch` after push.
- [x] Ship a low-effort `gcb retrieve` MVP for agent-usable retrieval
  augmentation blocks.
  Proof: `uv run pytest tests/retrieval/test_retrieve_cli.py -q` and live smoke
  `uv run gcb retrieve "Coaches fintech partnerships" --database-url <local-db>
  --limit 3` return source-backed excerpts.
- [ ] Make the GCB CLI installable standalone for the internal agent runtime.
  Proof: a clean Python 3.13 environment or pinned runtime image installs GCB
  from a durable artifact/ref and `gcb --help` lists `retrieve` without a source
  checkout.
- [ ] Publish/pin deployable GCB runtime artifacts.
  Proof: app, Dagster code/runtime, and CLI artifacts are pinned by digest/SHA;
  no deployment path depends on `latest` or an uncommitted local build.
- [ ] Add GCB pipeline/runtime deployment to the 4OK infrastructure repo.
  Proof: dev gateway/runtime assets can deploy Postgres/pgvector, GCB app,
  Dagster webserver/code/daemon, metrics/exporter, and Grafana/LGTM-equivalent
  observability with secrets resolved through Infisical.
- [ ] Install the standalone `gcb` CLI in the 4OK dev internal-agent image.
  Proof: inside the dev OpenClaw/internal-agent container, `gcb --help` includes
  `retrieve` and `gcb retrieve <known-query>` can reach the deployed dev GCB DB.
- [ ] Add internal-agent usage guidance in 4OK infrastructure repo.
  Proof: a GCB `SKILL.md` and workspace `TOOLS.md` tell the agent when to use
  `gcb retrieve`, include safe example commands, and document limitations.
- [ ] Deploy to the 4OK development environment and verify end to end.
  Proof: the dev GitHub Actions build/deploy succeeds, runtime containers are
  healthy, Dagster/Grafana are usable, and the internal agent uses `gcb retrieve`
  for a real source-backed question without plugin wiring.

## Resume Blockers

None.

## Product-Value Exit

Internal-agent use is a deployment problem, not a plugin-hook problem. The next
slice is: publish/pin GCB runtime artifacts, deploy the GCB pipeline/runtime in
the 4OK dev environment, install standalone `gcb` in the internal-agent image,
and teach the agent through SkillMD/ToolsMD when to call `gcb retrieve`.

## Operating Rules

- Keep this file under 100 lines.
- Do not add completed proof history here; put evidence in `reports/`.
- Do not duplicate implemented behavior; link to code/tests or the owning command.
- Use Codex only for large or parallel independent implementation slices.
- Prefer direct Hermes edits for small changes, tests, docs, glue, and live
  verification loops.

## Done Means

- [x] Approved live retrieval case set passes against the local runtime.
- [x] `uv run gcb stage1-acceptance --json` is the one local Stage 1 pass/fail
  command.
- [x] Corrected acceptance/check commands fail when Dagster has current failures
  or stale hourly-backfill freshness, and pass only after a successful required
  Dagster run/materialization within the hourly SLA.
- [x] Grafana/Dagster freshness proof prevents stale-dashboard conclusions,
  includes one successful Dagster run/materialization after rebuild, and shows
  `[Pipeline] Minutes since successful hourly backfill` within the hourly SLA.
- [x] End-to-end local proof survives rebuild/restart.
- [x] All goal commits are pushed; repo has no uncommitted work and no local-ahead
  commits.
- [ ] Standalone `gcb retrieve` is installed in the 4OK dev internal-agent
  container and can reach the deployed dev GCB runtime.
- [ ] 4OK infra `SKILL.md`/`TOOLS.md` guidance causes the internal agent to use
  `gcb retrieve` for source-backed company-context questions.
- [ ] Dev deployment proof covers GCB pipeline, Dagster, Grafana/observability,
  runtime health, and one real retrieval from the internal-agent container.
