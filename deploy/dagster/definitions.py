from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from dagster import (
    AssetSelection,
    Definitions,
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

from gcb.etl.extract.connectors import load_landed_source_records
from gcb.etl.extract.openviking_adapter import load_openviking_messages_jsonl_source_records
from gcb.etl.extract.openviking_sessions import write_openviking_session_messages_jsonl
from gcb.etl.extract.slack_adapter import load_slack_landed_source_records
from gcb.etl.extract.slack_tap_env import apply_slack_tap_defaults
from gcb.etl.extract.sync_jobs import complete_connector_job, try_start_connector_job
from gcb.governance.context import GovernedContext
from gcb.governance.state import create_governed_context_state
from gcb.observability import (
    configure_observability_from_env,
    critical_span,
    set_safe_span_attributes,
)
from gcb.orchestration.dagster_resources import (
    GcbRuntimeResource,
    InfisicalSecretsResource,
    MeltanoProjectResource,
    RawLandingResource,
    build_default_resources,
)
from gcb.runtime.dashboard import operator_dashboard
from gcb.runtime.rebuild import rebuild_context_objects, rebuild_retrieval_units
from gcb.runtime.source_imports import SourceRecordImportReport, import_source_records
from gcb.runtime.webhooks import process_pending_webhook_events, webhook_event_rows
from gcb.storage.config import RetrievalConfig

configure_observability_from_env()


@asset
def meltano_slack_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    infisical_secrets: InfisicalSecretsResource,
) -> MaterializeResult:
    return _run_meltano_raw_landing(
        job_name="slack-live-to-raw",
        landing_dir=raw_landing.root / "slack_live",
        project_root=meltano_project.root,
        secret_env=infisical_secrets.secret_env(),
    )


@asset
def meltano_twenty_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    infisical_secrets: InfisicalSecretsResource,
) -> MaterializeResult:
    return _run_meltano_raw_landing(
        job_name="twenty-live-to-raw",
        landing_dir=raw_landing.root / "twenty_live",
        project_root=meltano_project.root,
        secret_env=infisical_secrets.secret_env(),
    )


@asset
def meltano_linear_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    infisical_secrets: InfisicalSecretsResource,
) -> MaterializeResult:
    return _run_meltano_raw_landing(
        job_name="linear-live-to-raw",
        landing_dir=raw_landing.root / "linear_live",
        project_root=meltano_project.root,
        secret_env=infisical_secrets.secret_env(),
    )


@asset
def meltano_google_drive_live_raw_landing(
    raw_landing: RawLandingResource,
    meltano_project: MeltanoProjectResource,
    infisical_secrets: InfisicalSecretsResource,
) -> MaterializeResult:
    return _run_meltano_raw_landing(
        job_name="google-drive-live-to-raw",
        landing_dir=raw_landing.root / "google_drive_live",
        project_root=meltano_project.root,
        secret_env=infisical_secrets.secret_env(),
    )


def _run_meltano_raw_landing(
    *, job_name: str, landing_dir: Path, project_root: Path, secret_env: dict[str, str]
) -> MaterializeResult:
    with critical_span(
        _meltano_asset_span_name(job_name),
        attributes={
            "gcb.connector.job_name": job_name,
            "gcb.dagster.asset": _meltano_asset_span_name(job_name),
            "gcb.runtime_secret.key_count": len(secret_env),
        },
        status_attribute="gcb.raw_landing.status",
    ) as span:
        meltano = shutil.which("meltano")
        if meltano is None:
            raise RuntimeError("meltano executable is required for pipeline assets")

        landing_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [meltano, "run", job_name],
            check=True,
            cwd=project_root,
            env=_meltano_environment(landing_dir=landing_dir, secret_env=secret_env),
            text=True,
            capture_output=True,
        )

        report = _target_report(result.stderr)
        stream_counts = _landed_stream_counts(landing_dir)
        state_path = landing_dir / "state.json"
        record_count = int(report.get("record_count", sum(stream_counts.values())))
        set_safe_span_attributes(
            span,
            {
                "gcb.raw_landing.status": "succeeded",
                "gcb.raw_landing.record_count": record_count,
                "gcb.raw_landing.stream_count": len(stream_counts),
                "gcb.raw_landing.schema_message_count": int(report.get("schema_messages", 0)),
                "gcb.raw_landing.state_message_count": int(report.get("state_messages", 0)),
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
    return f"gcb_{connector}_live_source_records_from_raw_landing"


@asset(deps=[meltano_slack_live_raw_landing])
def gcb_slack_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    gcb_runtime: GcbRuntimeResource,
) -> MaterializeResult:
    connector_name = "slack-live"
    asset_name = "gcb_slack_live_source_records_from_raw_landing"
    with critical_span(
        asset_name,
        attributes={
            "gcb.connector.name": connector_name,
            "gcb.dagster.asset": asset_name,
            "gcb.dagster.run_id": context.run_id,
        },
        status_attribute="gcb.source_record.status",
    ) as span:
        landing_dir = raw_landing.root / "slack_live"
        records = load_slack_landed_source_records(landing_dir)
        result, report = _import_source_records(records=records, gcb_runtime=gcb_runtime)
        _record_live_connector_success(
            _governed_state(gcb_runtime),
            connector_name=connector_name,
            report=report,
            landing_dir=landing_dir,
            dagster_run_id=context.run_id,
        )
        set_safe_span_attributes(
            span,
            {
                "gcb.source_record.status": "succeeded",
                "gcb.source_record.count": report.record_count,
                "gcb.source_record.restricted_count": report.restricted_count,
                "gcb.retrieval.unit_count": report.retrieval_unit_count,
            },
        )
        return result


@asset(deps=[meltano_twenty_live_raw_landing])
def gcb_twenty_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    gcb_runtime: GcbRuntimeResource,
) -> MaterializeResult:
    return _import_live_landed_source_records(
        context=context,
        landing_dir=raw_landing.root / "twenty_live",
        gcb_runtime=gcb_runtime,
        connector_name="twenty-live",
        streams=("twenty_companies", "twenty_people"),
    )


