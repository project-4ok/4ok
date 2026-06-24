# Changelog

Completed implementation history and accepted decisions. The active work that
still needs to be done lives in [docs/plan.md](docs/plan.md).

## 2026-06-05

### Honcho Linear, Twenty, and Slack Identity Experiment

- Added Docker Compose runtime for the Honcho experiment with PostgreSQL,
  Cerbos, Honcho, Honcho Postgres/Redis, and the Python app container.
- Added `gcb honcho-preflight`, `gcb honcho-sync`, `gcb honcho-smoke`, and
  `gcb honcho-receipt` for local operation and verification.
- Wired Infisical SDK machine-identity auth into the app container and fixed
  Honcho preflight to use the same Infisical environment defaults as sync.
- Added bounded live source collection for Linear, Twenty workspace members,
  and Slack user identity.
- Added email-based employee linking across Twenty workspace members, Linear
  users, and Slack users.
- Routed Linear issues and comments to OpenClaw-compatible Slack-derived
  Honcho peer ids when a matched employee exists.
- Added aggregate Linear team fallback peers when deterministic employee
  routing is not available.
- Added source-ref based Honcho idempotency, write receipts, source imports,
  catalog refresh state, Linear checkpoints, overlap windows, changed-record
  superseding metadata, and receipt inspection.
- Verified local Docker E2E with Infisical-backed live sources:
  preflight passed for Linear, Slack, and Twenty; first bounded sync wrote 4
  Honcho messages; second sync wrote 0 messages and skipped already imported
  source refs.
- Split Honcho event import limits from identity/catalog refresh limits so a
  bounded Linear import no longer truncates employee catalogs.
- Added a `gcb honcho-eval` retrieval-quality harness for workspace, peer, and
  session search checks against expected source refs.
- Recorded that the first Honcho experiment is internal-only and intentionally
  skips governance, PII masking, tokenization, reveal policy, and sensitive
  access audit behavior.

## 2026-05-24

### Connector and OSS Planning

- Added an OSS ownership map for connector/parser/policy/search decisions.
- Added a Gmail/Workspace connector pilot checklist.
- Added `scripts/run_gmail_pilot.py` to fetch Gmail pilot credentials from
  Infisical or an ignored local fallback, validate required settings, and
  capture raw tap output without printing secret values.
- Added Gmail pilot preflight handling for environment-based Infisical metadata
  and Infisical credential source errors.
- Replaced the first Infisical CLI shell-out with a reusable
  `gcb.secrets.infisical` provider backed by the official `infisicalsdk`
  package.
- Added `scripts/inspect_gmail_pilot_output.py` to summarize raw Singer output
  shape without printing email body, attachment body, or secret values.
- Added `--inspect-output` to the Gmail pilot runner so a successful tap run can
  immediately write the redacted output inspection summary.
- Added pass/warning/fail inspection checks for Gmail pilot raw output so real
  connector output can be evaluated against source-record readiness criteria.
- Added a conservative Gmail raw-record adapter that maps likely Gmail/tap
  fields into `SourceRecord` and restricts records by default when permission
  snapshots are missing.
- Added a pre-production infrastructure gate to the active plan: validate real
  connector behavior, ETL triggering/checkpointing, document extraction,
  identity/groups, policy, demo workflow, and operations requirements before
  detailed production infrastructure design.
- Added a local Meltano/Singer fixture boundary with `tap-gcb-fixture`,
  `target-gcb-raw-jsonl`, and `meltano.yml`.
- Added Singer raw landing and adapter support for source records.
- Added connector permission snapshot semantics:
  `missing`, `stale`, and `revoked` restrict retrieval.
- Added source-record support for source URLs, thread refs, permission refs,
  permission snapshot status, attachments, lifecycle state, and source
  identities.

### Document Extraction

- Added optional Docling adapter boundary in `gcb.etl.extract.document_extraction`.
- Added `scripts/evaluate_document_extraction.py` for ignored synthetic
  Markdown/HTML/DOCX/PPTX/PDF smoke fixtures.
- Added a containerized Docling worker experiment service that keeps Docling
  outside the default project runtime.
