from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, cast

from dagster import (
    AssetKey,
    AssetSelection,
    DefaultScheduleStatus,
    Definitions,
    Failure,
    MaterializeResult,
    MetadataValue,
    RunRequest,
    ScheduleDefinition,
    SkipReason,
    asset,
    define_asset_job,
    in_process_executor,
    sensor,
)

from fourok.etl.extract.connectors import load_landed_source_records
from fourok.etl.extract.openviking_adapter import load_openviking_messages_jsonl_source_records
from fourok.etl.extract.openviking_sessions import write_openviking_session_messages_jsonl
from fourok.etl.extract.slack_adapter import load_slack_landed_source_records
from fourok.etl.extract.slack_tap_env import apply_slack_tap_defaults
from fourok.etl.extract.sync_jobs import complete_connector_job, try_start_connector_job
from fourok.governance.context import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.observability import (
    configure_observability_from_env,
    critical_span,
    set_safe_span_attributes,
)
from fourok.orchestration.dagster_resources import (
    ConnectorEnvResource,
    FourokRuntimeResource,
    MeltanoProjectResource,
    RawLandingResource,
    build_default_resources,
)
from fourok.runtime.dashboard import operator_dashboard
from fourok.runtime.rebuild import rebuild_context_objects, rebuild_retrieval_units
from fourok.runtime.source_imports import SourceRecordImportReport, import_source_records
from fourok.runtime.webhooks import process_pending_webhook_events, webhook_event_rows
from fourok.storage.config import RetrievalConfig

configure_observability_from_env()


@asset
def meltano_slack_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    connector_env: ConnectorEnvResource,
) -> MaterializeResult[Any]:
    return _run_meltano_raw_landing(
        job_name="slack-live-to-raw",
        landing_dir=raw_landing.root / "slack_live",
        project_root=meltano_project.root,
        secret_env=connector_env.secret_env(),
    )


@asset
def meltano_twenty_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    connector_env: ConnectorEnvResource,
) -> MaterializeResult[Any]:
    return _run_meltano_raw_landing(
        job_name="twenty-live-to-raw",
        landing_dir=raw_landing.root / "twenty_live",
        project_root=meltano_project.root,
        secret_env=connector_env.secret_env(),
    )


@asset
def meltano_linear_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    connector_env: ConnectorEnvResource,
) -> MaterializeResult[Any]:
    return _run_meltano_raw_landing(
        job_name="linear-live-to-raw",
        landing_dir=raw_landing.root / "linear_live",
        project_root=meltano_project.root,
        secret_env=connector_env.secret_env(),
    )


@asset
def meltano_google_drive_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    connector_env: ConnectorEnvResource,
) -> MaterializeResult[Any]:
    return _run_meltano_raw_landing(
        job_name="google-drive-live-to-raw",
        landing_dir=raw_landing.root / "google_drive_live",
        project_root=meltano_project.root,
        secret_env=connector_env.secret_env(),
    )


