from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError

from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.storage.health import check_runtime_health

DEFAULT_DAGSTER_URL = "http://127.0.0.1:3001/server_info"
DEFAULT_ERROR_WINDOW_SECONDS = 3600
ERROR_MARKERS = ("ERROR", "CRITICAL", "FATAL", "Traceback", "Exception")
LOG_SUFFIXES = (".log", ".err", ".out", ".jsonl")
PROJECT_LOG_ROOTS = (".local", "logs", "var/log/fourok")

CommandRunner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def agent_diagnostics(
    *,
    project_root: Path = Path("."),
    now: datetime | None = None,
    since_seconds: int = DEFAULT_ERROR_WINDOW_SECONDS,
    dagster_url: str = DEFAULT_DAGSTER_URL,
    state_path: Path = Path(".local/context.sqlite"),
    database_url: str | None = None,
    raw_store_path: Path | None = None,
    runner: CommandRunner | None = None,
) -> dict[str, object]:
    root = project_root.resolve()
    generated_at = _now(now).isoformat()
    recent_errors = find_recent_errors(root, now=_now(now), since_seconds=since_seconds)

    checks = [
        _recent_errors_check(recent_errors),
        _docker_pipeline_check(root, runner=runner),
        _dagster_check(dagster_url),
        _database_check(root, state_path=state_path, database_url=database_url),
        _raw_store_check(root, raw_store_path=raw_store_path),
        _search_check(root, state_path=state_path, database_url=database_url),
    ]
    next_commands = _dedupe_commands(
        ["uv run fourok-dev agent-diagnostics --json"]
        + [command for check in checks for command in check["next_commands"]]
    )
    return {
        "checks": checks,
        "generated_at": generated_at,
        "next_commands": next_commands,
        "project_root": str(root),
        "recent_errors": recent_errors,
        "status": _rollup_status(checks),
    }


def find_recent_errors(
    project_root: Path,
    *,
    now: datetime | None = None,
    since_seconds: int = DEFAULT_ERROR_WINDOW_SECONDS,
) -> dict[str, object]:
    current = _now(now)
    cutoff = current - timedelta(seconds=since_seconds)
    entries: list[dict[str, object]] = []
    for path in _candidate_log_paths(project_root):
        with suppress(OSError):
            modified_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified_at < cutoff:
                continue
            entries.extend(_error_entries(project_root, path, modified_at))
    entries.sort(key=lambda entry: (str(entry["path"]), int(entry["line_number"])))
    return {
        "count": len(entries),
        "entries": entries[:50],
        "window_seconds": since_seconds,
    }


def _candidate_log_paths(project_root: Path) -> list[Path]:
    paths: list[Path] = []
    for root_name in PROJECT_LOG_ROOTS:
        root = project_root / root_name
        if not root.exists():
            continue
        paths.extend(
            path for path in root.rglob("*") if path.is_file() and path.suffix in LOG_SUFFIXES
        )
    return sorted(paths)


def _error_entries(
    project_root: Path,
    path: Path,
    modified_at: datetime,
) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            marker = _matched_marker(line)
            if marker is None:
                continue
            entries.append(
                {
                    "path": path.relative_to(project_root).as_posix(),
                    "line_number": line_number,
                    "matched": marker,
                    "modified_at": modified_at.isoformat(),
                }
            )
    return entries


def _matched_marker(line: str) -> str | None:
    return next((marker for marker in ERROR_MARKERS if marker in line), None)


def _recent_errors_check(recent_errors: dict[str, object]) -> dict[str, object]:
    count = int(recent_errors["count"])
    return {
        "detail": {
            "count": count,
            "window_seconds": recent_errors["window_seconds"],
        },
        "name": "recent_errors",
        "next_commands": ["find .local -type f -mtime -1 -name '*.log' -print"],
        "status": "warning" if count else "ok",
    }


def _docker_pipeline_check(
    project_root: Path, *, runner: CommandRunner | None
) -> dict[str, object]:
    command = ("docker", "compose", "--profile", "pipeline", "ps", "--services")
    try:
        result = _run(command, cwd=project_root, runner=runner)
    except (OSError, subprocess.SubprocessError) as error:
        return _check(
            "docker_pipeline",
            "warning",
            {"detail": str(error), "services": []},
            ["uv run fourok-dev pipeline-ps", "uv run fourok-dev pipeline-up"],
        )
    services = [line for line in result.stdout.splitlines() if line]
    status = "ok" if result.returncode == 0 else "warning"
    return _check(
        "docker_pipeline",
        status,
        {
            "returncode": result.returncode,
            "services": services,
        },
        ["uv run fourok-dev pipeline-ps", "uv run fourok-dev pipeline-up"],
    )


