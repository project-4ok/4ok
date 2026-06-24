from __future__ import annotations

from typing import Any, Protocol

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from gcb.storage.raw_store import FileRawSourceStore


class RuntimeHealthState(Protocol):
    @property
    def engine(self) -> Engine: ...

    @property
    def raw_store(self) -> FileRawSourceStore | None: ...


def check_runtime_health(state: RuntimeHealthState) -> dict[str, Any]:
    checks = [_database_check(state)]
    if checks[0]["status"] == "ok":
        checks.append(_count_check(state, "source_records", "lifecycle_state = 'active'"))
        checks.append(_count_check(state, "retrieval_records", "status = 'current'"))
    return {
        "status": "ok" if all(check["status"] == "ok" for check in checks) else "failed",
        "checks": checks,
    }


def _database_check(state: RuntimeHealthState) -> dict[str, Any]:
    try:
        with state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as error:
        return {
            "name": "database",
            "status": "failed",
            "detail": str(error),
            "dialect": state.engine.dialect.name,
        }

    return {
        "name": "database",
        "status": "ok",
        "detail": "connected",
        "dialect": state.engine.dialect.name,
    }


def _count_check(state: RuntimeHealthState, table_name: str, where_clause: str) -> dict[str, Any]:
    if not inspect(state.engine).has_table(table_name):
        return {
            "name": table_name,
            "status": "failed",
            "detail": f"{table_name} table missing",
            "count": 0,
        }
    with state.engine.connect() as connection:
        count = int(
            connection.execute(
                text(f"SELECT count(*) FROM {table_name} WHERE {where_clause}")
            ).scalar_one()
        )
    if count < 1:
        return {
            "name": table_name,
            "status": "failed",
            "detail": _empty_detail(table_name),
            "count": 0,
        }
    return {
        "name": table_name,
        "status": "ok",
        "detail": _ready_detail(table_name),
        "count": count,
    }


def _empty_detail(table_name: str) -> str:
    if table_name == "source_records":
        return "no active source records found"
    if table_name == "retrieval_records":
        return "no current retrieval records found"
    return f"no {table_name} records found"


def _ready_detail(table_name: str) -> str:
    if table_name == "source_records":
        return "active source records found"
    if table_name == "retrieval_records":
        return "current retrieval records found"
    return f"{table_name} records found"
