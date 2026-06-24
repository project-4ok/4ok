from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from gcb.etl.extract.context_snapshot import load_context_snapshot_source_records
from gcb.etl.extract.source_records import SourceRecord
from gcb.etl.extract.sync_jobs import complete_connector_job, start_connector_job
from gcb.governance import GovernedContext, SourceChange
from gcb.governance.state import create_governed_context_state
from gcb.runtime.access import check_compose_access_boundary
from gcb.runtime.dashboard import operator_dashboard
from gcb.runtime.rebuild import rebuild_retrieval_units
from gcb.runtime.retention import retention_status
from gcb.runtime.webhooks import (
    WebhookEventInput,
    enqueue_webhook_event,
    process_pending_webhook_events,
    webhook_event_rows,
)
from gcb.storage.config import RuntimeConfig, load_runtime_config
from gcb.storage.health import check_runtime_health
from gcb.storage.postgres_backup import (
    BackupCommandError,
    postgres_backup_command,
    postgres_restore_command,
)

ObservabilitySmoke = Callable[[], dict[str, object]]
AccessSmoke = Callable[[], dict[str, object]]


def internal_v0_acceptance_proof(
    *,
    state_path: Path,
    database_url: str | None,
    config_path: Path | None,
    fixture_path: Path,
    query: str,
    backup_database_url: str | None,
    backup_output: Path,
    observability_smoke: ObservabilitySmoke,
    access_smoke: AccessSmoke | None = None,
) -> dict[str, object]:
    config = _load_config(config_path)
    state = create_governed_context_state(
        state_path=state_path,
        database_url=database_url,
        raw_store_path=None,
        raw_store_config=config.raw_store,
    )
    import_report = _run_fixture_import(
        state_path=state_path,
        database_url=database_url,
        fixture_path=fixture_path,
        config=config,
    )
    webhook_report = _run_webhook_proof(
        state=state,
        state_path=state_path,
        database_url=database_url,
        config=config,
        query="webhook acceptance marker",
    )
    retention_report = retention_status(state, config)
    rebuild_report = rebuild_retrieval_units(state, retrieval_config=config.retrieval)
    health = check_runtime_health(state)
    dashboard = operator_dashboard(
        state,
        retry_delay_seconds=config.scheduler.retry_delay_seconds,
        max_retry_attempts=config.scheduler.max_attempts,
    )
    search_report = _run_search_proof(
        state_path=state_path,
        database_url=database_url,
        query=query,
    )
    audit_report = _audit_proof(state_path=state_path, database_url=database_url)
    lifecycle_report = _run_lifecycle_proof(
        state_path=state_path,
        database_url=database_url,
        config=config,
    )
    access_report = (access_smoke or _default_access_smoke)()
    observability_report = observability_smoke()
    backup_report = _backup_command_proof(
        database_url=backup_database_url or database_url,
        output=backup_output,
    )
    restore_report = _restore_command_proof(
        database_url=backup_database_url or database_url,
        input_path=backup_output,
    )

    checks = {
        "config": "ok",
        "health": health["status"],
        "import": _status_from_bool(import_report["record_count"] > 0),
        "dashboard": _status_from_bool(dashboard["source_records"]["total"] > 0),
        "search": _status_from_bool(search_report["evidence_item_count"] > 0),
        "audit": _status_from_bool(
            audit_report["search_events"] > 0 and audit_report["source_access_events"] > 0
        ),
        "webhook": _status_from_bool(
            webhook_report["process"]["succeeded"] == 1
            and webhook_report["search_result_count"] > 0
        ),
        "lifecycle": _status_from_bool(
            lifecycle_report["restricted_hidden"]
            and lifecycle_report["restored_searchable"]
            and lifecycle_report["deleted_hidden"]
            and lifecycle_report["raw_removed_after_delete"]
            and lifecycle_report["final_lifecycle_state"] == "deleted"
            and lifecycle_report["final_retrieval_status"] == "inactive"
        ),
        "retention": _retention_status(retention_report),
        "rebuild": _status_from_bool(rebuild_report["retrieval_units_created"] > 0),
        "access": str(access_report.get("status", "failed")),
        "observability": str(observability_report.get("status", "failed")),
        "backup_command": backup_report["status"],
        "restore_command": restore_report["status"],
    }
    alerts = _acceptance_alerts(checks=checks, dashboard_alerts=dashboard["alerts"])
    return {
        "status": "ok" if all(status == "ok" for status in checks.values()) else "failed",
        "checks": checks,
        "alerts": alerts,
        "config": _config_report(config),
        "health": health,
        "import": import_report,
        "dashboard": {
            "source_records": dashboard["source_records"]["total"],
            "canonical_objects": dashboard["canonical_objects"]["total"],
            "entity_links": dashboard["entity_links"]["total"],
            "connector_jobs_by_status": dashboard["connectors"]["jobs"]["by_status"],
            "webhook_backlog_by_status": dashboard["webhooks"]["by_status"],
            "alert_status": dashboard["alerts"]["status"],
            "alert_count": len(dashboard["alerts"]["items"]),
        },
        "search": search_report,
        "audit": audit_report,
        "webhook": webhook_report,
        "lifecycle": lifecycle_report,
        "retention": retention_report,
        "rebuild": rebuild_report,
        "access": access_report,
        "observability": observability_report,
        "backup_command": backup_report,
        "restore_command": restore_report,
    }


