from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.sync_jobs import (
    complete_connector_job,
    connector_job_runs,
    fail_connector_job,
    try_start_connector_job,
)

LIVE_INGESTION_SOURCES = ("twenty", "slack", "linear", "google_drive")


class LiveIngestionState(Protocol):
    @property
    def engine(self) -> Engine: ...

    @property
    def connector_states(self) -> Table: ...

    @property
    def connector_job_runs(self) -> Table: ...


def run_live_ingestion_backfill(
    state: LiveIngestionState,
    *,
    sources: tuple[str, ...],
    artifact_dir: Path,
    database_url: str,
    now: datetime | None = None,
    verify_live_db: bool = False,
) -> dict[str, object]:
    requested_sources = _selected_sources(sources)
    source_reports = [
        _run_live_source(
            state,
            source=source,
            artifact_dir=artifact_dir / source,
            database_url=database_url,
            now=now,
            verify_live_db=verify_live_db,
        )
        for source in requested_sources
    ]
    statuses = {str(report["status"]) for report in source_reports}
    if statuses == {"succeeded"}:
        status = "succeeded"
    elif statuses == {"skipped"}:
        status = "skipped"
    else:
        status = "partial"
    return {
        "status": status,
        "sources": source_reports,
    }


def live_ingestion_status(
    state: LiveIngestionState,
    *,
    now: datetime | None = None,
    stale_after_minutes: int = 60,
) -> dict[str, object]:
    current_time = _timestamp_datetime(now)
    jobs = connector_job_runs(state.engine, state.connector_job_runs)
    sources = {
        source: _source_status(
            source,
            jobs=jobs,
            now=current_time,
            stale_after_minutes=stale_after_minutes,
        )
        for source in LIVE_INGESTION_SOURCES
    }
    status = (
        "fresh"
        if all(report["freshness_status"] == "fresh" for report in sources.values())
        else "attention_required"
    )
    return {
        "status": status,
        "stale_after_minutes": stale_after_minutes,
        "sources": sources,
    }


def _run_live_source(
    state: LiveIngestionState,
    *,
    source: str,
    artifact_dir: Path,
    database_url: str,
    now: datetime | None,
    verify_live_db: bool,
) -> dict[str, object]:
    connector_name = _connector_name(source)
    start_result = try_start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name=connector_name,
        now=now,
    )
    if start_result.started is None:
        running_job = start_result.running or {}
        return {
            "source": source,
            "connector_name": connector_name,
            "status": "skipped",
            "reason": "connector_job_already_running",
            "running_job_id": running_job.get("job_id", ""),
        }

    job = start_result.started
    command = [
        "uv",
        "run",
        "--group",
        "pipeline",
        "python",
        "scripts/check_dagster_pipeline.py",
        "--materialize-live-connectors",
        "--live-connector",
        source,
        "--artifact-dir",
        str(artifact_dir),
    ]
    if verify_live_db:
        command.append("--verify-live-db")

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        env=_live_command_env(database_url=database_url),
    )
    if completed.returncode != 0:
        fail_connector_job(
            state.engine,
            state.connector_job_runs,
            job_id=job.job_id,
            error=_safe_process_error(completed),
            now=now,
        )
        return {
            "source": source,
            "connector_name": connector_name,
            "status": "failed",
            "job_id": job.job_id,
            "artifact_dir": str(artifact_dir),
            "error": _safe_process_error(completed),
        }

    output_state = {
        "freshness_status": "fresh",
        "idempotency_status": "recorded",
        **_live_output_counts(completed.stdout),
    }
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name=connector_name,
        output_state=output_state,
        raw_output_ref=str(artifact_dir),
        now=now,
    )
    return {
        "source": source,
        "connector_name": connector_name,
        "status": "succeeded",
        "job_id": job.job_id,
        "artifact_dir": str(artifact_dir),
        "record_count": output_state.get("record_count"),
        "source_record_count": output_state.get("source_record_count"),
        "retrieval_record_count": output_state.get("retrieval_record_count"),
    }


def _source_status(
    source: str,
    *,
    jobs: list[dict[str, Any]],
    now: datetime,
    stale_after_minutes: int,
) -> dict[str, object]:
    connector_name = _connector_name(source)
    source_jobs = [job for job in jobs if job["connector_name"] == connector_name]
    if not source_jobs:
        return {
            "connector_name": connector_name,
            "latest_status": "missing",
            "latest_started_at": "",
            "latest_finished_at": "",
            "age_seconds": None,
            "freshness_status": "missing",
            "idempotency_status": "missing",
            "source_record_count": None,
            "raw_output_ref": "",
            "error": "",
        }

    latest = max(
        source_jobs,
        key=lambda job: (job["started_at"], job["finished_at"], job["job_id"]),
    )
    finished_at = str(latest["finished_at"])
    age_seconds = _age_seconds(finished_at, now) if finished_at else None
    output_state = latest["output_state"]
    freshness_status = str(output_state.get("freshness_status") or latest["status"])
    if latest["status"] != "succeeded":
        freshness_status = str(latest["status"])
    elif age_seconds is not None and age_seconds > stale_after_minutes * 60:
        freshness_status = "stale"
    return {
        "connector_name": connector_name,
        "latest_status": latest["status"],
        "latest_started_at": latest["started_at"],
        "latest_finished_at": finished_at,
        "age_seconds": age_seconds,
        "freshness_status": freshness_status,
        "idempotency_status": output_state.get("idempotency_status", ""),
        "source_record_count": output_state.get("source_record_count"),
        "raw_output_ref": latest["raw_output_ref"],
        "error": latest["error"],
    }


def _selected_sources(sources: tuple[str, ...]) -> tuple[str, ...]:
    if sources == ("all",):
        return LIVE_INGESTION_SOURCES
    invalid = sorted(set(sources) - set(LIVE_INGESTION_SOURCES))
    if invalid:
        raise ValueError(f"unsupported live ingestion source: {', '.join(invalid)}")
    return sources


def _connector_name(source: str) -> str:
    return f"{source}-live"


def _live_output_counts(stdout: str) -> dict[str, int]:
    keys = {
        "record_count",
        "source_record_count",
        "retrieval_record_count",
        "live_db_source_records_delta",
        "live_db_retrieval_records_delta",
    }
    counts: dict[str, int] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key in keys:
            try:
                counts[key] = int(value)
            except ValueError:
                continue
    return counts


def _safe_process_error(completed: subprocess.CompletedProcess[str]) -> str:
    lines = [line.strip() for line in (completed.stderr or completed.stdout).splitlines()]
    visible_lines = [line for line in lines if line]
    detail = visible_lines[-1] if visible_lines else "live Dagster materialization failed"
    return f"exit_code={completed.returncode} {detail}"


def _live_command_env(*, database_url: str) -> dict[str, str] | None:
    if not database_url:
        return None
    import os

    return {**os.environ, "FOUROK_DATABASE_URL": database_url}


def _timestamp_datetime(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def _age_seconds(finished_at: str, now: datetime) -> int:
    finished = datetime.fromisoformat(finished_at)
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    return int((now - finished).total_seconds())
