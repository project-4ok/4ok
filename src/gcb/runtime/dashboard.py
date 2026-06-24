from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol

from opentelemetry import trace
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from gcb.etl.extract.sync_jobs import connector_job_runs, connector_retry_plan
from gcb.governance.audit import audit_summary
from gcb.runtime.recurring_live_ingestion import live_ingestion_status


class DashboardState(Protocol):
    engine: Engine
    source_records: Table
    canonical_objects: Table
    entity_links: Table
    retrieval_records: Table
    source_lifecycle: Table
    connector_states: Table
    connector_job_runs: Table
    webhook_events: Table
    audit_events: Table
    raw_store: object | None


def operator_dashboard(
    state: DashboardState,
    *,
    retry_delay_seconds: int = 300,
    max_retry_attempts: int = 3,
) -> dict[str, Any]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("gcb.dashboard") as span:
        report = _operator_dashboard(
            state,
            retry_delay_seconds=retry_delay_seconds,
            max_retry_attempts=max_retry_attempts,
        )
        span.set_attribute(
            "gcb.dashboard.source_record_count",
            report["source_records"]["total"],
        )
        span.set_attribute(
            "gcb.dashboard.connector_job_count",
            report["connectors"]["jobs"]["total"],
        )
        span.set_attribute(
            "gcb.dashboard.webhook_backlog_count",
            report["webhooks"]["by_status"].get("pending", 0),
        )
        span.set_attribute(
            "gcb.dashboard.slack_message_count",
            report["slack_messages"]["active_total"],
        )
        span.set_attribute(
            "gcb.dashboard.audit_event_count",
            report["audit"]["total_events"],
        )
        span.set_attribute(
            "gcb.dashboard.alert_count",
            len(report["alerts"]["items"]),
        )
        span.set_attribute("gcb.dashboard.alert_status", report["alerts"]["status"])
        return report


def operator_status(
    state: DashboardState,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 60,
) -> dict[str, Any]:
    jobs = connector_job_runs(state.engine, state.connector_job_runs)
    latest_job = _latest_job(jobs)
    latest_job_summary: dict[str, str] = {}
    if latest_job is not None:
        latest_job_summary = {
            "connector_name": str(latest_job["connector_name"]),
            "status": str(latest_job["status"]),
            "started_at": str(latest_job["started_at"]),
            "finished_at": str(latest_job["finished_at"]),
            "raw_output_ref": str(latest_job["raw_output_ref"]),
        }

    return {
        "status": "ok",
        "imported_items_by_source": _count_by(
            state.engine,
            state.source_records,
            state.source_records.c.source_system,
            where=state.source_records.c.lifecycle_state == "active",
        ),
        "imported_items_by_source_record_type": _nested_count_by(
            state.engine,
            state.source_records,
            state.source_records.c.source_system,
            state.source_records.c.record_type,
            where=state.source_records.c.lifecycle_state == "active",
        ),
        "retrieval_records": {
            "total": _count_rows(state.engine, state.retrieval_records),
            "by_status": _count_by(
                state.engine,
                state.retrieval_records,
                state.retrieval_records.c.status,
            ),
        },
        "connector_jobs": {
            "latest": latest_job_summary,
            "by_status": _count_by(
                state.engine,
                state.connector_job_runs,
                state.connector_job_runs.c.status,
            ),
        },
        "freshness": {
            "latest_checkpoint_at": _max_value(
                state.engine,
                state.connector_states,
                state.connector_states.c.updated_at,
            ),
            "latest_finished_at": _max_value(
                state.engine,
                state.connector_job_runs,
                state.connector_job_runs.c.finished_at,
            ),
            "live_ingestion": live_ingestion_status(
                state,
                now=now,
                stale_after_minutes=stale_after_minutes,
            ),
        },
    }