def _run_meltano_raw_landing(
    *, job_name: str, landing_dir: Path, project_root: Path, secret_env: dict[str, str]
) -> MaterializeResult[Any]:
    with critical_span(
        _meltano_asset_span_name(job_name),
        attributes={
            "fourok.connector.job_name": job_name,
            "fourok.dagster.asset": _meltano_asset_span_name(job_name),
            "fourok.runtime_secret.key_count": len(secret_env),
        },
        status_attribute="fourok.raw_landing.status",
    ) as span:
        meltano = shutil.which("meltano") or _venv_executable("meltano")
        if meltano is None:
            raise RuntimeError("meltano executable is required for pipeline assets")

        landing_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [meltano, "--cwd", str(project_root / "deploy" / "meltano"), "run", job_name],
            check=False,
            cwd=project_root,
            env=_meltano_environment(landing_dir=landing_dir, secret_env=secret_env),
            text=True,
            capture_output=True,
        )
        if result.returncode != 0:
            stderr_tail = _safe_output_tail(result.stderr, secret_env=secret_env)
            stdout_tail = _safe_output_tail(result.stdout, secret_env=secret_env)
            detail = _meltano_failure_detail(stderr_tail=stderr_tail, stdout_tail=stdout_tail)
            set_safe_span_attributes(
                span,
                {
                    "fourok.raw_landing.status": "failed",
                    "fourok.raw_landing.exit_code": result.returncode,
                    "fourok.raw_landing.error": detail,
                },
            )
            raise Failure(
                description=(
                    f"Meltano job {job_name} failed with exit code {result.returncode}: {detail}"
                ),
                metadata={
                    "job_name": job_name,
                    "exit_code": result.returncode,
                    "landing_dir": MetadataValue.path(landing_dir),
                    "stderr_tail": MetadataValue.text(stderr_tail),
                    "stdout_tail": MetadataValue.text(stdout_tail),
                    "runtime_secret_key_count": len(secret_env),
                },
            )

        report = _target_report(result.stderr)
        stream_counts = _landed_stream_counts(landing_dir)
        state_path = landing_dir / "state.json"
        record_count = int(report.get("record_count", sum(stream_counts.values())))
        set_safe_span_attributes(
            span,
            {
                "fourok.raw_landing.status": "succeeded",
                "fourok.raw_landing.record_count": record_count,
                "fourok.raw_landing.stream_count": len(stream_counts),
                "fourok.raw_landing.schema_message_count": int(report.get("schema_messages", 0)),
                "fourok.raw_landing.state_message_count": int(report.get("state_messages", 0)),
            },
        )
        return MaterializeResult(
            metadata={
                "landing_dir": MetadataValue.path(landing_dir),
                "record_count": record_count,
                "streams": MetadataValue.json(stream_counts),
                "schema_messages": report.get("schema_messages", 0),
                "state_messages": report.get("state_messages", 0),
                "checkpoint_ref": MetadataValue.path(state_path) if state_path.exists() else "",
                "checkpoint_keys": MetadataValue.json(_checkpoint_keys(state_path)),
                "runtime_secret_key_count": len(secret_env),
            }
        )


def _meltano_asset_span_name(job_name: str) -> str:
    return {
        "slack-live-to-raw": "meltano_slack_live_raw_landing",
        "twenty-live-to-raw": "meltano_twenty_live_raw_landing",
        "linear-live-to-raw": "meltano_linear_live_raw_landing",
        "google-drive-live-to-raw": "meltano_google_drive_live_raw_landing",
    }.get(job_name, f"meltano_{job_name.replace('-', '_')}")


def _source_records_asset_span_name(connector_name: str) -> str:
    connector = connector_name.removesuffix("-live").replace("-", "_")
    return f"fourok_{connector}_live_source_records_from_raw_landing"


@asset(deps=[meltano_slack_live_raw_landing])
def fourok_slack_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    fourok_runtime: FourokRuntimeResource,
) -> MaterializeResult[Any]:
    connector_name = "slack-live"
    asset_name = "fourok_slack_live_source_records_from_raw_landing"
    with critical_span(
        asset_name,
        attributes={
            "fourok.connector.name": connector_name,
            "fourok.dagster.asset": asset_name,
            "fourok.dagster.run_id": context.run_id,
        },
        status_attribute="fourok.source_record.status",
    ) as span:
        landing_dir = raw_landing.root / "slack_live"
        records = load_slack_landed_source_records(landing_dir)
        result, report = _import_source_records(records=records, fourok_runtime=fourok_runtime)
        _record_live_connector_success(
            _governed_state(fourok_runtime),
            connector_name=connector_name,
            report=report,
            landing_dir=landing_dir,
            dagster_run_id=context.run_id,
        )
        set_safe_span_attributes(
            span,
            {
                "fourok.source_record.status": "succeeded",
                "fourok.source_record.count": report.record_count,
                "fourok.source_record.restricted_count": report.restricted_count,
                "fourok.retrieval.unit_count": report.retrieval_unit_count,
            },
        )
        return result


@asset(deps=[meltano_twenty_live_raw_landing])
def fourok_twenty_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    fourok_runtime: FourokRuntimeResource,
) -> MaterializeResult[Any]:
    return _import_live_landed_source_records(
        context=context,
        landing_dir=raw_landing.root / "twenty_live",
        fourok_runtime=fourok_runtime,
        connector_name="twenty-live",
        streams=("twenty_companies", "twenty_people"),
    )


@asset(deps=[meltano_linear_live_raw_landing])
def fourok_linear_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    fourok_runtime: FourokRuntimeResource,
) -> MaterializeResult[Any]:
    return _import_live_landed_source_records(
        context=context,
        landing_dir=raw_landing.root / "linear_live",
        fourok_runtime=fourok_runtime,
        connector_name="linear-live",
        streams=("linear_users", "linear_issues", "linear_comments"),
    )


