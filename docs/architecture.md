# Architecture

4ok is a source-record-first context layer for a human using
an agent. It is not generic agent memory, and the current internal v0 is not a
GDPR-complete reveal system.

The current product contract is:

- controlled retrieval
- source-backed evidence
- permission and lifecycle filtering before retrieval output
- audit for search and source access

The core architectural rule is:

```text
source records are truth; retrieval units, entity links, summaries, vectors,
and other indexes are derived and rebuildable.
```

## Current Internal Flow

```text
source connector / Meltano/Singer extraction
  -> raw landing
  -> SourceRecord adapter
  -> SourceChange applier
  -> source_records
  -> canonical objects and entity links
  -> retrieval-unit preparation
  -> permission/lifecycle filtered search
  -> evidence pack with related context
  -> audit

webhook event
  -> durable webhook_events backlog
  -> SourceChange applier
  -> same pipeline

text-layer PDF
  -> raw PDF landing
  -> pypdf embedded-text extraction
  -> Document SourceRecord
  -> same pipeline

OpenClaw chat capture
  -> Message SourceRecord
  -> same pipeline
```

Active agent tool:

```text
search_context(query, limit?)
```

No reveal tool, `read_source`, `record_decision`, or entity-resolution tool is
active in this stage.

## Code Layout

The active implementation follows the ETL split:

- `src/gcb/etl/extract`: source connectors, source adapters, raw landing helpers,
  PDF text extraction, and connector job inputs
- `src/gcb/etl/transform`: deferred transformation experiments such as entity
  resolution and PII/tokenization
- `src/gcb/etl/load`: import-pipeline loading behavior for source changes,
  source metadata, context objects, entity links, and retrieval records
- `src/gcb/storage`: persistence and runtime state: ORM models, schema
  compatibility, config, raw store, health checks, schema contract checks, and
  PostgreSQL backup/restore helpers

Governance, retrieval, runtime, secrets, and workflows remain separate because
they are product/control-plane concerns rather than ETL stages.

## Source Records

Every connector adapts source-native data into a stable `SourceRecord`
envelope:

- `source_ref`, `source_system`, and `source_id`
- `record_type`
- title and body/retrieval text
- source URL/path where available
- author, actor, thread, and identity refs
- source timestamps and ingestion/update timestamps
- permission refs and permission snapshot status
- lifecycle state
- checksum/version
- source-specific metadata and raw payload refs

Raw payloads are landed for replay and inspection when available. Agents do not
query raw payloads directly; retrieval resolves back to source records.

## Source Changes

All imports should pass through one source-change boundary.

Supported operations:

- `upsert`
- `restore`
- `restrict`
- `delete`
- `supersede`
- `duplicate`

The applier keeps source records, retrieval units, canonical objects, entity
links, raw refs, lifecycle rows, audit rows, and dashboard-visible state
consistent. The legacy email index tables may still exist in the schema, but
the active source-change import path deletes touched legacy rows instead of
populating them.

## Canonical Objects

Source-specific objects map into a small set of context object types:

- `Person`
- `Organization`
- `Message`
- `Document`
- `WorkItem`
- `Relationship`

The canonical object taxonomy is represented as stored object-type values, not
as a separate domain-object class hierarchy. ORM table definitions live in
`src/gcb/storage/models`.

Keep this taxonomy deliberately small. Source-specific distinctions remain in
`SourceRecord.record_type` and canonical-object metadata:

- projects and issues map to `WorkItem`
- events and chat/email/comments map to `Message`
- generic resources and files map to `Document`

Do not make `Customer`, `Tenant`, `Owner`, or `Supplier` top-level primitives
by default. Model those as roles or relationships on people or organizations
with source-backed evidence.

## Entity Links

Entity linking is a derived layer, not retrieval truth.

Use deterministic links first:

- shared email addresses across Slack, Linear, Twenty, Gmail, and other tools
- source-native user/contact/company ids
- explicit assignee, author, membership, CRM ownership, thread, or project refs

Ambiguous mentions remain candidate links with confidence, reason, and source
evidence. Broader probabilistic/LLM linking is deferred until deterministic
linking and evidence formatting are stable.

## Retrieval Units

`source_records` keep metadata, permissions, lifecycle state, URLs, and source
identity. `retrieval_records` store only derived retrieval units:

- `source_ref`
- unit index
- text offsets
- source checksum
- prepared text
- status
- index kind

Short records stay one unit. Long emails, documents, chat transcripts, and PDF
text are split before indexing. Current defaults are a 900-word window with
100-word overlap; these are configurable and should be tuned with real
retrieval-quality and storage-footprint evidence.

## Retrieval

Retrieval is permission-filtered before evidence-pack assembly.

```text
query
  -> principal context
  -> permission/lifecycle filters
  -> source/type/time/entity filters
  -> keyword/full-text search over retrieval units
  -> optional vector search over retrieval units
  -> source-record join
  -> evidence pack
  -> related-object expansion
  -> audit
```

Evidence packs include:

- query
- result candidates
- source refs and URLs where available
- snippets
- source type and timestamps
- ranking or inclusion reason
- primary objects
- related people, organizations, work items, documents, and threads
- unresolved candidates
- limitations
- audit ref

Related objects are capped and marked as adjacent context, not primary
evidence. Expansion uses explicit source-backed relationships first: same
thread, accepted/candidate entity links, same author/actor, same organization,
same project/work item, and other stored relationship records.

## Storage

Use PostgreSQL as the internal production target and SQLite as the local test
fallback.

PostgreSQL stores the stable relational envelope and `jsonb` for source-specific
metadata:

```text
common across sources -> column
important for joins/filtering -> column
source-specific or unstable -> jsonb
frequently queried jsonb field -> generated column or index
```

Expected indexes:

- unique source identity
- lifecycle and recency
- permission refs
- source-specific metadata
- keyword retrieval
- optional `pgvector` later

OpenSearch is not the system of record. Add it later only as a derived search
accelerator if PostgreSQL full-text search, JSONB indexes, or `pgvector` prove
insufficient.

## Runtime

Internal v0 runs as Docker Compose on one host:

- Python app container
- PostgreSQL
- local observability backend
- persistent volumes
- pinned image references
- env/.env-backed secrets

The next production-readiness release should add Dagster as the pipeline
orchestrator and visual control plane. Dagster owns the asset graph, schedules,
run history, failure visibility, retries, and operator-facing pipeline state.
Meltano/Singer owns batch source extraction where suitable taps exist. GCB owns
raw landing, SourceRecord adapters, source-change application, storage,
retrieval, evidence packs, and audit.

Webhook ingestion uses the database-backed `webhook_events` backlog for
internal v0. A production broker can replace the transport later if volume,
fanout, delayed retries, or backpressure require it.

## Deferred Governance

PII masking, tokenization, and reveal are intentionally not active in the
current runtime. Existing deferred modules such as
`gcb.governance.deferred_reveal_policy`, `gcb.governance.reveal`,
`gcb.governance.token_store`, and `gcb.etl.transform.pii` are experimental and
must not be presented as the current product surface.

Production still needs a defended governance design:

- universal PII/tokenization across all source-record surfaces
- protected identity/token store
- purpose/workflow-aware reveal policy
- field-level reveal authorization
- deletion and retention propagation
- sensitive access audit
- source permission synchronization

Until that design is implemented end to end, agents only get retrieval evidence
from the internal source-record path.

Runtime contracts are defined in [contracts.md](contracts.md).
The implemented flow diagram is in [architecture-flow.md](architecture-flow.md).
Operational commands are in [operations.md](operations.md).