def _operator_dashboard(
    state: DashboardState,
    *,
    retry_delay_seconds: int,
    max_retry_attempts: int,
) -> dict[str, Any]:
    source_total = _count_rows(state.engine, state.source_records)
    linked_source_count = _distinct_count(
        state.engine,
        state.entity_links,
        state.entity_links.c.source_ref,
        where=state.entity_links.c.status.in_(["linked", "accepted"]),
    )
    connector_jobs_by_status = _count_by(
        state.engine,
        state.connector_job_runs,
        state.connector_job_runs.c.status,
    )
    connector_retry = _connector_retry_visibility(
        state,
        retry_delay_seconds=retry_delay_seconds,
        max_retry_attempts=max_retry_attempts,
    )
    webhook_by_status = _count_by(
        state.engine,
        state.webhook_events,
        state.webhook_events.c.status,
    )
    report = {
        "source_records": {
            "total": source_total,
            "by_source_system": _count_by(
                state.engine,
                state.source_records,
                state.source_records.c.source_system,
            ),
            "by_record_type": _count_by(
                state.engine,
                state.source_records,
                state.source_records.c.record_type,
            ),
            "by_source_system_record_type": _nested_count_by(
                state.engine,
                state.source_records,
                state.source_records.c.source_system,
                state.source_records.c.record_type,
            ),
            "by_lifecycle_state": _count_by(
                state.engine,
                state.source_records,
                state.source_records.c.lifecycle_state,
            ),
        },
        "canonical_objects": {
            "total": _count_rows(state.engine, state.canonical_objects),
            "by_object_type": _count_by(
                state.engine,
                state.canonical_objects,
                state.canonical_objects.c.object_type,
            ),
            "by_lifecycle_state": _count_by(
                state.engine,
                state.canonical_objects,
                state.canonical_objects.c.lifecycle_state,
            ),
        },
        "entity_links": {
            "total": _count_rows(state.engine, state.entity_links),
            "by_status": _count_by(
                state.engine,
                state.entity_links,
                state.entity_links.c.status,
            ),
            "by_reason": _count_by(
                state.engine,
                state.entity_links,
                state.entity_links.c.reason,
            ),
            "linked_source_count": linked_source_count,
            "link_coverage": _coverage(linked_source_count, source_total),
        },
        "source_lifecycle": {
            "total": _count_rows(state.engine, state.source_lifecycle),
            "by_state": _count_by(
                state.engine,
                state.source_lifecycle,
                state.source_lifecycle.c.state,
            ),
        },
        "retrieval_records": {
            "total": _count_rows(state.engine, state.retrieval_records),
            "by_status": _count_by(
                state.engine,
                state.retrieval_records,
                state.retrieval_records.c.status,
            ),
            "by_index_kind": _count_by(
                state.engine,
                state.retrieval_records,
                state.retrieval_records.c.index_kind,
            ),
        },
        "connectors": {
            "state_count": _count_rows(state.engine, state.connector_states),
            "latest_checkpoint_at": _max_value(
                state.engine,
                state.connector_states,
                state.connector_states.c.updated_at,
            ),
            "jobs": {
                "total": sum(connector_jobs_by_status.values()),
                "by_status": connector_jobs_by_status,
                "latest_started_at": _max_value(
                    state.engine,
                    state.connector_job_runs,
                    state.connector_job_runs.c.started_at,
                ),
                "latest_finished_at": _max_value(
                    state.engine,
                    state.connector_job_runs,
                    state.connector_job_runs.c.finished_at,
                ),
                "recent_failure_count": connector_jobs_by_status.get("failed", 0),
                "recent_invalid_count": connector_jobs_by_status.get("invalid", 0),
                "latest_failed_connector": connector_retry["latest_failed_connector"],
                "next_retry_attempt": connector_retry["next_retry_attempt"],
                "earliest_retry_at": connector_retry["earliest_retry_at"],
                "retry_exhausted": connector_retry["retry_exhausted"],
                "recent_import_rate": {
                    "unit": "succeeded_connector_jobs",
                    "count": connector_jobs_by_status.get("succeeded", 0),
                },
            },
        },
        "raw_sources": _raw_source_visibility(state),
        "slack_messages": _slack_message_visibility(state),
        "google_drive_files": _google_drive_file_visibility(state),
        "webhooks": {
            "total": _count_rows(state.engine, state.webhook_events),
            "by_status": webhook_by_status,
            "by_source_system": _count_by(
                state.engine,
                state.webhook_events,
                state.webhook_events.c.source_system,
            ),
            "latest_received_at": _max_value(
                state.engine,
                state.webhook_events,
                state.webhook_events.c.received_at,
            ),
            "latest_processed_at": _max_value(
                state.engine,
                state.webhook_events,
                state.webhook_events.c.processed_at,
            ),
        },
        "audit": audit_summary(state.engine, state.audit_events),
    }
    report["alerts"] = _alert_summary(
        connector_jobs_by_status=connector_jobs_by_status,
        webhook_by_status=webhook_by_status,
    )
    return report