@asset(deps=[meltano_google_drive_live_raw_landing])
def fourok_google_drive_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    fourok_runtime: FourokRuntimeResource,
) -> MaterializeResult[Any]:
    return _import_live_landed_source_records(
        context=context,
        landing_dir=raw_landing.root / "google_drive_live",
        fourok_runtime=fourok_runtime,
        connector_name="google_drive-live",
        streams=("google_drive_files",),
    )


@asset
def fourok_openviking_live_source_records_from_sessions(
    context,
    raw_landing: RawLandingResource,
    fourok_runtime: FourokRuntimeResource,
) -> MaterializeResult[Any]:
    connector_name = "openviking-live"
    sessions_dir = Path(os.environ.get("OPENVIKING_SESSIONS_DIR", "/var/lib/openclaw/sessions"))
    landing_dir = raw_landing.root / "openviking_live"
    landing_dir.mkdir(parents=True, exist_ok=True)
    messages_path = landing_dir / "messages.jsonl"
    normalized_count = write_openviking_session_messages_jsonl(sessions_dir, messages_path)
    records = load_openviking_messages_jsonl_source_records(messages_path)
    _result, report = _import_source_records(records=records, fourok_runtime=fourok_runtime)
    _record_live_connector_success(
        _governed_state(fourok_runtime),
        connector_name=connector_name,
        report=report,
        landing_dir=landing_dir,
        dagster_run_id=context.run_id,
    )
    return _source_record_materialization(
        report,
        metadata={
            "sessions_dir": MetadataValue.path(sessions_dir),
            "messages_path": MetadataValue.path(messages_path),
            "normalized_message_count": normalized_count,
        },
    )


_LIVE_SOURCE_RECORD_IMPORT_ASSETS = [
    fourok_slack_live_source_records_from_raw_landing,
    fourok_twenty_live_source_records_from_raw_landing,
    fourok_linear_live_source_records_from_raw_landing,
    fourok_google_drive_live_source_records_from_raw_landing,
    fourok_openviking_live_source_records_from_sessions,
]

_LIVE_RAW_LANDING_ASSETS = [
    meltano_slack_live_raw_landing,
    meltano_twenty_live_raw_landing,
    meltano_linear_live_raw_landing,
    meltano_google_drive_live_raw_landing,
]

_CONNECTOR_ASSET_KEYS = {
    "slack": (
        "meltano_slack_live_raw_landing",
        "fourok_slack_live_source_records_from_raw_landing",
    ),
    "twenty": (
        "meltano_twenty_live_raw_landing",
        "fourok_twenty_live_source_records_from_raw_landing",
    ),
    "linear": (
        "meltano_linear_live_raw_landing",
        "fourok_linear_live_source_records_from_raw_landing",
    ),
    "google_drive": (
        "meltano_google_drive_live_raw_landing",
        "fourok_google_drive_live_source_records_from_raw_landing",
    ),
    "openviking": ("fourok_openviking_live_source_records_from_sessions",),
}

_SHARED_BACKFILL_ASSET_KEYS = (
    "fourok_webhook_backlog",
    "fourok_canonical_objects_and_entity_links",
    "fourok_retrieval_records",
    "fourok_operator_dashboard",
    "fourok_audit_metadata",
)


@asset
def fourok_webhook_backlog(fourok_runtime: FourokRuntimeResource) -> MaterializeResult[Any]:
    with critical_span(
        "fourok_webhook_backlog", attributes={"fourok.dagster.asset": "fourok_webhook_backlog"}
    ):
        state = _governed_state(fourok_runtime)
        context = _governed_context(fourok_runtime)
        process_report = process_pending_webhook_events(state, context)
        status_counts = _count_by(webhook_event_rows(state), "status")

        return MaterializeResult(
            metadata={
                "claimed": cast(int, process_report["claimed"]),
                "succeeded": cast(int, process_report["succeeded"]),
                "failed": cast(int, process_report["failed"]),
                "invalid": cast(int, process_report["invalid"]),
                "webhook_event_count": sum(status_counts.values()),
                "webhook_statuses": MetadataValue.json(status_counts),
            }
        )


