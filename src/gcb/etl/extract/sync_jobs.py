from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import Table


@dataclass(frozen=True)
class ConnectorJobRun:
    job_id: str
    connector_name: str
    status: str
    attempt: int
    started_at: str
    finished_at: str
    input_state: dict[str, Any]
    output_state: dict[str, Any]
    raw_output_ref: str
    error: str


@dataclass(frozen=True)
class ConnectorRetryPlan:
    attempt: int
    earliest_retry_at: str


@dataclass(frozen=True)
class ConnectorJobStart:
    started: ConnectorJobRun | None
    running: dict[str, Any] | None


def try_start_connector_job(
    engine: Engine,
    *,
    job_runs: Table,
    connector_states: Table,
    connector_name: str,
    job_id: str | None = None,
    attempt: int = 1,
    input_state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ConnectorJobStart:
    try:
        return ConnectorJobStart(
            started=start_connector_job(
                engine,
                job_runs=job_runs,
                connector_states=connector_states,
                connector_name=connector_name,
                job_id=job_id,
                attempt=attempt,
                input_state=input_state,
                now=now,
            ),
            running=None,
        )
    except IntegrityError:
        return ConnectorJobStart(
            started=None,
            running=running_connector_job(
                engine,
                job_runs=job_runs,
                connector_name=connector_name,
            ),
        )


def start_connector_job(
    engine: Engine,
    *,
    job_runs: Table,
    connector_states: Table,
    connector_name: str,
    job_id: str | None = None,
    attempt: int = 1,
    input_state: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> ConnectorJobRun:
    if input_state is None:
        input_state = connector_checkpoint(
            engine,
            connector_states,
            connector_name=connector_name,
        )
    run = ConnectorJobRun(
        job_id=job_id or str(uuid4()),
        connector_name=connector_name,
        status="running",
        attempt=attempt,
        started_at=_timestamp(now),
        finished_at="",
        input_state=input_state,
        output_state={},
        raw_output_ref="",
        error="",
    )
    with engine.begin() as connection:
        connection.execute(
            job_runs.insert().values(
                job_id=run.job_id,
                connector_name=run.connector_name,
                status=run.status,
                attempt=run.attempt,
                started_at=run.started_at,
                finished_at=run.finished_at,
                input_state_json=_state_json(run.input_state),
                output_state_json=_state_json(run.output_state),
                raw_output_ref=run.raw_output_ref,
                error=run.error,
            )
        )
    return run


def running_connector_job(
    engine: Engine,
    *,
    job_runs: Table,
    connector_name: str,
) -> dict[str, Any] | None:
    with engine.begin() as connection:
        row = (
            connection.execute(
                select(job_runs)
                .where(job_runs.c.connector_name == connector_name)
                .where(job_runs.c.status == "running")
                .order_by(job_runs.c.started_at.desc(), job_runs.c.job_id.desc())
            )
            .mappings()
            .first()
        )
    return _job_row(row) if row is not None else None


def complete_connector_job(
    engine: Engine,
    *,
    job_runs: Table,
    connector_states: Table,
    job_id: str,
    connector_name: str,
    output_state: dict[str, Any],
    raw_output_ref: str = "",
    now: datetime | None = None,
) -> None:
    finished_at = _timestamp(now)
    with engine.begin() as connection:
        connection.execute(
            update(job_runs)
            .where(job_runs.c.job_id == job_id)
            .values(
                status="succeeded",
                finished_at=finished_at,
                output_state_json=_state_json(output_state),
                raw_output_ref=raw_output_ref,
                error="",
            )
        )
        connection.execute(
            delete(connector_states).where(connector_states.c.connector_name == connector_name)
        )
        connection.execute(
            connector_states.insert().values(
                connector_name=connector_name,
                state_json=_state_json(output_state),
                updated_at=finished_at,
            )
        )


def fail_connector_job(
    engine: Engine,
    job_runs: Table,
    *,
    job_id: str,
    error: str,
    now: datetime | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(job_runs)
            .where(job_runs.c.job_id == job_id)
            .values(status="failed", finished_at=_timestamp(now), error=error)
        )


def mark_connector_job_invalid(
    engine: Engine,
    job_runs: Table,
    *,
    job_id: str,
    error: str,
    raw_output_ref: str = "",
    now: datetime | None = None,
) -> None:
    with engine.begin() as connection:
        connection.execute(
            update(job_runs)
            .where(job_runs.c.job_id == job_id)
            .values(
                status="invalid",
                finished_at=_timestamp(now),
                raw_output_ref=raw_output_ref,
                error=error,
            )
        )


def connector_checkpoint(
    engine: Engine,
    connector_states: Table,
    *,
    connector_name: str,
) -> dict[str, Any]:
    with engine.begin() as connection:
        row = (
            connection.execute(
                select(connector_states.c.state_json).where(
                    connector_states.c.connector_name == connector_name
                )
            )
            .mappings()
            .first()
        )
    if row is None:
        return {}
    return _state_dict(row["state_json"])


def connector_job_runs(engine: Engine, job_runs: Table) -> list[dict[str, Any]]:
    with engine.begin() as connection:
        rows = connection.execute(select(job_runs).order_by(job_runs.c.job_id)).mappings().all()
    return [_job_row(row) for row in rows]


def connector_retry_plan(
    job_history: list[dict[str, Any]],
    *,
    connector_name: str,
    base_delay_seconds: int,
) -> ConnectorRetryPlan | None:
    latest_run = _latest_connector_run(job_history, connector_name=connector_name)
    if latest_run is None or latest_run["status"] != "failed":
        return None

    attempt = int(latest_run["attempt"]) + 1
    failed_at = _retry_anchor_time(latest_run)
    delay_seconds = base_delay_seconds * (2 ** (attempt - 2))
    return ConnectorRetryPlan(
        attempt=attempt,
        earliest_retry_at=_timestamp(failed_at + timedelta(seconds=delay_seconds)),
    )


def _job_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": row["job_id"],
        "connector_name": row["connector_name"],
        "status": row["status"],
        "attempt": row["attempt"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "input_state": _state_dict(row["input_state_json"]),
        "output_state": _state_dict(row["output_state_json"]),
        "raw_output_ref": row["raw_output_ref"],
        "error": row["error"],
    }


def _latest_connector_run(
    job_history: list[dict[str, Any]],
    *,
    connector_name: str,
) -> dict[str, Any] | None:
    runs = [run for run in job_history if run["connector_name"] == connector_name]
    if not runs:
        return None
    return max(runs, key=_run_sort_key)


def _run_sort_key(run: dict[str, Any]) -> tuple[str, str, str]:
    return (run["started_at"], run["finished_at"], run["job_id"])


def _retry_anchor_time(run: dict[str, Any]) -> datetime:
    anchor = run["finished_at"] or run["started_at"]
    if not anchor:
        raise ValueError("failed connector job must have a timestamp to compute retry timing")
    return datetime.fromisoformat(anchor)


def _timestamp(value: datetime | None) -> str:
    if value is None:
        value = datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _state_json(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _state_dict(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("connector state must be a JSON object")
    return parsed