@asset(deps=[meltano_linear_live_raw_landing])
def gcb_linear_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    gcb_runtime: GcbRuntimeResource,
) -> MaterializeResult:
    return _import_live_landed_source_records(
        context=context,
        landing_dir=raw_landing.root / "linear_live",
        gcb_runtime=gcb_runtime,
        connector_name="linear-live",
        streams=("linear_users", "linear_issues", "linear_comments"),
    )


@asset(deps=[meltano_google_drive_live_raw_landing])
def gcb_google_drive_live_source_records_from_raw_landing(
    context,
    raw_landing: RawLandingResource,
    gcb_runtime: GcbRuntimeResource,
) -> MaterializeResult:
    return _import_live_landed_source_records(
        context=context,
        landing_dir=raw_landing.root / "google_drive_live",
        gcb_runtime=gcb_runtime,
        connector_name="google_drive-live",
        streams=("google_drive_files",),
    )


@asset
def gcb_openviking_live_source_records_from_sessions(
    context,
    raw_landing: RawLandingResource,
    gcb_runtime: GcbRuntimeResource,
) -> MaterializeResult:
    connector_name = "openviking-live"
    sessions_dir = Path(os.environ.get("OPENVIKING_SESSIONS_DIR", "/var/lib/openclaw/sessions"))
    landing_dir = raw_landing.root / "openviking_live"
    landing_dir.mkdir(parents=True, exist_ok=True)
    messages_path = landing_dir / "messages.jsonl"
    normalized_count = write_openviking_session_messages_jsonl(sessions_dir, messages_path)
    records = load_openviking_messages_jsonl_source_records(messages_path)
    _result, report = _import_source_records(records=records, gcb_runtime=gcb_runtime)
    _record_live_connector_success(
        _governed_state(gcb_runtime),
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
    gcb_slack_live_source_records_from_raw_landing,
    gcb_twenty_live_source_records_from_raw_landing,
    gcb_linear_live_source_records_from_raw_landing,
    gcb_google_drive_live_source_records_from_raw_landing,
    gcb_openviking_live_source_records_from_sessions,
]

_LIVE_RAW_LANDING_ASSETS = [
    meltano_slack_live_raw_landing,
    meltano_twenty_live_raw_landing,
    meltano_linear_live_raw_landing,
    meltano_google_drive_live_raw_landing,
]


@asset
def gcb_webhook_backlog(gcb_runtime: GcbRuntimeResource) -> MaterializeResult:
    with critical_span(
        "gcb_webhook_backlog", attributes={"gcb.dagster.asset": "gcb_webhook_backlog"}
    ):
        state = _governed_state(gcb_runtime)
        context = _governed_context(gcb_runtime)
        process_report = process_pending_webhook_events(state, context)
        status_counts = _count_by(webhook_event_rows(state), "status")

        return MaterializeResult(
            metadata={
                "claimed": process_report["claimed"],
                "succeeded": process_report["succeeded"],
                "failed": process_report["failed"],
                "invalid": process_report["invalid"],
                "webhook_event_count": sum(status_counts.values()),
                "webhook_statuses": MetadataValue.json(status_counts),
            }
        )