@asset(deps=[fourok_webhook_backlog, *_LIVE_SOURCE_RECORD_IMPORT_ASSETS])
def fourok_canonical_objects_and_entity_links(
    fourok_runtime: FourokRuntimeResource,
) -> MaterializeResult[Any]:
    with critical_span(
        "fourok_canonical_objects_and_entity_links",
        attributes={"fourok.dagster.asset": "fourok_canonical_objects_and_entity_links"},
    ):
        state = _governed_state(fourok_runtime)
        rebuild_report = rebuild_context_objects(state)
        context = _governed_context(fourok_runtime)
        canonical_objects = context.canonical_objects()
        entity_links = context.entity_links()

        return MaterializeResult(
            metadata={
                "canonical_object_count": len(canonical_objects),
                "canonical_objects_rebuilt": rebuild_report["canonical_objects_created"],
                "canonical_objects_deleted": rebuild_report["canonical_objects_deleted"],
                "canonical_object_types": MetadataValue.json(
                    _count_by(canonical_objects, "object_type")
                ),
                "entity_link_count": len(entity_links),
                "entity_links_rebuilt": rebuild_report["entity_links_created"],
                "entity_links_deleted": rebuild_report["entity_links_deleted"],
                "entity_link_relationships": MetadataValue.json(
                    _count_by(entity_links, "relationship")
                ),
                "source_ref_count": len(
                    {
                        source_ref
                        for row in canonical_objects + entity_links
                        if (source_ref := row.get("source_ref"))
                    }
                ),
            }
        )


@asset(deps=[fourok_canonical_objects_and_entity_links])
def fourok_retrieval_records(fourok_runtime: FourokRuntimeResource) -> MaterializeResult[Any]:
    with critical_span(
        "fourok_retrieval_records", attributes={"fourok.dagster.asset": "fourok_retrieval_records"}
    ):
        state = _governed_state(fourok_runtime)
        rebuild_report = rebuild_retrieval_units(state, retrieval_config=RetrievalConfig())
        context = _governed_context(fourok_runtime)
        retrieval_units = context.retrieval_units()

        return MaterializeResult(
            metadata={
                "retrieval_unit_count": len(retrieval_units),
                "retrieval_units_rebuilt": rebuild_report["retrieval_units_created"],
                "retrieval_units_deleted": rebuild_report["retrieval_units_deleted"],
                "embeddings_indexed": rebuild_report["embeddings_indexed"],
                "source_records": rebuild_report["source_records"],
                "retrieval_unit_statuses": MetadataValue.json(_count_by(retrieval_units, "status")),
                "source_ref_count": len(
                    {unit["source_ref"] for unit in retrieval_units if unit.get("source_ref")}
                ),
                "index_kinds": MetadataValue.json(_count_by(retrieval_units, "index_kind")),
            }
        )


@asset(deps=[fourok_retrieval_records])
def fourok_operator_dashboard(fourok_runtime: FourokRuntimeResource) -> MaterializeResult[Any]:
    with critical_span(
        "fourok_operator_dashboard",
        attributes={"fourok.dagster.asset": "fourok_operator_dashboard"},
    ):
        dashboard = operator_dashboard(_governed_state(fourok_runtime))

        return MaterializeResult(
            metadata={
                "source_record_count": dashboard["source_records"]["total"],
                "canonical_object_count": dashboard["canonical_objects"]["total"],
                "entity_link_count": dashboard["entity_links"]["total"],
                "retrieval_unit_count": dashboard["retrieval_records"]["total"],
                "audit_event_count": dashboard["audit"]["total_events"],
                "alert_status": dashboard["alerts"]["status"],
                "alert_count": len(dashboard["alerts"]["items"]),
            }
        )


@asset(deps=[fourok_operator_dashboard])
def fourok_audit_metadata(fourok_runtime: FourokRuntimeResource) -> MaterializeResult[Any]:
    with critical_span(
        "fourok_audit_metadata", attributes={"fourok.dagster.asset": "fourok_audit_metadata"}
    ):
        audit = _governed_context(fourok_runtime).audit_summary()

        return MaterializeResult(
            metadata={
                "audit_event_count": cast(int, audit["total_events"]),
                "audit_event_types": MetadataValue.json(cast(dict[str, Any], audit["event_types"])),
                "audit_decisions": MetadataValue.json(cast(dict[str, Any], audit["decisions"])),
                "audit_humans": MetadataValue.json(cast(dict[str, Any], audit["humans"])),
            }
        )


