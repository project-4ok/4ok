from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.storage.config import RuntimeConfig


class RetentionStatusState(Protocol):
    engine: Engine
    source_lifecycle: Table
    source_records: Table
    retrieval_records: Table
    webhook_events: Table
    audit_events: Table


def retention_status(
    state: RetentionStatusState,
    config: RuntimeConfig,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    effective_now = now or datetime.now(UTC)
    return {
        "policy": {
            "raw_source_days": config.retention.raw_source_days,
            "audit_event_days": config.retention.audit_event_days,
            "backup_days": config.retention.backup_days,
            "webhook_backlog_days": config.retention.webhook_backlog_days,
        },
        "surfaces": {
            "raw_sources": _raw_source_status(state, config, now=effective_now),
            "source_records": _source_records_status(state),
            "retrieval_units": _retrieval_units_status(state),
            "webhook_backlog": _webhook_backlog_status(state, config, now=effective_now),
            "audit_events": _audit_event_status(state, config, now=effective_now),
            "telemetry": {
                "status": "external",
                "scope": "managed by the configured OpenTelemetry backend",
            },
            "backups": _backup_status(config, now=effective_now),
        },
    }


def _source_records_status(state: RetentionStatusState) -> dict[str, Any]:
    return {
        "status": "configured",
        "retention_days": None,
        "total": _count_rows(state.engine, state.source_records),
        "by_lifecycle_state": _count_by_column(
            state.engine,
            state.source_records,
            state.source_records.c.lifecycle_state,
        ),
        "delete_command": None,
        "scope": "source records are retained or hidden through source lifecycle changes",
    }


def _retrieval_units_status(state: RetentionStatusState) -> dict[str, Any]:
    return {
        "status": "configured",
        "retention_days": None,
        "total": _count_rows(state.engine, state.retrieval_records),
        "by_status": _count_by_column(
            state.engine,
            state.retrieval_records,
            state.retrieval_records.c.status,
        ),
        "delete_command": None,
        "scope": "retrieval units are derived from source records and rebuilt or marked inactive",
    }


def _raw_source_status(
    state: RetentionStatusState,
    config: RuntimeConfig,
    *,
    now: datetime,
) -> dict[str, Any]:
    retention_days = config.retention.raw_source_days
    if retention_days is None:
        return _not_configured_surface("raw source retention window is not configured")

    cutoff = now - timedelta(days=retention_days)
    statement = (
        select(func.count())
        .select_from(state.source_lifecycle)
        .where(
            state.source_lifecycle.c.state == "restricted",
            state.source_lifecycle.c.recorded_at != "",
            state.source_lifecycle.c.recorded_at <= cutoff.isoformat(),
        )
    )
    return {
        "status": "configured",
        "retention_days": retention_days,
        "eligible_for_deletion": _scalar_count(state.engine, statement),
        "delete_command": "purge-raw-retention",
        "scope": "restricted raw source objects only",
    }


def _audit_event_status(
    state: RetentionStatusState,
    config: RuntimeConfig,
    *,
    now: datetime,
) -> dict[str, Any]:
    retention_days = config.retention.audit_event_days
    if retention_days is None:
        return _not_configured_surface("audit retention window is not configured")

    cutoff = now - timedelta(days=retention_days)
    statement = (
        select(func.count())
        .select_from(state.audit_events)
        .where(
            state.audit_events.c.recorded_at != "",
            state.audit_events.c.recorded_at < cutoff.isoformat(),
        )
    )
    return {
        "status": "configured",
        "retention_days": retention_days,
        "eligible_for_deletion": _scalar_count(state.engine, statement),
        "delete_command": "purge-audit-retention",
        "scope": "audit events older than the retention window",
    }


def purge_expired_backups(
    *,
    backup_path: Path,
    retention_days: int,
    now: datetime | None = None,
) -> list[str]:
    if retention_days < 0:
        raise ValueError("backup retention days must be non-negative")
    purged: list[str] = []
    for backup_file in _backup_dump_files(backup_path):
        if _backup_file_expired(backup_file, retention_days=retention_days, now=now):
            backup_file.unlink()
            purged.append(str(backup_file))
    return purged


def purge_expired_webhook_events(
    state: RetentionStatusState,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    if retention_days < 0:
        raise ValueError("webhook backlog retention days must be non-negative")
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    statement = (
        delete(state.webhook_events)
        .where(state.webhook_events.c.status.in_(["succeeded", "failed", "invalid"]))
        .where(state.webhook_events.c.processed_at != "")
        .where(state.webhook_events.c.processed_at < cutoff.isoformat())
    )
    with state.engine.begin() as connection:
        result = connection.execute(statement)
    return int(result.rowcount or 0)


def _webhook_backlog_status(
    state: RetentionStatusState,
    config: RuntimeConfig,
    *,
    now: datetime,
) -> dict[str, Any]:
    retention_days = config.retention.webhook_backlog_days
    total = _count_rows(state.engine, state.webhook_events)
    if retention_days is None:
        return _not_configured_surface(
            "webhook backlog retention window is not configured",
            total=total,
        )

    cutoff = now - timedelta(days=retention_days)
    statement = (
        select(func.count())
        .select_from(state.webhook_events)
        .where(state.webhook_events.c.status.in_(["succeeded", "failed", "invalid"]))
        .where(state.webhook_events.c.processed_at != "")
        .where(state.webhook_events.c.processed_at < cutoff.isoformat())
    )
    return {
        "status": "configured",
        "retention_days": retention_days,
        "total": total,
        "eligible_for_deletion": _scalar_count(state.engine, statement),
        "delete_command": "purge-webhook-retention",
        "scope": "terminal webhook events older than the retention window",
    }


def _backup_status(config: RuntimeConfig, *, now: datetime) -> dict[str, Any]:
    retention_days = config.retention.backup_days
    backup_path = config.backup.path
    if retention_days is None:
        return _not_configured_surface("backup retention window is not configured")
    if backup_path is None:
        return _not_configured_surface("backup retention requires [backup].path")

    dump_files = _backup_dump_files(backup_path)
    return {
        "status": "configured",
        "retention_days": retention_days,
        "total": len(dump_files),
        "eligible_for_deletion": sum(
            1
            for backup_file in dump_files
            if _backup_file_expired(backup_file, retention_days=retention_days, now=now)
        ),
        "delete_command": "purge-backup-retention",
        "path": str(backup_path),
        "scope": "PostgreSQL dump files older than the retention window",
    }


def _backup_dump_files(backup_path: Path) -> list[Path]:
    if not backup_path.exists():
        return []
    return sorted(
        path for path in backup_path.iterdir() if path.is_file() and path.suffix == ".dump"
    )


def _backup_file_expired(
    backup_file: Path,
    *,
    retention_days: int,
    now: datetime | None,
) -> bool:
    effective_now = now or datetime.now(UTC)
    cutoff = effective_now - timedelta(days=retention_days)
    modified_at = datetime.fromtimestamp(backup_file.stat().st_mtime, UTC)
    return modified_at < cutoff


def _not_configured_surface(scope: str, *, total: int | None = None) -> dict[str, Any]:
    surface = {
        "status": "not_configured",
        "retention_days": None,
        "scope": scope,
    }
    if total is not None:
        surface["total"] = total
    return surface


def _count_rows(engine: Engine, table: Table) -> int:
    return _scalar_count(engine, select(func.count()).select_from(table))


def _scalar_count(engine: Engine, statement) -> int:
    with engine.connect() as connection:
        return int(connection.execute(statement).scalar_one())


def _count_by_column(engine: Engine, table: Table, column) -> dict[str, int]:
    statement = select(column, func.count()).select_from(table).group_by(column).order_by(column)
    with engine.connect() as connection:
        return {str(row[0]): int(row[1]) for row in connection.execute(statement)}
