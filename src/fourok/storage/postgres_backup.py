from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from os import environ
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from fourok.storage.health import check_runtime_health

Runner = Callable[..., object]
HealthCheck = Callable[[str], dict[str, object]]


class BackupCommandError(RuntimeError):
    pass


def postgres_backup_command(*, database_url: str, output: Path) -> list[str]:
    if not database_url:
        raise BackupCommandError("PostgreSQL backup requires --database-url")
    return [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-acl",
        "--file",
        str(output),
        _postgres_tool_url(database_url).url,
    ]


def postgres_restore_command(
    *,
    database_url: str,
    input_path: Path,
    confirm_destructive_restore: bool,
) -> list[str]:
    if not database_url:
        raise BackupCommandError("PostgreSQL restore requires --database-url")
    if not confirm_destructive_restore:
        raise BackupCommandError("PostgreSQL restore requires --confirm-destructive-restore")
    if not input_path.exists():
        raise BackupCommandError(f"backup file does not exist: {input_path}")
    return [
        "pg_restore",
        "--clean",
        "--if-exists",
        "--no-owner",
        "--no-acl",
        "--dbname",
        _postgres_tool_url(database_url).url,
        str(input_path),
    ]


def backup_postgres(
    *,
    database_url: str,
    output: Path,
    runner: Runner = subprocess.run,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    completed = runner(
        postgres_backup_command(database_url=database_url, output=output),
        env=_postgres_tool_env(database_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    _raise_for_failure(completed, action="pg_dump")


def restore_postgres(
    *,
    database_url: str,
    input_path: Path,
    confirm_destructive_restore: bool,
    runner: Runner = subprocess.run,
) -> None:
    completed = runner(
        postgres_restore_command(
            database_url=database_url,
            input_path=input_path,
            confirm_destructive_restore=confirm_destructive_restore,
        ),
        env=_postgres_tool_env(database_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    _raise_for_failure(completed, action="pg_restore")


def postgres_restore_drill(
    *,
    database_url: str,
    restore_database_url: str,
    backup_output: Path,
    runner: Runner = subprocess.run,
    health_check: HealthCheck | None = None,
) -> dict[str, object]:
    if not database_url:
        raise BackupCommandError("PostgreSQL restore drill requires --database-url")
    if not restore_database_url:
        raise BackupCommandError("PostgreSQL restore drill requires --restore-database-url")
    if _same_database(database_url, restore_database_url):
        raise BackupCommandError("restore drill database must differ from source database")

    backup_postgres(database_url=database_url, output=backup_output, runner=runner)
    restore_postgres(
        database_url=restore_database_url,
        input_path=backup_output,
        confirm_destructive_restore=True,
        runner=runner,
    )
    health = (health_check or restored_database_health)(restore_database_url)
    if health.get("status") != "ok":
        raise BackupCommandError(f"restore drill health check failed: {health}")
    return {
        "status": "completed",
        "backup": str(backup_output),
        "restore_database": _postgres_tool_url(restore_database_url).url,
        "health": health,
    }


def restored_database_health(database_url: str) -> dict[str, object]:
    engine = create_engine(database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    state = _HealthState(engine=engine)
    report = check_runtime_health(state)
    if report["status"] == "ok":
        report["source_record_count"] = _source_record_count(engine)
    engine.dispose()
    return report


class PostgresToolUrl:
    def __init__(self, *, url: str, password: str) -> None:
        self.url = url
        self.password = password


def _postgres_tool_url(database_url: str) -> PostgresToolUrl:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    if not parsed.password:
        return PostgresToolUrl(url=urlunsplit(parsed), password="")

    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    user = quote(unquote(parsed.username or ""), safe="")
    netloc = f"{user}@{host}" if user else host
    return PostgresToolUrl(
        url=urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment)),
        password=unquote(parsed.password),
    )


def _postgres_tool_env(database_url: str) -> dict[str, str]:
    tool_url = _postgres_tool_url(database_url)
    env = dict(environ)
    if tool_url.password:
        env["PGPASSWORD"] = tool_url.password
    return env


@dataclass(frozen=True)
class _HealthState:
    engine: Engine
    raw_store: object | None = None


def _source_record_count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text("SELECT count(*) FROM source_records")).scalar_one())


def _same_database(first_url: str, second_url: str) -> bool:
    first = _database_identity(first_url)
    second = _database_identity(second_url)
    return first == second


def _database_identity(database_url: str) -> tuple[str, str, int | None, str]:
    parsed = urlsplit(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    path = parsed.path.strip("/")
    return (
        parsed.scheme,
        (parsed.hostname or "").lower(),
        parsed.port,
        path,
    )


def _raise_for_failure(completed: object, *, action: str) -> None:
    returncode = getattr(completed, "returncode", 0)
    if returncode == 0:
        return
    stderr = str(getattr(completed, "stderr", ""))
    raise BackupCommandError(f"{action} failed with status {returncode}: {_tail(stderr)}")


def _tail(value: str, *, limit: int = 2000) -> str:
    if len(value) <= limit:
        return value
    return value[-limit:]