- Recorded that the first ephemeral Docling install attempt had a large
  Torch/CUDA/OCR dependency footprint before conversion began.
- Updated the plan to require Docker/containerized evaluation for heavy
  optional OSS dependencies before adding them to the default runtime.

### Governance Refactor

- Split governance concerns out of the former large context implementation:
  audit, permissions, token-store helpers, state setup, lifecycle, reveal,
  source metadata, and indexing now live in focused governance modules.
- Kept `GovernedContext` as the public facade.
- Removed old flat import shims after internal imports and tests migrated.
- Added focused tests around the extracted governance modules.

### Storage, Lifecycle, and Runtime

- Added SQLAlchemy-backed connector job-run and connector checkpoint tables as
  the first ETL execution-state boundary.
- Wired the Gmail pilot runner to optionally record job runs and persist the
  latest Singer `STATE` message as the connector checkpoint.
- Wired the Gmail pilot runner to pass stored connector checkpoints back into
  SDK-based Singer taps with `--state` on reruns.
- Added read-only CLI inspection commands for connector checkpoints and job
  history.
- Added explicit raw-source store backend selection with filesystem support.
- Added config-backed restricted raw-source retention purge.
- Added timestamped audit events plus config-backed audit retention purge.
- Added `gcb audit-summary` for basic audit activity counts.
- Added SQLAlchemy database URL configuration and PostgreSQL-compatible state
  paths.
- Added local Docker Compose services for PostgreSQL and Cerbos.
- Added `scripts/smoke_runtime.py` for local runtime validation.
- Added local SQLite backup/restore commands for prototype state.
- Added `gcb health` for database/schema and filesystem raw-store readiness
  checks.
- Added `gcb postgres-backup`, `gcb postgres-restore`, and the PostgreSQL
  backup/restore drill doc.
- Added `gcb runtime-services` to make the current service/worker boundaries
  and deferred broker decision inspectable.

### Retrieval and Policy

- Added an explicit two-method agent tool facade for `search_context` and
  `request_reveal`.
- Added deterministic token ids derived from token type and normalized value.
- Added PostgreSQL full-text search path and pgvector experiment support.
- Added retrieval quality evaluation with keyword, vector, and hybrid methods.
- Added trusted identity-claim mapping into `PrincipalContext` for future
  SSO-backed human and agent contexts.
- Added principal-aware search/reveal audit records with human and agent ids.
- Added static reveal policy and Cerbos HTTP adapter.
- Added Cerbos policy/config for IBAN reveal with `payment_processing`.
- Added `source_access` audit events for permission-checked source metadata
  lookups.

### PII, Address, NLP, and Entity Experiments

- Added Presidio-backed PII detection with narrow custom recognizers.
- Added optional English spaCy model experiment.
- Added narrow address recognizer baseline and address-extraction decision doc.
- Added manually labeled local Enron PII evaluation summary.
- Added source identity storage for connector-derived records.
- Added multi-source identity fixture, exact-email baseline, alias baseline,
  Splink probability experiment, and ER tool comparison.

### Code Organization

- Moved source modules into clearer package boundaries:
  `extract`, `transform`, `retrieval`, `storage`, `governance`, and
  `workflows`.
- Moved tests to mirror the `src/gcb` package structure.
- Fixed refactor-era documentation paths.

## 2026-05-23

### Documentation Baseline

- Framed the product as governed context infrastructure, not generic agent
  memory.
- Accepted the minimal agent tool surface:
  `search_context(query)` and `request_reveal(token, purpose)`.
- Deferred `read_source`, `record_decision`, and canonical entity resolution for
  minimal v1.
- Added project engineering rules in [AGENTS.md](AGENTS.md).
- Approved Python tooling choices: pytest, ruff, and hatchling.
- Approved SQLAlchemy Core for storage/query construction.
- Approved `.local/` as the project-local ignored scratch location instead of
  `/tmp`.

### Local Search and Enron Smoke

- Added synthetic email fixtures and local email parsing.
- Added stable `local_email:*` source refs.
- Added source-linked keyword search and CLI output.
- Added local Enron maildir smoke loading with malformed-file reporting and
  HTML fallback parsing.
- Validated that source-linked keyword search was the cheapest first product
  test.
