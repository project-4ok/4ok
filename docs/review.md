# Review Log

Append audit-relevant open questions here. Keep this file short.

## Phase 6.5 Maintainability And Complexity Review (2026-06-10)

- Completed: reviewed touched ingestion/retrieval/observability/runtime/devtool surfaces
  and found no Stage 1 blockers; all findings are now recorded here with clear deferrals.
- Blocking now? No. `python`-line overage check uses 800-line threshold and no files
  exceed this threshold in `src/` or `tests/` (`src/gcb/devtools/dev.py` is 761 lines
  and `src/gcb/etl/extract/connectors.py` is 686, both below threshold) while still
  showing high coupling candidates for a future slice.
- Blocking for Stage 1 (deferred): no safe, high-leverage code cleanup was identified
  this pass; replacing the currently intentional broad exception paths would require
  a dedicated behavior contract update before we can prove no-op equivalence.
- Deferred cleanup: extract shared connector tap pagination/transport helpers across
  `src/gcb/etl/extract/*_tap.py` to reduce duplication in future slices; expected
  benefit is reduced surface for adapter bugs and easier fixture/cold-path testing.
- Deferred cleanup: centralize repeated container compose command wiring seen in
  `src/gcb/runtime/operator_live.py` and `src/gcb/devtools/dev.py`; expected benefit
  is fewer drift bugs in operator bootstrap/Dev tool command paths and shorter operator
  onboarding.
- Implemented? No behavior changes; all maintenance actions are documentation-only in
  this slice.
- Evidence/operator benefit: `rg -n "except Exception"` confirms narrow but repeated broad
  handling in `google_drive_tap.py`, `linear_tap.py`, `twenty_tap.py`, and
  `metrics_exporter.py`; this is now an explicit risk in docs with no Stage 1 test
  contract impact today.

## Open Items

- Gmail pilot follow-up: current pilot validated source refs, generated review
  URLs, and Singer state, but attachment-bearing samples and Workspace/group
  permission mapping still need validation.
- Connector execution: decide scheduler, retry/backoff behavior, lock/lease
  strategy, and whether any broker is needed.
- Identity: choose Keycloak or authentik; define how human and agent identity,
  groups, and trusted claims enter `PrincipalContext`.
- Policy: confirm Cerbos is enough for v1 reveal/source-access policy before
  introducing OpenFGA.
- Raw source storage: choose production object storage, encryption, deletion,
  and retention behavior.
- Internal v0 retention/deletion policy: raw-source, audit-event, terminal
  webhook backlog, and backup purge paths exist; source records and retrieval
  units have lifecycle/status retention visibility. Define final telemetry
  retention and production deletion guarantees before relying on real internal
  data long term.
- PostgreSQL operations: live local restore drill passed on 2026-06-07 with
  app image `9ae4026`; nightly systemd backup timer template and local backup
  retention purge exist. Decide backup encryption, off-host copy, and incident
  procedure.
- Production migration discipline: define schema/data migration rules and
  deploy cutover expectations later. Do not build rollback or legacy-support
  machinery while the product is still in fast internal development.
- Local PostgreSQL volume: Compose Postgres reports a collation-version
  mismatch on database create/drop. Refresh or recreate the local volume before
  relying on local restore-drill results.
- Document extraction: validate Docling in an isolated container against
  representative attachments before adding it to the default runtime.
- PII/NLP quality: expand labeled evaluation data before making production
  claims about names, addresses, or sensitive-category filtering.
- Entity resolution: keep source identities inspectable; revisit canonical
  entities only after multiple real sources exist.
- Human review workflow: define a later annotation/review/correction path for
  disputed entity links, evidence quality, retention decisions, production
  policy, and ingestion mistakes. It should preserve evidence, correction
  reason, reviewer identity, and audit history. Do not build this during the
  current internal-v0 implementation goal.
- Infisical SDK: confirm license/dependency footprint before productionizing
  in-process secret access.
- Infisical self-hosting: confirm `INFISICAL_API_URL` / host conventions and
  accepted universal-auth env names stay aligned across Hermes and production
  bootstrap.
- Honcho runtime: current Compose builds Honcho from the ignored local
  `.reference/honcho` checkout; choose a pinned image or tracked source strategy
  before relying on this deployment outside the internal experiment.
- Honcho live source smoke: Twenty now uses REST because the same API key works
  against `/rest/workspaceMembers` while GraphQL returns Cloudflare `1010`.
  Revisit GraphQL only if batch relation traversal becomes necessary.
- Honcho source-ref upserts: changed source refs append a superseding event and
  metadata-mark the previous Honcho message as superseded. Confirm whether
  production agents can reliably filter superseded metadata or need physical
  compaction.
- Honcho entity catalog: Slack email changes move the active peer mapping, but
  source identity history is still a flat list. Decide whether production needs
  explicit active vs historical identity records.
- Graphiti ingestion path: packaged REST `/messages` only accepts
  conversation-style messages and does not expose the full source metadata
  contract needed for source refs, timestamps, and filtering. The Python
  `add_episode` and `add_episode_bulk` paths also do not pass
  `episode_metadata` into `EpisodicNode` despite the model having that field.
  For the experiment, source refs must be encoded into uuid/name/body or we must
  patch/wrap Graphiti/write episodic nodes ourselves.
- Local observability: OpenTelemetry/Grafana LGTM is approved for local
  debugging only. Before exporting telemetry outside localhost, define and test
  collector-side redaction for PII, raw source text, connector payloads, and
  secrets-adjacent attributes.
- App image/runbook alignment: the slim `app` image currently installs the
  `gcb` CLI and fixture data, but older internal-prod Gmail steps reference
  repository scripts. Decide whether production images should include those
  scripts or the runbook should use dedicated worker images.
- Operator live ingestion: `gcb-dev operator-live --dry-run` is proven locally,
  but this worktree has no `.env` or Infisical source settings and no running
  local Dagster services. Run the actual live command against a credentialed
  local environment before treating live SaaS ingestion as operationally
  verified.
- GCB MCP retrieval: handler and SDK registration tests cover the local
  contract, but Hermes has not yet connected to `uv run gcb-mcp` against the
  runtime database. Run the Hermes stdio integration and compare `search_gcb`
  with `gcb search-state` before treating the server as operationally verified.
- Grafana-first runtime state: the dashboard now includes log-derived runtime
  service activity and recent error panels, but it still does not query Docker
  health status directly. Exact container health remains a Docker/Dagster
  drilldown until a safe Docker-health metric source is added to the local
  observability profile.
- Grafana provisioning drift: during the 2026-06-10 Grafana-first slice, the
  running local Grafana served an older provisioned dashboard after provisioning
  reload, indicating it was mounted from a different checkout or stale runtime
  state. Rebuild/restart the observability profile from this branch before
  treating the canonical `gcb-local-runtime-logs` UID as live-updated.
- Live retrieval case-set proof gap: runtime run of the approved case set returns
  one pass (`openviking-launch-checklist`) and four failures (Slack, Drive,
  Linear, Twenty) due stale source-ref/text assumptions, so this remains a
  functional blocker until the fixture and/or runtime source assumptions are
  refreshed.

## Approved

- Python tooling: `pytest`, `ruff`, `hatchling`, `uv`.
- SQLAlchemy Core for storage/query construction.
- `.local/` as ignored project scratch space.
- OpenTelemetry plus Grafana LGTM for local debugging telemetry.
- Deterministic token ids.
- Temporary internal agent tool surface: `search_context` only.
- PostgreSQL plus pgvector as current production database direction.