def _default_access_smoke() -> dict[str, object]:
    return check_compose_access_boundary(compose_file=Path("docker-compose.yml"))


def _run_webhook_proof(
    *,
    state,
    state_path: Path,
    database_url: str | None,
    config: RuntimeConfig,
    query: str,
) -> dict[str, object]:
    event_id = "acceptance-webhook-1"
    raw_payload_ref = f"webhook:linear:{event_id}:raw"
    context = GovernedContext(
        state_path,
        database_url=database_url,
        raw_store_config=config.raw_store,
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id=event_id,
            source_system="linear",
            source_object_id="ACCEPT-1",
            event_type="issue.updated",
            operation="upsert",
            idempotency_key="linear:ACCEPT-1:acceptance",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:ACCEPT-1",
                    "source_system": "linear",
                    "source_id": "ACCEPT-1",
                    "record_type": "work_item",
                    "title": "Acceptance webhook event",
                    "body": "Webhook acceptance marker confirms backlog processing.",
                    "source_url": "https://linear.example/ACCEPT-1",
                    "metadata": {"acceptance": True},
                }
            },
        ),
    )
    process_report = process_pending_webhook_events(state, context, limit=1)
    search_report = context.search_context(query, limit=1)
    return {
        "event_id": event_id,
        "process": process_report,
        "raw_payload_landed": bool(
            state.raw_store is not None and state.raw_store.exists(raw_payload_ref)
        ),
        "search_result_count": len(search_report.results),
        "status_by_event_id": {
            str(row["event_id"]): str(row["status"]) for row in webhook_event_rows(state)
        },
    }


def _run_lifecycle_proof(
    *,
    state_path: Path,
    database_url: str | None,
    config: RuntimeConfig,
) -> dict[str, object]:
    source_ref = "acceptance:lifecycle:1"
    query = "sourcechangeprobeuniqueterm"
    record = SourceRecord(
        source_ref=source_ref,
        source_system="acceptance",
        source_id="lifecycle-1",
        record_type="document",
        title="Acceptance lifecycle probe",
        body="sourcechangeprobeuniqueterm proves source-change propagation.",
        source_url="https://example.invalid/gcb/acceptance/lifecycle-1",
    )
    context = GovernedContext(
        state_path,
        database_url=database_url,
        raw_store_config=config.raw_store,
    )
    context.apply_source_changes([SourceChange(operation="upsert", record=record)])
    raw_payload_landed = source_ref in context.raw_source_refs()

    context.apply_source_changes(
        [SourceChange(operation="restrict", source_ref=source_ref, reason="acceptance_hold")]
    )
    restricted_hidden = len(context.search_context(query, limit=1).results) == 0

    context.apply_source_changes([SourceChange(operation="restore", record=record)])
    restored_searchable = len(context.search_context(query, limit=1).results) == 1

    context.apply_source_changes(
        [SourceChange(operation="delete", source_ref=source_ref, reason="acceptance_deleted")]
    )
    deleted_hidden = len(context.search_context(query, limit=1).results) == 0
    final_lifecycle_state = _source_lifecycle_state(context, source_ref)
    final_retrieval_status = _retrieval_status(context, source_ref)
    return {
        "source_ref": source_ref,
        "raw_payload_landed": raw_payload_landed,
        "restricted_hidden": restricted_hidden,
        "restored_searchable": restored_searchable,
        "deleted_hidden": deleted_hidden,
        "raw_removed_after_delete": source_ref not in context.raw_source_refs(),
        "final_lifecycle_state": final_lifecycle_state,
        "final_retrieval_status": final_retrieval_status,
    }