def _import_landed_source_records(
    *,
    landing_dir: Path,
    fourok_runtime: FourokRuntimeResource,
    stream: str | None = None,
    streams: tuple[str, ...] = (),
) -> MaterializeResult[Any]:
    stream_names = streams or ((stream,) if stream is not None else ())
    records = [
        record
        for stream_name in stream_names
        for record in load_landed_source_records(landing_dir, stream=stream_name)
    ]
    result, _report = _import_source_records(records=records, fourok_runtime=fourok_runtime)
    return result


def _import_live_landed_source_records(
    *,
    context,
    landing_dir: Path,
    fourok_runtime: FourokRuntimeResource,
    connector_name: str,
    stream: str | None = None,
    streams: tuple[str, ...] = (),
) -> MaterializeResult[Any]:
    asset_name = _source_records_asset_span_name(connector_name)
    with critical_span(
        asset_name,
        attributes={
            "fourok.connector.name": connector_name,
            "fourok.dagster.asset": asset_name,
            "fourok.dagster.run_id": context.run_id,
        },
        status_attribute="fourok.source_record.status",
    ) as span:
        stream_names = streams or ((stream,) if stream is not None else ())
        records = [
            record
            for stream_name in stream_names
            for record in load_landed_source_records(landing_dir, stream=stream_name)
        ]
        result, report = _import_source_records(
            records=records,
            fourok_runtime=fourok_runtime,
            snapshot_deletes=True,
            snapshot_scopes=_snapshot_scopes_for_landed_streams(stream_names),
        )
        _record_live_connector_success(
            _governed_state(fourok_runtime),
            connector_name=connector_name,
            report=report,
            landing_dir=landing_dir,
            dagster_run_id=context.run_id,
        )
        set_safe_span_attributes(
            span,
            {
                "fourok.source_record.status": "succeeded",
                "fourok.source_record.count": report.record_count,
                "fourok.source_record.restricted_count": report.restricted_count,
                "fourok.retrieval.unit_count": report.retrieval_unit_count,
            },
        )
        return result


def _import_source_records(
    *,
    records: list[Any],
    fourok_runtime: FourokRuntimeResource,
    snapshot_deletes: bool = False,
    snapshot_scopes: set[tuple[str, str]] | None = None,
) -> tuple[MaterializeResult[Any], SourceRecordImportReport]:
    context = GovernedContext(
        fourok_runtime.state,
        database_url=fourok_runtime.database_url or None,
    )
    report = import_source_records(
        context,
        records,
        snapshot_deletes=snapshot_deletes,
        snapshot_scopes=snapshot_scopes,
    )

    return _source_record_materialization(report), report


def _source_record_materialization(
    report: SourceRecordImportReport,
    metadata: dict[str, Any] | None = None,
) -> MaterializeResult[Any]:
    result_metadata = {
        "record_count": report.record_count,
        "source_refs": MetadataValue.json(list(report.source_refs)),
        "source_ref_count": len(report.source_refs),
        "source_systems": MetadataValue.json(list(report.source_systems)),
        "record_types": MetadataValue.json(list(report.record_types)),
        "lifecycle_states": MetadataValue.json(list(report.lifecycle_states)),
        "restricted_count": report.restricted_count,
        "deleted_record_count": report.deleted_record_count,
        "failure_count": 0,
        "retrieval_unit_count": report.retrieval_unit_count,
    }
    if metadata:
        result_metadata.update(metadata)
    return MaterializeResult(metadata=result_metadata)


def _snapshot_scopes_for_landed_streams(
    stream_names: tuple[str | None, ...],
) -> set[tuple[str, str]]:
    stream_scopes = {
        "twenty_companies": ("twenty", "organization"),
        "twenty_people": ("twenty", "person"),
        "linear_users": ("linear", "person"),
        "linear_issues": ("linear", "work_item"),
        "linear_comments": ("linear", "message"),
        "google_drive_files": ("google_drive", "document"),
    }
    return {stream_scopes[name] for name in stream_names if name in stream_scopes}