def _dagster_check(dagster_url: str) -> dict[str, object]:
    try:
        with urllib.request.urlopen(dagster_url, timeout=2) as response:
            status_code = response.status
    except (OSError, urllib.error.URLError) as error:
        return _check(
            "dagster",
            "warning",
            {"detail": str(error), "url": dagster_url},
            ["uv run fourok-dev pipeline-up", "uv run fourok-dev pipeline-ps"],
        )
    return _check(
        "dagster",
        "ok" if 200 <= status_code < 300 else "warning",
        {"status_code": status_code, "url": dagster_url},
        ["uv run fourok-dev pipeline-ps"],
    )


def _database_check(
    project_root: Path,
    *,
    state_path: Path,
    database_url: str | None,
) -> dict[str, object]:
    resolved_state = _resolve_project_path(project_root, state_path)
    if not database_url and not resolved_state.exists():
        return _check(
            "database",
            "skipped",
            {"reason": "no FOUR_OK_DATABASE_URL and no local state database"},
            ["uv run fourok health --state .local/context.sqlite"],
        )
    try:
        state = create_governed_context_state(
            state_path=resolved_state,
            database_url=database_url,
        )
        report = check_runtime_health(state)
    except (OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
        return _check(
            "database",
            "failed",
            {"detail": str(error)},
            ["uv run fourok health --state .local/context.sqlite"],
        )
    database = next(check for check in report["checks"] if check["name"] == "database")
    return _check(
        "database",
        str(database["status"]),
        {
            "detail": database.get("detail"),
            "dialect": database.get("dialect"),
        },
        ["uv run fourok health --state .local/context.sqlite"],
    )


def _raw_store_check(project_root: Path, *, raw_store_path: Path | None) -> dict[str, object]:
    candidates = [raw_store_path] if raw_store_path is not None else [Path(".local/raw")]
    path = _resolve_project_path(project_root, candidates[0])
    if not path.exists():
        return _check(
            "raw_store",
            "skipped",
            {"path": str(path), "reason": "raw store path is not present"},
            ["uv run fourok health --raw-store .local/raw"],
        )
    return _check(
        "raw_store",
        "ok" if path.is_dir() else "failed",
        {"path": str(path)},
        ["uv run fourok health --raw-store .local/raw"],
    )


def _search_check(
    project_root: Path,
    *,
    state_path: Path,
    database_url: str | None,
) -> dict[str, object]:
    resolved_state = _resolve_project_path(project_root, state_path)
    if not database_url and not resolved_state.exists():
        return _check(
            "search",
            "skipped",
            {"reason": "no database surface available for search probe"},
            ['uv run fourok search-state "diagnostic health probe" --state .local/context.sqlite'],
        )
    try:
        context = GovernedContext(resolved_state, database_url=database_url)
        response = context.search_context("diagnostic health probe", limit=1)
    except (OSError, RuntimeError, SQLAlchemyError, ValueError) as error:
        return _check(
            "search",
            "failed",
            {"detail": str(error)},
            ['uv run fourok search-state "diagnostic health probe" --state .local/context.sqlite'],
        )
    return _check(
        "search",
        "ok",
        {"result_count": len(response.results)},
        ['uv run fourok search-state "diagnostic health probe" --state .local/context.sqlite'],
    )


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    runner: CommandRunner | None,
) -> subprocess.CompletedProcess[str]:
    if runner is not None:
        return runner(command)
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=5, check=False)


def _check(
    name: str,
    status: str,
    detail: dict[str, object],
    next_commands: list[str],
) -> dict[str, object]:
    return {
        "detail": detail,
        "name": name,
        "next_commands": next_commands,
        "status": status,
    }


def _rollup_status(checks: list[dict[str, object]]) -> str:
    statuses = {check["status"] for check in checks}
    if "failed" in statuses:
        return "failed"
    if "warning" in statuses:
        return "warning"
    return "ok"


def _dedupe_commands(commands: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for command in commands:
        if command in seen:
            continue
        seen.add(command)
        deduped.append(command)
    return deduped


def _resolve_project_path(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else project_root / path


def _now(now: datetime | None) -> datetime:
    if now is None:
        return datetime.now(tz=UTC)
    if now.tzinfo is None:
        return now.replace(tzinfo=UTC)
    return now.astimezone(UTC)