def _source_lifecycle_state(context: GovernedContext, source_ref: str) -> str:
    for row in context.source_lifecycle():
        if row["source_ref"] == source_ref:
            return str(row["state"])
    return ""


def _retrieval_status(context: GovernedContext, source_ref: str) -> str:
    statuses = {
        str(row["status"]) for row in context.retrieval_units() if row["source_ref"] == source_ref
    }
    return ",".join(sorted(statuses))


def _load_config(config_path: Path | None) -> RuntimeConfig:
    if config_path is None:
        return RuntimeConfig()
    return load_runtime_config(config_path)


def _run_fixture_import(
    *,
    state_path: Path,
    database_url: str | None,
    fixture_path: Path,
    config: RuntimeConfig,
) -> dict[str, object]:
    records = load_context_snapshot_source_records(fixture_path)
    context = GovernedContext(
        state_path,
        database_url=database_url,
        retrieval_config=config.retrieval,
        raw_store_config=config.raw_store,
    )
    context.ingest_source_records(records)
    state = create_governed_context_state(
        state_path=state_path,
        database_url=database_url,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="acceptance-fixture",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name="acceptance-fixture",
        output_state={"record_count": len(records), "source_ref_count": len(records)},
        raw_output_ref=str(fixture_path),
    )
    return {
        "connector_name": "acceptance-fixture",
        "record_count": len(records),
        "source_ref_count": len({record.source_ref for record in records}),
        "raw_source_count": len(context.raw_source_refs()),
    }


def _run_search_proof(
    *,
    state_path: Path,
    database_url: str | None,
    query: str,
) -> dict[str, object]:
    response = GovernedContext(state_path, database_url=database_url).search_context(query, limit=1)
    return {
        "query": query,
        "result_count": len(response.results),
        "result_candidate_count": len(response.result_candidates or []),
        "evidence_item_count": len(response.evidence_items or []),
        "primary_object_count": len(response.primary_objects or []),
        "related_object_count": len(response.related_objects or []),
        "has_audit_ref": bool(response.audit_ref),
    }


def _audit_proof(*, state_path: Path, database_url: str | None) -> dict[str, object]:
    context = GovernedContext(state_path, database_url=database_url)
    search_events = context.audit_events(event_type="search")
    source_access_events = context.audit_events(event_type="source_access")
    return {
        "search_events": len(search_events),
        "source_access_events": len(source_access_events),
        "total_events": len(context.audit_events()),
    }


def _backup_command_proof(*, database_url: str | None, output: Path) -> dict[str, object]:
    if not database_url:
        return {
            "status": "failed",
            "reason": "backup_database_url_required",
        }
    command = postgres_backup_command(database_url=database_url, output=output)
    return {
        "status": "ok",
        "program": command[0],
        "argument_count": len(command),
        "output": str(output),
        "has_password_in_command": _url_password(database_url) in " ".join(command)
        if _url_password(database_url)
        else False,
    }


def _restore_command_proof(*, database_url: str | None, input_path: Path) -> dict[str, object]:
    if not database_url:
        return {
            "status": "failed",
            "reason": "restore_database_url_required",
        }
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.touch(exist_ok=True)
    try:
        postgres_restore_command(
            database_url=database_url,
            input_path=input_path,
            confirm_destructive_restore=False,
        )
    except BackupCommandError as error:
        destructive_confirmation_required = "--confirm-destructive-restore" in str(error)
    else:
        destructive_confirmation_required = False
    command = postgres_restore_command(
        database_url=database_url,
        input_path=input_path,
        confirm_destructive_restore=True,
    )
    return {
        "status": "ok" if destructive_confirmation_required else "failed",
        "program": command[0],
        "argument_count": len(command),
        "input": str(input_path),
        "destructive_confirmation_required": destructive_confirmation_required,
        "has_password_in_command": _url_password(database_url) in " ".join(command)
        if _url_password(database_url)
        else False,
    }