def _latest_job(jobs: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not jobs:
        return None
    return max(jobs, key=lambda job: (job["finished_at"], job["started_at"], job["job_id"]))


def _count_rows(engine: Engine, table: Table) -> int:
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def _count_by(engine: Engine, table: Table, column, *, where=None) -> dict[str, int]:
    statement = (
        select(column, func.count())
        .select_from(table)
        .where(column != "")
        .group_by(column)
        .order_by(column)
    )
    if where is not None:
        statement = statement.where(where)
    with engine.connect() as connection:
        return {str(row[0]): int(row[1]) for row in connection.execute(statement)}


def _nested_count_by(
    engine: Engine,
    table: Table,
    outer_column,
    inner_column,
    *,
    where=None,
) -> dict[str, dict[str, int]]:
    statement = (
        select(outer_column, inner_column, func.count())
        .select_from(table)
        .where(outer_column != "")
        .where(inner_column != "")
        .group_by(outer_column, inner_column)
        .order_by(outer_column, inner_column)
    )
    if where is not None:
        statement = statement.where(where)
    counts: dict[str, dict[str, int]] = {}
    with engine.connect() as connection:
        for outer, inner, count in connection.execute(statement):
            outer_counts = counts.setdefault(str(outer), {})
            outer_counts[str(inner)] = int(count)
    return {outer: dict(sorted(inner.items())) for outer, inner in sorted(counts.items())}


def _distinct_count(engine: Engine, table: Table, column, *, where) -> int:
    statement = select(func.count(func.distinct(column))).select_from(table).where(where)
    with engine.connect() as connection:
        return int(connection.execute(statement).scalar_one())


def _max_value(engine: Engine, table: Table, column) -> str:
    statement = select(func.max(column)).select_from(table).where(column != "")
    with engine.connect() as connection:
        value = connection.execute(statement).scalar_one()
    return str(value) if value is not None else ""


def _raw_source_visibility(state: DashboardState) -> dict[str, object]:
    if state.raw_store is None:
        return {
            "configured": False,
            "path": "",
            "stored_count": 0,
            "source_record_ref_count": 0,
            "source_record_refs": [],
            "unreferenced_count": 0,
        }

    stored_refs = set(state.raw_store.refs())
    source_record_refs = _source_record_raw_refs(state.engine, state.source_records)
    return {
        "configured": True,
        "path": str(state.raw_store.root),
        "stored_count": len(stored_refs),
        "source_record_ref_count": len(source_record_refs),
        "source_record_refs": sorted(source_record_refs),
        "unreferenced_count": len(stored_refs.difference(source_record_refs)),
    }


def _source_record_raw_refs(engine: Engine, source_records: Table) -> set[str]:
    statement = (
        select(source_records.c.raw_ref)
        .select_from(source_records)
        .where(source_records.c.raw_ref != "")
    )
    with engine.connect() as connection:
        return {str(row[0]) for row in connection.execute(statement)}


def _slack_message_visibility(state: DashboardState) -> dict[str, int]:
    return {
        "active_total": _count_rows_where(
            state.engine,
            state.source_records,
            (state.source_records.c.source_system == "slack")
            & (state.source_records.c.record_type == "message")
            & (state.source_records.c.lifecycle_state == "active"),
        )
    }


def _count_rows_where(engine: Engine, table: Table, where) -> int:
    statement = select(func.count()).select_from(table).where(where)
    with engine.connect() as connection:
        return int(connection.execute(statement).scalar_one())


def _google_drive_file_visibility(state: DashboardState) -> dict[str, object]:
    statement = (
        select(
            state.source_records.c.metadata_json,
        )
        .select_from(state.source_records)
        .where(state.source_records.c.source_system == "google_drive")
        .where(state.source_records.c.record_type == "document")
        .where(state.source_records.c.lifecycle_state == "active")
    )
    by_mime_type: dict[str, int] = {}
    by_content_status: dict[str, int] = {}
    by_export_status: dict[str, int] = {}
    total = 0
    with state.engine.connect() as connection:
        rows = connection.execute(statement)
        for row in rows:
            total += 1
            metadata = _metadata_object(row[0])
            _increment(by_mime_type, _metadata_string(metadata, "mime_type"))
            _increment(by_content_status, _metadata_string(metadata, "content_status"))
            _increment(by_export_status, _metadata_string(metadata, "export_status"))
    return {
        "total": total,
        "by_mime_type": by_mime_type,
        "by_content_status": by_content_status,
        "by_export_status": by_export_status,
    }


def _metadata_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def _increment(counts: dict[str, int], value: str) -> None:
    if not value:
        return
    counts[value] = counts.get(value, 0) + 1


def _connector_retry_visibility(
    state: DashboardState,
    *,
    retry_delay_seconds: int,
    max_retry_attempts: int,
) -> dict[str, object]:
    jobs = connector_job_runs(state.engine, state.connector_job_runs)
    failed = [job for job in jobs if job["status"] == "failed"]
    if not failed:
        return {
            "latest_failed_connector": "",
            "next_retry_attempt": 0,
            "earliest_retry_at": "",
            "retry_exhausted": False,
        }
    latest_failed = max(
        failed,
        key=lambda job: (job["finished_at"], job["started_at"], job["job_id"]),
    )
    retry = connector_retry_plan(
        jobs,
        connector_name=str(latest_failed["connector_name"]),
        base_delay_seconds=retry_delay_seconds,
    )
    retry_exhausted = retry is not None and retry.attempt > max_retry_attempts
    return {
        "latest_failed_connector": latest_failed["connector_name"],
        "next_retry_attempt": retry.attempt if retry is not None else 0,
        "earliest_retry_at": (
            retry.earliest_retry_at if retry is not None and not retry_exhausted else ""
        ),
        "retry_exhausted": retry_exhausted,
    }


def _alert_summary(
    *,
    connector_jobs_by_status: dict[str, int],
    webhook_by_status: dict[str, int],
) -> dict[str, object]:
    items: list[dict[str, object]] = []
    _append_alert(
        items,
        code="connector_failed",
        count=connector_jobs_by_status.get("failed", 0),
        threshold="count > 0",
        message="Connector jobs failed recently.",
        next_step=(
            "Run `gcb connector-jobs` and retry due jobs with "
            "`gcb run-imports --retry-failed` after the configured backoff."
        ),
    )
    _append_alert(
        items,
        code="connector_invalid",
        count=connector_jobs_by_status.get("invalid", 0),
        threshold="count > 0",
        message="Connector jobs were rejected as malformed or unsupported.",
        next_step=(
            "Run `gcb connector-jobs`, inspect the raw_output_ref, then fix or "
            "skip the malformed source payload."
        ),
    )
    _append_alert(
        items,
        code="webhook_pending",
        count=webhook_by_status.get("pending", 0),
        threshold="count > 0",
        message="Webhook events are waiting to be processed.",
        next_step=(
            "Run `gcb webhook-events --status pending`, then process due events "
            "with `gcb webhook-process`."
        ),
    )
    _append_alert(
        items,
        code="webhook_failed",
        count=webhook_by_status.get("failed", 0),
        threshold="count > 0",
        message="Webhook events failed processing.",
        next_step=(
            "Run `gcb webhook-events --status failed`, inspect the error class, "
            "then retry or quarantine the source payload."
        ),
    )
    _append_alert(
        items,
        code="webhook_invalid",
        count=webhook_by_status.get("invalid", 0),
        threshold="count > 0",
        message="Webhook events were rejected as malformed or unsupported.",
        next_step=(
            "Run `gcb webhook-events --status invalid`, inspect the raw payload "
            "ref, then fix the sender or mark the event reviewed."
        ),
    )
    return {
        "status": "needs_attention" if items else "ok",
        "items": items,
    }


def _append_alert(
    items: list[dict[str, object]],
    *,
    code: str,
    count: int,
    threshold: str,
    message: str,
    next_step: str,
) -> None:
    if count <= 0:
        return
    items.append(
        {
            "code": code,
            "severity": "warning",
            "count": count,
            "threshold": threshold,
            "message": message,
            "next_step": next_step,
        }
    )


def _coverage(linked_count: int, total_count: int) -> float:
    if total_count == 0:
        return 0.0
    return round(linked_count / total_count, 4)