@asset(deps=[gcb_webhook_backlog])
def gcb_canonical_objects_and_entity_links(
    gcb_runtime: GcbRuntimeResource,
) -> MaterializeResult:
    with critical_span(
        "gcb_canonical_objects_and_entity_links",
        attributes={"gcb.dagster.asset": "gcb_canonical_objects_and_entity_links"},
    ):
        state = _governed_state(gcb_runtime)
        rebuild_report = rebuild_context_objects(state)
        context = _governed_context(gcb_runtime)
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


@asset(deps=[gcb_webhook_backlog])
def gcb_retrieval_records(gcb_runtime: GcbRuntimeResource) -> MaterializeResult:
    with critical_span(
        "gcb_retrieval_records", attributes={"gcb.dagster.asset": "gcb_retrieval_records"}
    ):
        state = _governed_state(gcb_runtime)
        rebuild_report = rebuild_retrieval_units(state, retrieval_config=RetrievalConfig())
        context = _governed_context(gcb_runtime)
        retrieval_units = context.retrieval_units()

        return MaterializeResult(
            metadata={
                "retrieval_unit_count": len(retrieval_units),
                "retrieval_units_rebuilt": rebuild_report["retrieval_units_created"],
                "retrieval_units_deleted": rebuild_report["retrieval_units_deleted"],
                "source_records": rebuild_report["source_records"],
                "retrieval_unit_statuses": MetadataValue.json(_count_by(retrieval_units, "status")),
                "source_ref_count": len(
                    {unit["source_ref"] for unit in retrieval_units if unit.get("source_ref")}
                ),
                "index_kinds": MetadataValue.json(_count_by(retrieval_units, "index_kind")),
            }
        )


@asset(deps=[gcb_retrieval_records])
def gcb_operator_dashboard(gcb_runtime: GcbRuntimeResource) -> MaterializeResult:
    with critical_span(
        "gcb_operator_dashboard", attributes={"gcb.dagster.asset": "gcb_operator_dashboard"}
    ):
        dashboard = operator_dashboard(_governed_state(gcb_runtime))

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


@asset(deps=[gcb_operator_dashboard])
def gcb_audit_metadata(gcb_runtime: GcbRuntimeResource) -> MaterializeResult:
    with critical_span(
        "gcb_audit_metadata", attributes={"gcb.dagster.asset": "gcb_audit_metadata"}
    ):
        audit = _governed_context(gcb_runtime).audit_summary()

        return MaterializeResult(
            metadata={
                "audit_event_count": audit["total_events"],
                "audit_event_types": MetadataValue.json(audit["event_types"]),
                "audit_decisions": MetadataValue.json(audit["decisions"]),
                "audit_humans": MetadataValue.json(audit["humans"]),
            }
        )


def _import_landed_source_records(
    *,
    landing_dir: Path,
    gcb_runtime: GcbRuntimeResource,
    stream: str | None = None,
    streams: tuple[str, ...] = (),
) -> MaterializeResult:
    stream_names = streams or ((stream,) if stream is not None else ())
    records = [
        record
        for stream_name in stream_names
        for record in load_landed_source_records(landing_dir, stream=stream_name)
    ]
    result, _report = _import_source_records(records=records, gcb_runtime=gcb_runtime)
    return result


def _import_live_landed_source_records(
    *,
    context,
    landing_dir: Path,
    gcb_runtime: GcbRuntimeResource,
    connector_name: str,
    stream: str | None = None,
    streams: tuple[str, ...] = (),
) -> MaterializeResult:
    asset_name = _source_records_asset_span_name(connector_name)
    with critical_span(
        asset_name,
        attributes={
            "gcb.connector.name": connector_name,
            "gcb.dagster.asset": asset_name,
            "gcb.dagster.run_id": context.run_id,
        },
        status_attribute="gcb.source_record.status",
    ) as span:
        stream_names = streams or ((stream,) if stream is not None else ())
        records = [
            record
            for stream_name in stream_names
            for record in load_landed_source_records(landing_dir, stream=stream_name)
        ]
        result, report = _import_source_records(records=records, gcb_runtime=gcb_runtime)
        _record_live_connector_success(
            _governed_state(gcb_runtime),
            connector_name=connector_name,
            report=report,
            landing_dir=landing_dir,
            dagster_run_id=context.run_id,
        )
        set_safe_span_attributes(
            span,
            {
                "gcb.source_record.status": "succeeded",
                "gcb.source_record.count": report.record_count,
                "gcb.source_record.restricted_count": report.restricted_count,
                "gcb.retrieval.unit_count": report.retrieval_unit_count,
            },
        )
        return result


