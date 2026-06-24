from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fourok.governance import GovernedContext

LIVE_OPERATOR_ASSETS = [
    "meltano_slack_live_raw_landing",
    "fourok_slack_live_source_records_from_raw_landing",
    "meltano_twenty_live_raw_landing",
    "fourok_twenty_live_source_records_from_raw_landing",
    "meltano_linear_live_raw_landing",
    "fourok_linear_live_source_records_from_raw_landing",
    "meltano_google_drive_live_raw_landing",
    "fourok_google_drive_live_source_records_from_raw_landing",
]

DAGSTER_START_COMMAND = [
    "docker",
    "compose",
    "--profile",
    "pipeline",
    "up",
    "--build",
    "--force-recreate",
    "-d",
    "postgres",
    "dagster-postgres",
    "dagster-code",
    "dagster-webserver",
    "dagster-daemon",
]
DAGSTER_STATUS_COMMAND = ["docker", "compose", "--profile", "pipeline", "ps"]


def main(argv: Sequence[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    project_root = args.project_root.resolve()
    env = operator_environment(project_root)
    database_url = args.database_url or env.get("FOUROK_DATABASE_URL", "")

    if args.dry_run:
        print(
            json.dumps(
                build_operator_live_dry_run(
                    project_root=project_root,
                    raw_landing=args.raw_landing,
                    state_path=args.state,
                    database_url=host_database_url(database_url),
                    start_dagster=not args.no_start_dagster,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return

    report = run_operator_live(
        project_root=project_root,
        raw_landing=args.raw_landing,
        state_path=args.state,
        database_url=database_url,
        start_dagster=not args.no_start_dagster,
        env=env,
    )
    print(json.dumps(report, indent=2, sort_keys=True))


def build_operator_live_dry_run(
    *,
    project_root: Path,
    raw_landing: Path,
    state_path: Path,
    database_url: str,
    start_dagster: bool,
) -> dict[str, object]:
    return {
        "mode": "dry-run",
        "dagster": {
            "start_command": DAGSTER_START_COMMAND if start_dagster else [],
            "status_command": DAGSTER_STATUS_COMMAND,
            "status": "not_started",
        },
        "raw_landing_path": str(_project_path(project_root, raw_landing)),
        "fourok_database_url": redacted_database_url(database_url),
        "state_path": str(_project_path(project_root, state_path)),
        "live_assets": LIVE_OPERATOR_ASSETS,
        "source_record_counts_by_source_system": {},
        "retrieval_count": 0,
    }


def run_operator_live(
    *,
    project_root: Path,
    raw_landing: Path,
    state_path: Path,
    database_url: str,
    start_dagster: bool,
    env: Mapping[str, str],
) -> dict[str, object]:
    run_env = dict(env)
    run_env["FOUROK_PROJECT_ROOT"] = str(project_root)
    run_env["FOUROK_RAW_LANDING_DIR"] = str(_project_path(project_root, raw_landing))
    run_env["FOUROK_STATE_PATH"] = str(_project_path(project_root, state_path))
    if database_url:
        run_env["FOUROK_DATABASE_URL"] = database_url

    dagster_status: dict[str, object] = {"status": "starting" if start_dagster else "skipped"}
    if start_dagster:
        subprocess.run(DAGSTER_START_COMMAND, cwd=project_root, env=run_env, check=True)
        dagster_status["start"] = "succeeded"

    ps = subprocess.run(
        DAGSTER_STATUS_COMMAND,
        cwd=project_root,
        env=run_env,
        check=True,
        capture_output=True,
        text=True,
    )
    dagster_status["compose_status"] = "checked"
    dagster_status["compose_ps"] = [line for line in ps.stdout.splitlines() if line]

    materialize_database_url = host_database_url(database_url)
    _materialize_live_assets(
        project_root=project_root,
        raw_landing=_project_path(project_root, raw_landing),
        state_path=_project_path(project_root, state_path),
        database_url=materialize_database_url,
        env=run_env,
    )
    dagster_status["status"] = "materialized"
    dagster_status["assets"] = LIVE_OPERATOR_ASSETS

    report = build_operator_live_report(
        project_root=project_root,
        raw_landing=raw_landing,
        state_path=state_path,
        database_url=materialize_database_url,
        dagster_status=str(dagster_status["status"]),
        dagster_assets=LIVE_OPERATOR_ASSETS,
    )
    report["dagster"].update(dagster_status)  # type: ignore[union-attr]
    return report


def build_operator_live_report(
    *,
    project_root: Path,
    raw_landing: Path,
    state_path: Path,
    database_url: str,
    dagster_status: str,
    dagster_assets: Sequence[str],
) -> dict[str, object]:
    context = GovernedContext(
        _project_path(project_root, state_path),
        database_url=database_url or None,
    )
    source_records = [
        row for row in context.source_records() if row.get("lifecycle_state") == "active"
    ]
    retrieval_units = context.retrieval_units()
    return {
        "mode": "live",
        "dagster": {
            "status": dagster_status,
            "assets": list(dagster_assets),
        },
        "raw_landing_path": str(_project_path(project_root, raw_landing)),
        "fourok_database_url": redacted_database_url(database_url),
        "state_path": str(_project_path(project_root, state_path)),
        "source_record_counts_by_source_system": _count_by(source_records, "source_system"),
        "retrieval_count": len(retrieval_units),
    }


def operator_environment(project_root: Path) -> dict[str, str]:
    env = {**_dotenv_values(project_root / ".env"), **os.environ}
    env.setdefault("DAGSTER_POSTGRES_PASSWORD", "local-check")
    env.setdefault("POSTGRES_PASSWORD", "local-check")
    env.setdefault(
        "FOUROK_DATABASE_URL",
        f"postgresql+psycopg://fourok:{env['POSTGRES_PASSWORD']}@postgres:5432/fourok",
    )
    env.setdefault("FOUROK_OBSERVABILITY_ENABLED", "true")
    env.setdefault("OTEL_EXPORTER_OTLP_ENDPOINT", "http://observability:4318")
    return env


def host_database_url(database_url: str) -> str:
    if not database_url:
        return ""
    parsed = urlsplit(database_url)
    if parsed.hostname != "postgres":
        return database_url

    host = "127.0.0.1"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"
    return urlunsplit(
        (parsed.scheme, f"{userinfo}{host}", parsed.path, parsed.query, parsed.fragment)
    )


def redacted_database_url(database_url: str) -> str:
    if not database_url:
        return ""
    parsed = urlsplit(database_url)
    netloc = parsed.netloc
    if parsed.password is not None:
        host = parsed.hostname or ""
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        user = parsed.username or ""
        netloc = f"{user}:[REDACTED]@{host}" if user else host

    query = urlencode(
        [
            (key, "[REDACTED]" if _is_sensitive_key(key) else value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ],
        safe="[]",
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, query, parsed.fragment))


def _materialize_live_assets(
    *,
    project_root: Path,
    raw_landing: Path,
    state_path: Path,
    database_url: str,
    env: Mapping[str, str],
) -> None:
    from dagster import materialize

    module = _load_dagster_definitions(project_root)
    assets = [getattr(module, name) for name in LIVE_OPERATOR_ASSETS]
    with _temporary_environ(env):
        result = materialize(
            assets,
            resources={
                "raw_landing": module.RawLandingResource(path=str(raw_landing)),
                "meltano_project": module.MeltanoProjectResource(project_root=str(project_root)),
                "fourok_runtime": module.FourokRuntimeResource(
                    state_path=str(state_path),
                    database_url=database_url,
                ),
                "connector_env": module.ConnectorEnvResource(
                    dotenv_path=env.get("FOUROK_DOTENV_PATH", ".env"),
                    load_dotenv=_truthy(env.get("FOUROK_LOAD_DOTENV", "true")),
                ),
            },
        )
    if not result.success:
        raise RuntimeError("Dagster live materialization failed")


def _load_dagster_definitions(project_root: Path) -> Any:
    path = project_root / "deploy" / "dagster" / "definitions.py"
    spec = importlib.util.spec_from_file_location("fourok_operator_dagster_definitions", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load Dagster definitions from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def _temporary_environ(env: Mapping[str, str]) -> Iterator[None]:
    previous = os.environ.copy()
    os.environ.update(env)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(previous)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fourok.runtime.operator_live")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--project-root", type=Path, default=Path("."))
    parser.add_argument("--raw-landing", type=Path, default=Path(".local/raw/singer"))
    parser.add_argument("--state", type=Path, default=Path(".local/dagster/fourok-state.sqlite"))
    parser.add_argument("--database-url", default="")
    parser.add_argument("--no-start-dagster", action="store_true")
    return parser


def _project_path(project_root: Path, path: Path) -> Path:
    return path if path.is_absolute() else project_root / path


def _count_by(rows: list[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _dotenv_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _copy_if_missing(env: dict[str, str], target: str, source: str) -> None:
    if target not in env and env.get(source):
        env[target] = env[source]


def _first_env(env: Mapping[str, str], *names: str, default: str = "") -> str:
    for name in names:
        value = env.get(name, "")
        if value:
            return value
    return default


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_sensitive_key(key: str) -> bool:
    return any(token in key.upper() for token in ("PASSWORD", "SECRET", "TOKEN", "API_KEY"))


if __name__ == "__main__":
    main()
