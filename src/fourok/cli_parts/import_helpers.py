from __future__ import annotations

import argparse
from datetime import UTC, datetime

from opentelemetry import trace

from fourok.cli_parts.runtime_helpers import (
    _config_from_args,
    _context_state_from_args,
    _governed_context_from_args,
    _optional_datetime,
    _run_import_retry_base_delay_from_args,
)
from fourok.etl.extract.connectors import ConnectorPayloadError, load_gmail_source_records
from fourok.etl.extract.context_snapshot import load_context_snapshot_source_records
from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.extract.sync_jobs import (
    complete_connector_job,
    connector_job_runs,
    connector_retry_plan,
    fail_connector_job,
    mark_connector_job_invalid,
    try_start_connector_job,
)
from fourok.etl.load.source_metadata import source_record_checksum
from fourok.governance import SourceChange
from fourok.runtime.source_imports import import_source_records
from fourok.storage.config import RuntimeConfig


def _raw_retention_days_from_args(args: argparse.Namespace, *, config: RuntimeConfig) -> int:
    if args.retention_days is not None:
        if args.retention_days < 0:
            raise SystemExit("--retention-days must be a non-negative integer")
        return args.retention_days

    retention_days = config.retention.raw_source_days
    if retention_days is None:
        raise SystemExit("raw source retention requires --retention-days or --config")
    return retention_days


def _source_record_import_counts(
    existing_rows: list[dict[str, object]],
    records,
    *,
    deleted_count: int = 0,
) -> dict[str, int]:
    existing_checksums = {
        str(row["source_ref"]): str(row["checksum"]) for row in existing_rows if "checksum" in row
    }
    new_count = 0
    unchanged_count = 0
    changed_count = 0
    incoming_deleted_count = 0
    for record in records:
        if record.effective_lifecycle_state == "deleted":
            incoming_deleted_count += 1
        previous_checksum = existing_checksums.get(record.source_ref)
        if previous_checksum is None:
            new_count += 1
        elif previous_checksum == source_record_checksum(record):
            unchanged_count += 1
        else:
            changed_count += 1
    return {
        "new_count": new_count,
        "unchanged_count": unchanged_count,
        "changed_count": changed_count,
        "deleted_count": incoming_deleted_count + deleted_count,
    }


def _run_imports(args: argparse.Namespace) -> dict[str, object]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("fourok.run_imports") as span:
        try:
            return _run_imports_with_span(args, span)
        except Exception as exc:
            span.set_attribute("fourok.import.status", "failed")
            span.set_attribute("fourok.error.class", type(exc).__name__)
            raise


def _run_imports_with_span(args: argparse.Namespace, span) -> dict[str, object]:
    config = _config_from_args(args)
    retry_base_delay_seconds = _run_import_retry_base_delay_from_args(args, config=config)
    max_attempts = config.scheduler.max_attempts
    _validate_run_import_args(args)
    _validate_run_import_connector_enabled(args, config=config)
    span.set_attribute("fourok.connector.name", args.connector)

    state = _context_state_from_args(args)
    jobs = connector_job_runs(state.engine, state.connector_job_runs)
    now = _optional_datetime(args.now)
    retry_check_time = now or datetime.now(UTC)
    attempt = 1
    if args.retry_failed:
        retry_plan = connector_retry_plan(
            jobs,
            connector_name=args.connector,
            base_delay_seconds=retry_base_delay_seconds,
        )
        if retry_plan is None:
            span.set_attribute("fourok.import.status", "skipped")
            span.set_attribute("fourok.import.skip_reason", "no_failed_connector_job_due")
            return {
                "status": "skipped",
                "connector_name": args.connector,
                "reason": "no_failed_connector_job_due",
            }
        if retry_plan.attempt > max_attempts:
            span.set_attribute("fourok.connector.attempt", retry_plan.attempt)
            span.set_attribute("fourok.import.status", "skipped")
            span.set_attribute("fourok.import.skip_reason", "connector_retry_attempts_exhausted")
            return {
                "status": "skipped",
                "connector_name": args.connector,
                "reason": "connector_retry_attempts_exhausted",
                "max_attempts": max_attempts,
            }
        if datetime.fromisoformat(retry_plan.earliest_retry_at) > retry_check_time:
            span.set_attribute("fourok.connector.attempt", retry_plan.attempt)
            span.set_attribute("fourok.import.status", "retry_not_due")
            return {
                "status": "retry_not_due",
                "connector_name": args.connector,
                "attempt": retry_plan.attempt,
                "earliest_retry_at": retry_plan.earliest_retry_at,
            }
        attempt = retry_plan.attempt
    span.set_attribute("fourok.connector.attempt", attempt)

    start_result = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name=args.connector,
        attempt=attempt,
        now=now,
    )
    if start_result.started is None:
        running_job = start_result.running or {}
        span.set_attribute("fourok.import.status", "skipped")
        span.set_attribute("fourok.import.skip_reason", "connector_job_already_running")
        return {
            "status": "skipped",
            "connector_name": args.connector,
            "reason": "connector_job_already_running",
            "running_job_id": running_job.get("job_id", ""),
        }
    job = start_result.started
    try:
        output = _run_import_connector(args)
    except ConnectorPayloadError as exc:
        mark_connector_job_invalid(
            state.engine,
            state.connector_job_runs,
            job_id=job.job_id,
            error=str(exc),
            raw_output_ref=_run_import_raw_output_ref(args),
            now=now,
        )
        span.set_attribute("fourok.import.status", "invalid")
        raise SystemExit(str(exc)) from exc
    except Exception as exc:
        fail_connector_job(
            state.engine,
            state.connector_job_runs,
            job_id=job.job_id,
            error=str(exc),
            now=now,
        )
        raise

    output_state = output["output_state"]
    span.set_attribute("fourok.import.status", "succeeded")
    span.set_attribute("fourok.import.record_count", output_state["record_count"])
    span.set_attribute("fourok.import.deleted_record_count", output_state["deleted_record_count"])
    span.set_attribute("fourok.import.restricted_count", output_state["restricted_count"])
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name=args.connector,
        output_state=output_state,
        raw_output_ref=str(output.get("raw_output_ref") or ""),
        now=now,
    )
    jobs_after_run = connector_job_runs(state.engine, state.connector_job_runs)
    completed_job = _connector_job_by_id(jobs_after_run, job_id=job.job_id)
    result = {
        "status": "succeeded",
        "connector_name": args.connector,
        "record_count": output["record_count"],
        "source_refs": output["source_refs"],
        "job": completed_job,
    }
    if output["import_counts"]:
        result["import_counts"] = output["import_counts"]
    return result


