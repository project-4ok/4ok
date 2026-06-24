from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fourok.cli_parts.import_helpers import (
    _deleted_snapshot_changes,
    _run_imports,
    _snapshot_source_changes,
    _source_record_import_counts,
)
from fourok.cli_parts.runtime_helpers import (
    _config_from_args,
    _context_state_from_args,
    _governed_context_from_args,
    _optional_datetime,
)
from fourok.etl.extract.connectors import land_singer_records, load_gmail_source_records
from fourok.etl.extract.context_snapshot import load_context_snapshot_source_records
from fourok.etl.extract.document_extraction import DocumentConversionError, pdf_source_record
from fourok.etl.extract.openviking_adapter import load_openviking_messages_jsonl_source_records
from fourok.etl.extract.sync_jobs import connector_checkpoint, connector_job_runs
from fourok.runtime.operator_live import host_database_url
from fourok.runtime.recurring_live_ingestion import (
    live_ingestion_status,
    run_live_ingestion_backfill,
)
from fourok.runtime.seed_snapshots import prepare_context_seed_snapshot
from fourok.runtime.source_imports import import_source_records


def dispatch_import_commands(args: argparse.Namespace) -> bool:
    if args.command == "land-singer":
        report = land_singer_records(args.singer_file, args.landing_dir)
        print(
            json.dumps(
                {
                    "landing_dir": str(args.landing_dir),
                    "record_count": report.record_count,
                    "streams": report.streams,
                    "schema_messages": report.schema_messages,
                    "state_messages": report.state_messages,
                },
                indent=2,
            )
        )
        return True

    if args.command == "ingest-gmail-singer":
        records = load_gmail_source_records(args.singer_file)
        context = _governed_context_from_args(args)
        report = import_source_records(context, records)
        print(
            json.dumps(
                {
                    "input": str(args.singer_file),
                    "record_count": report.record_count,
                    "source_refs": list(report.source_refs),
                    "restricted_count": report.restricted_count,
                },
                indent=2,
            )
        )
        return True

    if args.command == "ingest-pdf":
        try:
            record = pdf_source_record(
                args.pdf_file,
                landing_dir=args.landing_dir,
                source_ref=args.source_ref,
                source_system=args.source_system,
                source_id=args.source_id,
                source_url=args.source_url,
                permission_refs=tuple(args.permission_ref),
            )
        except DocumentConversionError as exc:
            raise SystemExit(str(exc)) from exc
        context = _governed_context_from_args(args)
        import_source_records(context, [record])
        print(
            json.dumps(
                {
                    "input": str(args.pdf_file),
                    "source_ref": record.source_ref,
                    "source_id": record.source_id,
                    "record_type": record.record_type,
                    "checksum": record.checksum,
                    "raw_ref": record.raw_ref,
                    "text_length": len(record.body),
                    "ocr_used": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "backfill-openviking-messages":
        try:
            records = load_openviking_messages_jsonl_source_records(args.messages_file)
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        args.database_url = _database_url_unless_explicit_state(args)
        context = _governed_context_from_args(args)
        report = import_source_records(context, records)
        print(
            json.dumps(
                {
                    "input": str(args.messages_file),
                    **report.to_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "import-context-fixture":
        records = load_context_snapshot_source_records(args.fixture)
        context = _governed_context_from_args(args)
        existing_source_records = context.source_records()
        deleted_changes = _deleted_snapshot_changes(existing_source_records, records)
        import_counts = _source_record_import_counts(
            existing_source_records,
            records,
            deleted_count=len(deleted_changes),
        )
        context.apply_source_changes(_snapshot_source_changes(records, deleted_changes))
        print(
            json.dumps(
                {
                    "input": str(args.fixture),
                    "record_count": len(records),
                    "source_refs": [record.source_ref for record in records],
                    "canonical_object_count": len(context.canonical_objects()),
                    "entity_link_count": len(context.entity_links()),
                    **import_counts,
                    "restricted_count": sum(
                        1 for record in records if record.effective_lifecycle_state != "active"
                    ),
                },
                indent=2,
            )
        )
        return True

    if args.command == "prepare-seed-snapshot":
        print(
            json.dumps(
                prepare_context_seed_snapshot(
                    input_path=args.input,
                    output_path=args.output,
                    project_root=Path("."),
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "run-imports":
        print(json.dumps(_run_imports(args), indent=2, sort_keys=True))
        return True

    if args.command == "run-live-ingestion":
        _ensure_state_parent(args.state)
        args.database_url = _live_ingestion_database_url(args)
        state = _context_state_from_args(args)
        sources = tuple(args.source or ["all"])
        try:
            report = run_live_ingestion_backfill(
                state,
                sources=sources,
                artifact_dir=args.artifact_dir,
                database_url=args.database_url or "",
                now=_optional_datetime(args.now),
                verify_live_db=args.verify_live_db,
            )
        except ValueError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(report, indent=2, sort_keys=True))
        return True

    if args.command == "live-ingestion-status":
        config = _config_from_args(args)
        stale_after_minutes = args.stale_after_minutes or config.scheduler.import_interval_minutes
        if stale_after_minutes < 1:
            raise SystemExit("--stale-after-minutes must be a positive integer")
        _ensure_state_parent(args.state)
        args.database_url = _live_ingestion_database_url(args)
        state = _context_state_from_args(args)
        print(
            json.dumps(
                live_ingestion_status(
                    state,
                    now=_optional_datetime(args.now),
                    stale_after_minutes=stale_after_minutes,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "connector-checkpoint":
        args.database_url = _database_url_unless_explicit_state(args)
        state = _context_state_from_args(args)
        print(
            json.dumps(
                {
                    "connector_name": args.connector_name,
                    "checkpoint": connector_checkpoint(
                        state.engine,
                        state.connector_states,
                        connector_name=args.connector_name,
                    ),
                },
                indent=2,
            )
        )
        return True

    if args.command == "connector-jobs":
        args.database_url = _database_url_unless_explicit_state(args)
        state = _context_state_from_args(args)
        jobs = connector_job_runs(state.engine, state.connector_job_runs)
        if args.connector_name:
            jobs = [job for job in jobs if job["connector_name"] == args.connector_name]
        print(
            json.dumps(
                {
                    "connector_name": args.connector_name,
                    "jobs": jobs,
                },
                indent=2,
            )
        )
        return True
    return False


def _ensure_state_parent(state_path: Path) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)


def _live_ingestion_database_url(args: argparse.Namespace) -> str | None:
    return _database_url_unless_explicit_state(args)


def _database_url_unless_explicit_state(args: argparse.Namespace) -> str | None:
    if args.database_url:
        return args.database_url
    if getattr(args, "state_explicit", False):
        return None
    database_url = os.environ.get("FOUROK_DATABASE_URL")
    if database_url and not _running_in_container():
        return host_database_url(database_url)
    return database_url


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
