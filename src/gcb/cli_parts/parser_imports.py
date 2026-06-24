from __future__ import annotations

import os
from pathlib import Path

from gcb.cli_parts.shared import DEFAULT_STATE, StoreExplicitState


def add_import_commands(subparsers) -> None:
    land_singer_parser = subparsers.add_parser(
        "land-singer",
        help="Land Singer RECORD messages as raw stream JSONL files.",
    )
    land_singer_parser.add_argument("singer_file", type=Path)
    land_singer_parser.add_argument(
        "--landing-dir",
        type=Path,
        default=Path(".local/raw/singer"),
        help="Project-local raw landing directory.",
    )

    ingest_gmail_singer_parser = subparsers.add_parser(
        "ingest-gmail-singer",
        help="Ingest adapted Gmail Singer messages records into governed state.",
    )
    ingest_gmail_singer_parser.add_argument("singer_file", type=Path)
    ingest_gmail_singer_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ingest_gmail_singer_parser.add_argument(
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )
    ingest_gmail_singer_parser.add_argument("--config", type=Path)

    ingest_pdf_parser = subparsers.add_parser(
        "ingest-pdf",
        help="Ingest a text-layer PDF as a Document source record. OCR is not supported.",
    )
    ingest_pdf_parser.add_argument("pdf_file", type=Path)
    ingest_pdf_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ingest_pdf_parser.add_argument("--database-url", default=os.environ.get("GCB_DATABASE_URL"))
    ingest_pdf_parser.add_argument("--config", type=Path)
    ingest_pdf_parser.add_argument(
        "--landing-dir",
        type=Path,
        default=Path(".local/raw/pdf"),
        help="Project-local directory for landed raw PDF bytes.",
    )
    ingest_pdf_parser.add_argument("--source-system", default="pdf")
    ingest_pdf_parser.add_argument("--source-id")
    ingest_pdf_parser.add_argument("--source-ref")
    ingest_pdf_parser.add_argument("--source-url", default="")
    ingest_pdf_parser.add_argument("--permission-ref", action="append", default=[])

    backfill_openviking_parser = subparsers.add_parser(
        "backfill-openviking-messages",
        help="Backfill OpenViking messages.jsonl captured conversations into governed state.",
    )
    backfill_openviking_parser.add_argument("messages_file", type=Path)
    backfill_openviking_parser.set_defaults(state_explicit=False)
    backfill_openviking_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        action=StoreExplicitState,
    )
    backfill_openviking_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to GCB_DATABASE_URL unless --state is explicit.",
    )
    backfill_openviking_parser.add_argument("--config", type=Path)

    import_context_fixture_parser = subparsers.add_parser(
        "import-context-fixture",
        help="Import a test-only deterministic context snapshot into governed state.",
        description="Import a test-only deterministic context snapshot into governed state.",
    )
    import_context_fixture_parser.add_argument("--fixture", type=Path, required=True)
    import_context_fixture_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    import_context_fixture_parser.add_argument(
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )
    import_context_fixture_parser.add_argument("--config", type=Path)

    prepare_seed_parser = subparsers.add_parser(
        "prepare-seed-snapshot",
        help="Validate and copy a context snapshot into a project-local ignored seed path.",
    )
    prepare_seed_parser.add_argument("--input", type=Path, required=True)
    prepare_seed_parser.add_argument(
        "--output",
        type=Path,
        default=Path(".local/seeds/context-snapshot.json"),
        help="Seed snapshot output path. Must be under .local/.",
    )

    run_imports_parser = subparsers.add_parser(
        "run-imports",
        help="Run one scheduler-safe import job through the governed import pipeline.",
        description=(
            "Run one scheduler-safe import job through the governed import pipeline; "
            "context-fixture is regression-only."
        ),
    )
    run_imports_parser.add_argument(
        "--connector",
        required=True,
        choices=("context-fixture", "gmail-singer"),
        help=(
            "Import connector to run; gmail-singer is the internal path, "
            "context-fixture is regression-only."
        ),
    )
    run_imports_parser.add_argument(
        "--fixture",
        type=Path,
        help="Test-only context snapshot fixture for --connector context-fixture.",
    )
    run_imports_parser.add_argument(
        "--singer-file",
        type=Path,
        help="Singer JSONL file for --connector gmail-singer.",
    )
    run_imports_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    run_imports_parser.add_argument("--database-url", default=os.environ.get("GCB_DATABASE_URL"))
    run_imports_parser.add_argument("--config", type=Path)
    run_imports_parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Only run when the latest failed job is due for retry.",
    )
    run_imports_parser.add_argument("--retry-base-delay-seconds", type=int)
    run_imports_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic scheduler checks.",
    )

    run_live_ingestion_parser = subparsers.add_parser(
        "run-live-ingestion",
        help="Run one hourly-safe live backfill for Twenty, Slack, Linear, and Drive.",
        description=(
            "Run one hourly-safe live Dagster connector backfill and record source "
            "freshness/idempotency status."
        ),
    )
    run_live_ingestion_parser.add_argument(
        "--source",
        action="append",
        choices=("all", "twenty", "slack", "linear", "google_drive"),
        default=[],
        help="Live source to run. Repeat for multiple sources; default is all.",
    )
    run_live_ingestion_parser.set_defaults(state_explicit=False)
    run_live_ingestion_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        action=StoreExplicitState,
    )
    run_live_ingestion_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to GCB_DATABASE_URL unless --state is explicit.",
    )
    run_live_ingestion_parser.add_argument("--config", type=Path)
    run_live_ingestion_parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".local/recurring-live-ingestion"),
        help="Ignored project-local artifact root for live materialization proofs.",
    )
    run_live_ingestion_parser.add_argument(
        "--verify-live-db",
        action="store_true",
        help="Require GCB_DATABASE_URL and verify live DB row deltas.",
    )
    run_live_ingestion_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic scheduler checks.",
    )

    live_ingestion_status_parser = subparsers.add_parser(
        "live-ingestion-status",
        help="Print recurring live ingestion freshness and idempotency status.",
    )
    live_ingestion_status_parser.set_defaults(state_explicit=False)
    live_ingestion_status_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        action=StoreExplicitState,
    )
    live_ingestion_status_parser.add_argument(
        "--database-url",
        help="SQLAlchemy database URL. Defaults to GCB_DATABASE_URL unless --state is explicit.",
    )
    live_ingestion_status_parser.add_argument("--config", type=Path)
    live_ingestion_status_parser.add_argument(
        "--stale-after-minutes",
        type=int,
        help="Freshness window before a succeeded source is reported stale.",
    )
    live_ingestion_status_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic status checks.",
    )

    connector_checkpoint_parser = subparsers.add_parser(
        "connector-checkpoint",
        help="Print the latest stored connector checkpoint.",
    )
    connector_checkpoint_parser.add_argument("connector_name")
    connector_checkpoint_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    connector_checkpoint_parser.add_argument(
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )

    connector_jobs_parser = subparsers.add_parser(
        "connector-jobs",
        help="Print stored connector job runs.",
    )
    connector_jobs_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    connector_jobs_parser.add_argument("--database-url", default=os.environ.get("GCB_DATABASE_URL"))
    connector_jobs_parser.add_argument("--connector-name")