def _import_source_records(
    *, records: list[Any], gcb_runtime: GcbRuntimeResource
) -> tuple[MaterializeResult, SourceRecordImportReport]:
    context = GovernedContext(
        gcb_runtime.state,
        database_url=gcb_runtime.database_url or None,
    )
    report = import_source_records(context, records)

    return _source_record_materialization(report), report


def _source_record_materialization(
    report: SourceRecordImportReport,
    metadata: dict[str, Any] | None = None,
) -> MaterializeResult:
    result_metadata = {
        "record_count": report.record_count,
        "source_refs": MetadataValue.json(list(report.source_refs)),
        "source_ref_count": len(report.source_refs),
        "source_systems": MetadataValue.json(list(report.source_systems)),
        "record_types": MetadataValue.json(list(report.record_types)),
        "lifecycle_states": MetadataValue.json(list(report.lifecycle_states)),
        "restricted_count": report.restricted_count,
        "failure_count": 0,
        "retrieval_unit_count": report.retrieval_unit_count,
    }
    if metadata:
        result_metadata.update(metadata)
    return MaterializeResult(metadata=result_metadata)


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
            "retrieval_record_count": report.retrieval_unit_count,
            "dagster_run_id": dagster_run_id,
        },
        raw_output_ref=str(landing_dir),
    )


def _governed_context(gcb_runtime: GcbRuntimeResource) -> GovernedContext:
    return GovernedContext(
        gcb_runtime.state,
        database_url=gcb_runtime.database_url or None,
    )


def _governed_state(gcb_runtime: GcbRuntimeResource):
    return create_governed_context_state(
        state_path=gcb_runtime.state,
        database_url=gcb_runtime.database_url or None,
        raw_store_path=None,
    )


gcb_hourly_live_backfill = define_asset_job(
    "gcb_hourly_live_backfill",
    selection=AssetSelection.assets(
        *_LIVE_RAW_LANDING_ASSETS,
        *_LIVE_SOURCE_RECORD_IMPORT_ASSETS,
        gcb_webhook_backlog,
        gcb_canonical_objects_and_entity_links,
        gcb_retrieval_records,
        gcb_operator_dashboard,
        gcb_audit_metadata,
    ),
    executor_def=in_process_executor,
)

gcb_process_webhook_backlog = define_asset_job(
    "gcb_process_webhook_backlog",
    selection=AssetSelection.assets(
        gcb_webhook_backlog,
        gcb_canonical_objects_and_entity_links,
        gcb_retrieval_records,
        gcb_operator_dashboard,
    ),
)

gcb_hourly_live_backfill_schedule = ScheduleDefinition(
    job=gcb_hourly_live_backfill,
    cron_schedule="0 * * * *",
)


@sensor(job=gcb_process_webhook_backlog, minimum_interval_seconds=60)
def gcb_webhook_backlog_sensor():
    state = _governed_state(
        GcbRuntimeResource(
            state_path=os.environ.get("GCB_STATE_PATH", ".local/dagster/gcb-state.sqlite"),
            database_url=os.environ.get("GCB_DATABASE_URL", ""),
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
            "gcb/source": "webhook-backlog",
            "gcb/pending_webhook_count": str(len(pending_events)),
        },
    )


defs = Definitions(
    assets=[
        meltano_slack_live_raw_landing,
        gcb_slack_live_source_records_from_raw_landing,
        meltano_twenty_live_raw_landing,
        gcb_twenty_live_source_records_from_raw_landing,
        meltano_linear_live_raw_landing,
        gcb_linear_live_source_records_from_raw_landing,
        meltano_google_drive_live_raw_landing,
        gcb_google_drive_live_source_records_from_raw_landing,
        gcb_openviking_live_source_records_from_sessions,
        gcb_webhook_backlog,
        gcb_canonical_objects_and_entity_links,
        gcb_retrieval_records,
        gcb_operator_dashboard,
        gcb_audit_metadata,
    ],
    jobs=[gcb_hourly_live_backfill, gcb_process_webhook_backlog],
    schedules=[gcb_hourly_live_backfill_schedule],
    sensors=[gcb_webhook_backlog_sensor],
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
            "TARGET_GCB_RAW_JSONL_LANDING_DIR": str(landing_dir),
        }
    )


def _singer_secret_aliases(secret_env: dict[str, str]) -> dict[str, str]:
    env = dict(secret_env)
    if "SLACK_BOT_TOKEN" in env and "TAP_SLACK_API_KEY" not in env:
        env["TAP_SLACK_API_KEY"] = env["SLACK_BOT_TOKEN"]
    if "LINEAR_API_KEY" not in env:
        for alias in (
            "TAP_LINEAR_API_KEY",
            "GCB_LINEAR_API_KEY",
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