def _config_report(config: RuntimeConfig) -> dict[str, object]:
    return {
        "loaded": True,
        "raw_store_configured": config.raw_store.path is not None,
        "retention_configured": (
            config.retention.raw_source_days is not None
            and config.retention.audit_event_days is not None
            and config.retention.backup_days is not None
            and config.retention.webhook_backlog_days is not None
        ),
        "retrieval": {
            "max_words": config.retrieval.max_words,
            "overlap_words": config.retrieval.overlap_words,
        },
        "scheduler": {
            "import_interval_minutes": config.scheduler.import_interval_minutes,
            "retry_interval_minutes": config.scheduler.retry_interval_minutes,
            "max_attempts": config.scheduler.max_attempts,
            "retry_delay_seconds": config.scheduler.retry_delay_seconds,
        },
        "webhooks": {
            "process_limit": config.webhooks.process_limit,
            "max_attempts": config.webhooks.max_attempts,
            "retry_delay_seconds": config.webhooks.retry_delay_seconds,
        },
        "telemetry": {
            "enabled": config.telemetry.enabled,
            "endpoint": config.telemetry.endpoint,
            "service_name": config.telemetry.service_name,
        },
        "connectors": {
            "enabled": list(config.connectors.enabled),
            "source_limit": config.connectors.source_limit,
        },
    }


def _url_password(database_url: str) -> str:
    if "@" not in database_url or ":" not in database_url.split("@", 1)[0]:
        return ""
    return database_url.split("@", 1)[0].rsplit(":", 1)[1]


def _status_from_bool(value: bool) -> str:
    return "ok" if value else "failed"


def _retention_status(report: dict[str, object]) -> str:
    surfaces = report.get("surfaces", {})
    if not isinstance(surfaces, dict):
        return "failed"
    raw_sources = surfaces.get("raw_sources", {})
    audit_events = surfaces.get("audit_events", {})
    if not isinstance(raw_sources, dict) or not isinstance(audit_events, dict):
        return "failed"
    return _status_from_bool(
        raw_sources.get("status") == "configured" and audit_events.get("status") == "configured"
    )


def _acceptance_alerts(
    *,
    checks: dict[str, str],
    dashboard_alerts: object,
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    if isinstance(dashboard_alerts, dict):
        dashboard_items = dashboard_alerts.get("items", [])
        if isinstance(dashboard_items, list):
            items.extend(item for item in dashboard_items if isinstance(item, dict))
    _append_check_alert(
        items,
        checks=checks,
        check_name="access",
        code="access_boundary_failed",
        message="Docker Compose internal access-boundary smoke check failed.",
        next_step=(
            "Run `gcb access-smoke --compose-file docker-compose.yml` and fix "
            "unintended exposed services."
        ),
    )
    _append_check_alert(
        items,
        checks=checks,
        check_name="observability",
        code="observability_failed",
        message="OpenTelemetry smoke/export check failed.",
        next_step=(
            "Run `gcb observability-smoke` with the local observability profile "
            "enabled and inspect exporter configuration."
        ),
    )
    _append_check_alert(
        items,
        checks=checks,
        check_name="backup_command",
        code="backup_command_failed",
        message="PostgreSQL backup command wiring failed.",
        next_step=(
            "Run `gcb postgres-backup` with the configured backup database URL "
            "and verify the output path."
        ),
    )
    _append_check_alert(
        items,
        checks=checks,
        check_name="restore_command",
        code="restore_command_failed",
        message="PostgreSQL restore-drill command wiring failed.",
        next_step=(
            "Run `gcb postgres-restore-drill` against a separate drill database "
            "and inspect the command report."
        ),
    )
    return {
        "status": "needs_attention" if items else "ok",
        "items": items,
    }


def _append_check_alert(
    items: list[dict[str, object]],
    *,
    checks: dict[str, str],
    check_name: str,
    code: str,
    message: str,
    next_step: str,
) -> None:
    if checks.get(check_name) == "ok":
        return
    items.append(
        {
            "code": code,
            "severity": "warning",
            "threshold": "check status != ok",
            "message": message,
            "next_step": next_step,
        }
    )