def _run_import_connector(args: argparse.Namespace) -> dict[str, object]:
    config = _config_from_args(args)
    if args.connector == "context-fixture":
        records = _source_limited_records(
            load_context_snapshot_source_records(args.fixture),
            config=config,
        )
        context = _governed_context_from_args(args)
        existing_source_records = context.source_records()
        deleted_changes = (
            []
            if config.connectors.source_limit is not None
            else _deleted_snapshot_changes(existing_source_records, records)
        )
        import_counts = _source_record_import_counts(
            existing_source_records,
            records,
            deleted_count=len(deleted_changes),
        )
        context.apply_source_changes(_snapshot_source_changes(records, deleted_changes))
        return _scheduled_import_output(
            records=records,
            deleted_count=len(deleted_changes),
            raw_output_ref=str(args.fixture),
            import_counts=import_counts,
        )

    if args.connector == "gmail-singer":
        records = _source_limited_records(
            load_gmail_source_records(args.singer_file),
            config=config,
        )
        import_source_records(_governed_context_from_args(args), records)
        return _scheduled_import_output(
            records=records,
            deleted_count=0,
            raw_output_ref=str(args.singer_file),
        )

    raise SystemExit(f"unsupported connector: {args.connector}")


def _validate_run_import_connector_enabled(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig,
) -> None:
    enabled = config.connectors.enabled
    if enabled and args.connector not in enabled:
        raise SystemExit(f"connector {args.connector} is not enabled by config")


def _source_limited_records(
    records: list[SourceRecord], *, config: RuntimeConfig
) -> list[SourceRecord]:
    if config.connectors.source_limit is None:
        return records
    return records[: config.connectors.source_limit]


def _validate_run_import_args(args: argparse.Namespace) -> None:
    if args.connector == "context-fixture" and args.fixture is None:
        raise SystemExit("--connector context-fixture requires --fixture")
    if args.connector == "gmail-singer" and args.singer_file is None:
        raise SystemExit("--connector gmail-singer requires --singer-file")


def _run_import_raw_output_ref(args: argparse.Namespace) -> str:
    if args.connector == "context-fixture" and args.fixture is not None:
        return str(args.fixture)
    if args.connector == "gmail-singer" and args.singer_file is not None:
        return str(args.singer_file)
    return ""


def _scheduled_import_output(
    *,
    records: list[SourceRecord],
    deleted_count: int,
    raw_output_ref: str,
    import_counts: dict[str, int] | None = None,
) -> dict[str, object]:
    if import_counts is None:
        import_counts = {}
    output_state = {
        "record_count": len(records),
        "deleted_record_count": deleted_count,
        "restricted_count": sum(
            1 for record in records if record.effective_lifecycle_state != "active"
        ),
        "source_ref_count": len({record.source_ref for record in records}) + deleted_count,
        **import_counts,
    }
    return {
        "record_count": len(records),
        "source_refs": [record.source_ref for record in records],
        "raw_output_ref": raw_output_ref,
        "output_state": output_state,
        "import_counts": import_counts,
    }


def _snapshot_source_changes(
    records: list[SourceRecord],
    deleted_changes: list[SourceChange],
) -> list[SourceChange]:
    return [
        *(SourceChange(operation="upsert", record=record) for record in records),
        *deleted_changes,
    ]


def _connector_job_by_id(
    jobs: list[dict[str, object]],
    *,
    job_id: str,
) -> dict[str, object]:
    for job in jobs:
        if job["job_id"] == job_id:
            return job
    raise ValueError(f"connector job not found: {job_id}")


def _deleted_snapshot_changes(
    existing_rows: list[dict[str, object]],
    incoming_records: list[SourceRecord],
) -> list[SourceChange]:
    incoming_source_refs = {record.source_ref for record in incoming_records}
    incoming_systems = {record.source_system for record in incoming_records}
    return [
        SourceChange(
            operation="delete",
            source_ref=str(row["source_ref"]),
            reason="missing_from_latest_snapshot",
        )
        for row in existing_rows
        if row["source_system"] in incoming_systems
        and row["source_ref"] not in incoming_source_refs
        and row["lifecycle_state"] != "deleted"
    ]
