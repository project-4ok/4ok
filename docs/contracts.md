# Contracts

Small, stable contracts that code and agents should rely on.

## Active Agent Tools

The temporary internal agent-facing surface has one tool.

`search_context(query, limit?)`

- returns permission-filtered source-record evidence
- does not require a purpose
- does not return sensitive token refs or reveal claims
- includes source refs, snippets, confidence/score where available, related
  context, limitations, and audit ref
- returns a stable evidence-pack shape with `query`, `result_candidates`,
  `evidence_items`, `primary_objects`, `related_objects`,
  `related_object_groups`, `entities`, `unresolved_candidates`, `limitations`,
  and `audit_ref`

Deliberately absent in the active internal stage:

- no reveal tool
- no `read_source`
- no `record_decision`
- no entity-resolution tool

## Dependency Contract Spikes

Before an external runtime, SDK, connector family, plugin, or service is wired
into the active pipeline, it needs a small executable contract spike.

Minimum dimensions:

- auth
- read/write shape
- idempotency
- metadata support
- Docker/runtime shape
- failure behavior

The active registry is executable:

```bash
uv run gcb dependency-contracts
```

Current covered dependencies:

- Docker Compose runtime
- PostgreSQL
- env/.env secret loading
- Singer/Meltano-style connector boundary
- text-layer PDF extraction with `pypdf`
- local OpenTelemetry LGTM backend
- OpenClaw plugin boundary

The command reports proof commands for each dependency. A new integration should
not be added to the active runtime until this registry shows which executable
check proves the contract and which dimensions are intentionally out of scope.

Internal-prod readiness is executable too:

```bash
uv run gcb internal-prod-readiness
```

This is a static readiness check. It complements, but does not replace, the
Docker Compose acceptance proof.

## OpenClaw Integration

First-stage OpenClaw integration has two narrow contracts.

Chat capture:

- capture after agent turns and before compaction/reset
- adapt OpenClaw chat messages into `Message` `SourceRecord`s
- use `source_system = "openclaw"`
- use stable source refs shaped like
  `openclaw:session:<session_id>:message:<message_index>`
- preserve session id, agent id, sender id, role, provider, timestamp, and
  message index in metadata
- strip OpenClaw untrusted metadata/control boilerplate from retrieval text
- preserve the raw message payload as raw source material with stable refs
  shaped like `openclaw:session:<session_id>:message:<message_index>:raw`
- import through the same governed SourceRecord pipeline

OpenClaw plugin RAG hook:

- primary product path is not agent-initiated CLI use
- optional and explicitly enabled per OpenClaw runtime or agent
- runs before prompt assembly, after the user turn is known
- retrieves permitted GCB evidence through the in-process/plugin integration or
  internal service boundary, not by asking the agent to call `gcb`
- injects a short source summary into the agent input: source refs, source URLs
  when available, timestamps, limitations, and audit refs
- keeps the injected summary capped and purpose-built for the current user turn;
  no broad context dump
- never injects raw source bodies, secrets, credentials, hidden metadata, or
  reveal-only fields
- preserves the full evidence pack for follow-up inspection instead of
  flattening everything into the prompt
- records which source refs were injected and keeps normal search/source-access
  audit behavior
- can be disabled independently from chat capture and explicit search tools
- does not depend on Honcho, Graphiti, or `.reference` runtime code

Optional explicit tool surface:

`gcb_search_context(query, limit?)`

- returns the same evidence-pack shape as `search_context`
- publish the schema from `openclaw_tool_contracts()`
- dispatch calls through `call_openclaw_tool(...)`
- remains available for follow-up/debugging, but is not the main RAG path
- does not expose reveal

Local plugin package:

- `plugins/openclaw-gcb/openclaw.plugin.json` declares the RAG hook capability
  plus optional `gcb_search_context` and `gcb_health` tools
- `plugins/openclaw-gcb/src/index.ts` registers the hook and optional tools
- the plugin must not use the GCB CLI as the production product path; CLI checks
  are operator/dev smoke equivalents only

## Source Record

Connectors normalize source data into `SourceRecord`.

Required fields:

- `source_ref`: stable source-derived id, not ingestion order
- `source_system`
- `source_id`
- `title`
- `body`
- `created_at`
- `updated_at`

Governance fields:

- `source_url`
- `thread_ref`
- `permission_refs`
- `permission_snapshot_status`
- `attachment_refs`
- `identity_refs`
- `lifecycle_state`

Permission semantics:

- `current`: eligible for retrieval after policy filtering
- `missing`, `stale`, `revoked`: restrict retrieval by default
- connector code preserves source truth; it does not make authorization
  decisions

## Source Changes

Connectors, webhooks, and future schedulers should enter the import pipeline
through source changes, not separate lifecycle paths.

Supported operations:

- `upsert`: store/update source record without overriding an existing inactive
  lifecycle hold
- `restore`: explicitly clear lifecycle hold, store source record, and rebuild
  retrieval visibility
- `restrict`: hide source from retrieval but keep raw/source state for retention
- `delete`: hide source from retrieval and delete raw source object when
  configured
- `supersede`: hide old source ref while preserving lifecycle history
- `duplicate`: hide duplicate source ref while preserving lifecycle history

The applier is responsible for keeping source records, retrieval rows, email
index rows, canonical objects, entity links, raw source refs, lifecycle rows,
and audit events consistent.

## Webhook Events

Webhook ingestion lands source-change events into a durable broker-neutral
backlog before processing. Internal v0 uses the database-backed
`webhook_events` table; a production broker can replace the transport later
without changing the source-change applier.

Event envelope:

- `event_id`: unique source/provider event id
- `source_system`: source name such as `linear`, `slack`, `twenty`,
  `google_drive`, or `openclaw`
- `source_object_id`: source object id when available
- `event_type`: provider event type such as `issue.updated`
- `operation`: `upsert`, `delete`, `restrict`, `restore`, `supersede`, or
  `duplicate`
- `idempotency_key`: stable key for deduplicating retries
- `occurred_at` and `received_at`: source and ingestion timestamps
- `actor_ref`: source actor when available
- `raw_payload_ref`: raw landing ref for the original event payload
- `payload`: JSON object with either `source_record` or a lifecycle
  `source_ref` plus optional `reason`

Processing claims pending events and applies one `SourceChange` through the
governed import pipeline. Successful events become `succeeded`. Transient
processing errors become retryable `pending` events until `max_attempts`, then
`failed`. Permanent payload-shape errors become `invalid` immediately, with
attempt count, error class, and error visibility preserved for operator review.

## Text-Layer PDF Import

PDF import is limited to files that already contain extractable text.

Contract:

- land raw PDF bytes by checksum in a project-local or configured raw directory
- extract text with `pypdf`
- fail clearly when the file is not a PDF or has no text layer
- create a `Document` `SourceRecord`
- store source path/URL, checksum/version, raw ref, content type, and
  `ocr_used=false`
- reuse the governed source-record import pipeline

Deliberately absent in this path:

- no OCR
- no image interpretation
- no table extraction
- no layout reconstruction

## Retrieval Units

`source_records` remain the source of truth. Retrieval preparation creates
derived `retrieval_records` for all active source-record imports.

Unit contract:

- source metadata, permissions, lifecycle state, URL, and evidence identity stay
  on `source_records`
- each retrieval unit stores `source_ref`, `unit_index`, `start_offset`,
  `end_offset`, `source_checksum`, `prepared_text`, `status`, and `index_kind`
- short records remain one unit
- longer records split with the default word window and overlap used by the
  retrieval preparation helper
- source-record updates replace all retrieval units for the touched source ref
- inactive lifecycle changes mark retrieval units inactive

Current defaults:

- target/max window: 900 words
- overlap: 100 words

## Runtime Boundaries

Inspect current runtime boundaries with:

```bash
uv run gcb runtime-services
```

Current boundaries:

- `context-api`: search/source metadata facade
- `connector-runner`: source sync, raw landing, job runs, checkpoints
- `document-extraction-worker`: isolated attachment parsing experiments
- `policy-engine`: static in-process policy only
- `metadata-database`: SQLAlchemy state, PostgreSQL target
- `raw-source-store`: restricted local filesystem now, object storage later
- `secrets-provider`: env/.env secret loading or runtime secret injection
- `audit-store`: PostgreSQL-compatible audit events first

No production broker is chosen yet. Internal v0 should use a durable
broker-neutral event backlog until event volume, fanout, delayed retries, or
backpressure prove a broker is needed.