def _record_live_connector_success(
    state,
    *,
    connector_name: str,
    report: SourceRecordImportReport,
    landing_dir: Path,
    dagster_run_id: str,
) -> None:
    start_result = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name=connector_name,
        job_id=f"dagster:{dagster_run_id}:{connector_name}",
        input_state={"dagster_run_id": dagster_run_id},
    )
    if start_result.started is None:
        return

    job = start_result.started
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name=connector_name,
        output_state={
            "freshness_status": "fresh",
            "idempotency_status": "recorded",
            "source_record_count": report.record_count,
            "deleted_source_record_count": report.deleted_record_count,
            "retrieval_record_count": report.retrieval_unit_count,
            "dagster_run_id": dagster_run_id,
        },
        raw_output_ref=str(landing_dir),
    )


def _governed_context(fourok_runtime: FourokRuntimeResource) -> GovernedContext:
    return GovernedContext(
        fourok_runtime.state,
        database_url=fourok_runtime.database_url or None,
    )


def _governed_state(fourok_runtime: FourokRuntimeResource):
    return create_governed_context_state(
        state_path=fourok_runtime.state,
        database_url=fourok_runtime.database_url or None,
        raw_store_path=None,
    )


fourok_hourly_live_backfill = define_asset_job(
    "fourok_hourly_live_backfill",
    selection=AssetSelection.assets(
        *_LIVE_RAW_LANDING_ASSETS,
        *_LIVE_SOURCE_RECORD_IMPORT_ASSETS,
        fourok_webhook_backlog,
        fourok_canonical_objects_and_entity_links,
        fourok_retrieval_records,
        fourok_operator_dashboard,
        fourok_audit_metadata,
    ),
    executor_def=in_process_executor,
)

fourok_process_webhook_backlog = define_asset_job(
    "fourok_process_webhook_backlog",
    selection=AssetSelection.assets(
        fourok_webhook_backlog,
        fourok_canonical_objects_and_entity_links,
        fourok_retrieval_records,
        fourok_operator_dashboard,
    ),
)


def _hourly_live_backfill_schedule(_context) -> RunRequest:
    env = build_default_resources()["connector_env"].secret_env()
    configured_sources = _configured_live_sources(env)
    return RunRequest(
        asset_selection=_configured_live_backfill_asset_keys(env),
        tags={
            "fourok/configured_sources": ",".join(configured_sources) or "none",
        },
    )


fourok_hourly_live_backfill_schedule = ScheduleDefinition(
    job=fourok_hourly_live_backfill,
    cron_schedule="0 * * * *",
    execution_fn=_hourly_live_backfill_schedule,
    default_status=DefaultScheduleStatus.RUNNING,
)


@sensor(job=fourok_process_webhook_backlog, minimum_interval_seconds=60)
def fourok_webhook_backlog_sensor():
    state = _governed_state(
        FourokRuntimeResource(
            state_path=os.environ.get("FOUROK_STATE_PATH", ".local/dagster/fourok-state.sqlite"),
            database_url=os.environ.get("FOUROK_DATABASE_URL", ""),
        )
    )
    pending_events = [
        event
        for event in webhook_event_rows(state, status="pending")
        if event["status"] == "pending"
    ]
    if not pending_events:
        return SkipReason("no pending webhook events")
    return RunRequest(
        run_key=f"webhook-backlog-{len(pending_events)}-{pending_events[-1]['event_id']}",
        tags={
            "fourok/source": "webhook-backlog",
            "fourok/pending_webhook_count": str(len(pending_events)),
        },
    )


defs = Definitions(
    assets=[
        meltano_slack_live_raw_landing,
        fourok_slack_live_source_records_from_raw_landing,
        meltano_twenty_live_raw_landing,
        fourok_twenty_live_source_records_from_raw_landing,
        meltano_linear_live_raw_landing,
        fourok_linear_live_source_records_from_raw_landing,
        meltano_google_drive_live_raw_landing,
        fourok_google_drive_live_source_records_from_raw_landing,
        fourok_openviking_live_source_records_from_sessions,
        fourok_webhook_backlog,
        fourok_canonical_objects_and_entity_links,
        fourok_retrieval_records,
        fourok_operator_dashboard,
        fourok_audit_metadata,
    ],
    jobs=[fourok_hourly_live_backfill, fourok_process_webhook_backlog],
    schedules=[fourok_hourly_live_backfill_schedule],
    sensors=[fourok_webhook_backlog_sensor],
    resources=build_default_resources(),
)


