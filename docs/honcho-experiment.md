# Honcho Experiment Runbook

Status: historical/deferred experiment.

Purpose: run the internal Linear + Slack-identity Honcho experiment using
env/.env-backed source credentials and an externally supplied Honcho service.
The project Docker Compose file no longer starts Honcho; active Compose is kept
focused on the GCB runtime.

This path is internal-only. It intentionally excludes governance, PII masking,
tokenization, reveal policy, and Slack message ingestion.

## Prerequisites

- Docker engine available
- external secret manager machine identity in the environment
- source secrets available in external secret manager:
  - `LINEAR_API_KEY`
  - `SLACK_BOT_TOKEN`
  - `TWENTY_API_KEY`

Set runtime environment without printing secret values:

```bash
export HONCHO_WORKSPACE_ID="gcb-internal"
export HONCHO_SYNC_SOURCES="linear,slack"
export HONCHO_SOURCE_LIMIT="20"
export HONCHO_CATALOG_LIMIT="100"
export HONCHO_CHECKPOINT_OVERLAP_MINUTES="5"
```

Use `HONCHO_SYNC_SOURCES=linear,twenty,slack` only after Twenty preflight is
confirmed from the runtime network.

## Bring-Up

Validate Compose config:

```bash
GCB_IMAGE_TAG=$(git rev-parse --short HEAD) \
POSTGRES_PASSWORD=local-check \
GCB_DATABASE_URL=postgresql+psycopg://gcb:local-check@postgres:5432/gcb \
docker compose config >/dev/null
```

Build the app image and start only the active GCB dependencies:

```bash
docker compose build app
docker compose up -d postgres
```

Provide `HONCHO_URL` from a separately managed local or remote Honcho runtime.

Run source preflight without printing secrets:

```bash
docker compose run --rm app \
  honcho-preflight \
    --check-sources \
    --sources "$HONCHO_SYNC_SOURCES"
```

Run a bounded summary dry-run first:

```bash
docker compose run --rm app \
  honcho-sync \
    --dry-run \
    --summary-only \
    --live-sources \
    --sources "$HONCHO_SYNC_SOURCES" \
    --source-limit "$HONCHO_SOURCE_LIMIT" \
    --catalog-limit "$HONCHO_CATALOG_LIMIT" \
    --state /app/.local/honcho-sync-state.json
```

Start the app once to write new or changed Linear records:

```bash
docker compose run --rm app
```

Or run the long-lived app service:

```bash
docker compose up -d app
```

Inspect one write receipt:

```bash
docker compose run --rm app \
  honcho-receipt "linear:issue:<identifier>" \
    --state /app/.local/honcho-sync-state.json
```

Run fixture smoke readback against local Honcho:

```bash
docker compose run --rm app \
  honcho-smoke \
    --fixture fixtures/honcho/linear_twenty_slack_sample.json \
    --honcho-url "$HONCHO_URL" \
    --workspace-id "$HONCHO_WORKSPACE_ID" \
    --require
```

The smoke output includes `source_ref_readback` and `source_ref_search`. Local
test runtimes may disable Honcho message embeddings so workspace search uses
full-text search and does not require embedding provider credentials.
`--require` gates on readback.

Run a retrieval-quality check against local Honcho:

```bash
uv run gcb honcho-eval \
  --cases .local/honcho-retrieval-eval.json \
  --honcho-url "$HONCHO_URL" \
  --workspace-id "$HONCHO_WORKSPACE_ID" \
  --limit 5
```

The cases file is an ignored JSON list. Each case needs a `query` and may
include `expected_source_refs`, `peer_id`, `session_id`, and `filters`.
Workspace search is used by default; `peer_id` or `session_id` scopes the query
to the matching Honcho endpoint.

## Day 2 Behavior

Each `honcho-sync` run:

- refreshes selected identity/catalog sources before planning Linear writes
- applies `HONCHO_SOURCE_LIMIT` to Linear issues/comments and
  `HONCHO_CATALOG_LIMIT` to identity/catalog records
- stores refreshed source import records by stable source ref
- uses the stored Linear checkpoint with overlap for live deltas
- skips unchanged source refs
- writes newer changed source refs as superseding Honcho events
- marks the previous Honcho message metadata as `source_status=superseded`
- advances the source-ref receipt after each successful write
- keeps state in `.local/honcho-sync-state.json`

Changed records append a new Honcho event because the local Honcho API creates
messages with server ids. Old message content remains in Honcho, but the
previous message is metadata-marked as superseded for tools that support
metadata filtering.

## Current Limits

- Twenty uses REST `/rest/workspaceMembers` for Iteration 1 because the same
  key works against REST while GraphQL returns Cloudflare `1010` from this
  environment.
- This experiment does not run on a schedule yet. Use a host scheduler only
  after deciding non-overlap/lock behavior.