def _target_report(stderr: str) -> dict[str, Any]:
    for line in reversed(stderr.splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and "record_count" in parsed:
            return parsed
    return {}


def _venv_executable(name: str) -> str | None:
    candidate = Path(sys.executable).with_name(name)
    return str(candidate) if candidate.exists() else None


def _configured_live_backfill_asset_keys(env: dict[str, str]) -> list[AssetKey]:
    asset_names = [
        asset_name
        for source in _configured_live_sources(env)
        for asset_name in _CONNECTOR_ASSET_KEYS[source]
    ]
    asset_names.extend(_SHARED_BACKFILL_ASSET_KEYS)
    return [AssetKey(asset_name) for asset_name in asset_names]


def _configured_live_sources(env: dict[str, str]) -> tuple[str, ...]:
    sources: list[str] = []
    if _has_env_value(env, "SLACK_BOT_TOKEN") or _has_env_value(env, "TAP_SLACK_API_KEY"):
        sources.append("slack")
    if _has_env_value(env, "TWENTY_API_KEY"):
        sources.append("twenty")
    if any(
        _has_env_value(env, key)
        for key in ("LINEAR_API_KEY", "TAP_LINEAR_API_KEY", "FOUROK_LINEAR_API_KEY")
    ):
        sources.append("linear")
    if _has_env_value(env, "GOOGLE_WORKSPACE_ACCESS_TOKEN") or _has_env_value(
        env,
        "GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON",
        "GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN",
    ):
        sources.append("google_drive")
    openviking_sessions_dir = env.get("OPENVIKING_SESSIONS_DIR", "").strip()
    if openviking_sessions_dir and Path(openviking_sessions_dir).exists():
        sources.append("openviking")
    return tuple(sources)


def _has_env_value(env: dict[str, str], *keys: str) -> bool:
    return all(env.get(key, "").strip() for key in keys)


def _safe_output_tail(output: str, *, secret_env: dict[str, str], line_limit: int = 40) -> str:
    text = "\n".join(output.splitlines()[-line_limit:])
    for value in secret_env.values():
        if len(value) >= 8:
            text = text.replace(value, "[REDACTED]")
    return text


def _meltano_failure_detail(*, stderr_tail: str, stdout_tail: str) -> str:
    for output in (stderr_tail, stdout_tail):
        for line in reversed(output.splitlines()):
            stripped = line.strip()
            lowered = stripped.lower()
            if stripped and (" failed:" in lowered or "failed:" in lowered):
                return stripped
    for output in (stderr_tail, stdout_tail):
        for line in reversed(output.splitlines()):
            stripped = line.strip()
            lowered = stripped.lower()
            if stripped and ("failed" in lowered or "error" in lowered or "traceback" in lowered):
                return stripped
    for output in (stderr_tail, stdout_tail):
        for line in reversed(output.splitlines()):
            stripped = line.strip()
            if stripped:
                return stripped
    return "Meltano command failed without stderr/stdout"


def _landed_stream_counts(landing_dir: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for path in sorted(landing_dir.glob("*.jsonl")):
        counts[path.stem] = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line)
    return counts


def _meltano_environment(*, landing_dir: Path, secret_env: dict[str, str]) -> dict[str, str]:
    return apply_slack_tap_defaults(
        {
            **os.environ,
            **_singer_secret_aliases(secret_env),
            "TARGET_FOUROK_RAW_JSONL_LANDING_DIR": str(landing_dir),
        }
    )


def _singer_secret_aliases(secret_env: dict[str, str]) -> dict[str, str]:
    env = dict(secret_env)
    if "SLACK_BOT_TOKEN" in env and "TAP_SLACK_API_KEY" not in env:
        env["TAP_SLACK_API_KEY"] = env["SLACK_BOT_TOKEN"]
    if "LINEAR_API_KEY" not in env:
        for alias in (
            "TAP_LINEAR_API_KEY",
            "FOUROK_LINEAR_API_KEY",
            "LINEAR_API_TOKEN",
            "LINEAR_TOKEN",
            "LINEAR_PAT",
        ):
            if alias in env:
                env["LINEAR_API_KEY"] = env[alias]
                break
    return env


def _checkpoint_keys(state_path: Path) -> list[str]:
    if not state_path.exists():
        return []
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(state, dict):
        return []
    return sorted(str(key) for key in state)


def _count_by(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))
