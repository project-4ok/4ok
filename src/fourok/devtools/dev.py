from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path

from fourok.devtools.dagster_status import dagster_status_report
from fourok.devtools.diagnostics import DEFAULT_ERROR_WINDOW_SECONDS, agent_diagnostics

UV_CACHE_DIR = ".scratch/uv-cache"


@dataclass(frozen=True)
class DevStep:
    name: str
    command: tuple[str, ...]
    env: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        data: dict[str, object] = {"name": self.name, "command": list(self.command)}
        if self.env:
            data["env"] = {
                key: _redact_env_value(key, value) for key, value in sorted(self.env.items())
            }
        return data


def build_plan(action: str, extra_args: Sequence[str]) -> list[DevStep]:
    if action == "format":
        return [_format_check()]
    if action == "lint":
        return [_lint()]
    if action == "test":
        return [_pytest(extra_args)]
    if action == "check":
        return [_lint(), _format_check(), _pytest(extra_args), _compose_config(), _whitespace()]
    if action == "fast":
        return build_plan("check", extra_args)
    if action == "full":
        return [
            _lint(),
            _format_check(),
            _file_lengths(),
            _pytest(extra_args),
            _compose_config(),
            _goal_audit(),
            _whitespace(),
        ]
    if action == "compose-config":
        return [_compose_config()]
    if action == "core-up":
        return [_cleanup_smoke_projects(), _core_up()]
    if action == "app-up":
        return [_app_up()]
    if action == "observability-up":
        return [_observability_up()]
    if action == "pipeline-up":
        return [_pipeline_up()]
    if action == "stack-up":
        return build_plan("core-up", extra_args)
    if action == "pipeline-ps":
        return [_pipeline_ps()]
    if action == "operator-live":
        return [_operator_live(extra_args)]
    if action == "warm-docker":
        return [_pull_observability(), _pull_pipeline()]
    raise ValueError(f"unknown dev action: {action}")


def install_hooks(project_root: Path) -> list[Path]:
    hooks_dir = _git_hooks_dir(project_root)
    if not hooks_dir.exists():
        raise FileNotFoundError(f"missing git hooks directory: {hooks_dir}")

    hooks = {
        "pre-commit": "#!/usr/bin/env bash\nset -euo pipefail\n\nuv run fourok-dev check\n",
        "pre-push": "#!/usr/bin/env bash\nset -euo pipefail\n\nuv run fourok-dev full\n",
    }
    written: list[Path] = []
    for name, content in hooks.items():
        path = hooks_dir / name
        path.write_text(content, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fourok-dev")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in (
        "format",
        "lint",
        "test",
        "check",
        "test-tracked",
        "fast",
        "full",
        "compose-config",
        "core-up",
        "app-up",
        "observability-up",
        "pipeline-up",
        "stack-up",
        "pipeline-ps",
        "operator-live",
        "warm-docker",
    ):
        command_parser = subparsers.add_parser(command)
        if command != "operator-live":
            command_parser.add_argument("--dry-run", action="store_true")
        if command in {"test", "check", "fast", "full"}:
            command_parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
        if command == "operator-live":
            command_parser.add_argument("--dry-run", dest="operator_dry_run", action="store_true")
            command_parser.add_argument("--no-start-dagster", action="store_true")
            command_parser.add_argument("--project-root", type=Path)
            command_parser.add_argument("--raw-landing", type=Path)
            command_parser.add_argument("--state", type=Path)
            command_parser.add_argument("--database-url")
            command_parser.add_argument("operator_args", nargs=argparse.REMAINDER)

    install_hooks_parser = subparsers.add_parser("install-hooks")
    install_hooks_parser.add_argument("--project-root", type=Path, default=Path("."))

    diagnostics_parser = subparsers.add_parser(
        "agent-diagnostics",
        help="Print agent-readable local runtime diagnostics.",
    )
    diagnostics_parser.add_argument("--project-root", type=Path, default=Path("."))
    diagnostics_parser.add_argument(
        "--since-seconds",
        type=int,
        default=DEFAULT_ERROR_WINDOW_SECONDS,
        help="Recent error-log detection window.",
    )
    diagnostics_parser.add_argument(
        "--dagster-url",
        default="http://127.0.0.1:3001/server_info",
        help="Dagster webserver health URL.",
    )
    diagnostics_parser.add_argument("--state", type=Path, default=Path(".local/context.sqlite"))
    diagnostics_parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL"))
    diagnostics_parser.add_argument("--raw-store", type=Path)
    diagnostics_parser.add_argument(
        "--json", action="store_true", help="Accepted for agent clarity."
    )

    compose_env_parser = subparsers.add_parser(
        "compose-env",
        help="Print redacted compose/runtime environment resolved by fourok-dev.",
    )
    compose_env_parser.add_argument(
        "--show-secrets",
        action="store_true",
        help="Print raw values. Avoid in logs and agent transcripts.",
    )
    subparsers.add_parser(
        "connector-secrets",
        help="Check whether live connector secret env vars are present without printing values.",
    )

    dagster_status_parser = subparsers.add_parser(
        "dagster-status",
        help="Summarize Dagster repo, schedule/sensor, and latest backfill run status.",
    )
    dagster_status_parser.add_argument(
        "--dagster-url",
        default="http://127.0.0.1:3001/graphql",
        help="Dagster GraphQL URL.",
    )

    logs_status_parser = subparsers.add_parser(
        "logs-status",
        help="Summarize Loki Docker log aggregation status and useful fourok LogQL queries.",
    )
    logs_status_parser.add_argument(
        "--loki-url",
        default="http://127.0.0.1:3100",
        help="Loki base URL. Use http://localhost:3100 inside the observability container.",
    )
    logs_status_parser.add_argument(
        "--since-seconds",
        type=int,
        default=3600,
        help="Range-query window used for log counts.",
    )

    args = parser.parse_args(argv)
    if args.command == "lint":
        _run_ruff("check")
        return
    if args.command == "format":
        _run_ruff("format", "--check")
        return
    if args.command == "test-tracked":
        _run_pytest_tracked()
        return
    if args.command == "install-hooks":
        written = install_hooks(args.project_root)
        print(json.dumps({"status": "ok", "hooks": [str(path) for path in written]}, indent=2))
        return
    if args.command == "agent-diagnostics":
        print(
            json.dumps(
                agent_diagnostics(
                    project_root=args.project_root,
                    since_seconds=args.since_seconds,
                    dagster_url=args.dagster_url,
                    state_path=args.state,
                    database_url=args.database_url,
                    raw_store_path=args.raw_store,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command == "compose-env":
        print(
            json.dumps(compose_env_report(redact=not args.show_secrets), indent=2, sort_keys=True)
        )
        return
    if args.command == "connector-secrets":
        print(
            json.dumps(
                connector_secret_report(_connector_secret_env()),
                indent=2,
                sort_keys=True,
            )
        )
        return
    if args.command == "dagster-status":
        print(
            json.dumps(
                dagster_status_report(dagster_url=args.dagster_url), indent=2, sort_keys=True
            )
        )
        return
    if args.command == "logs-status":
        print(
            json.dumps(
                logs_status_report(
                    loki_url=args.loki_url,
                    since_seconds=args.since_seconds,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return

    extra_args = _operator_live_args(args) if args.command == "operator-live" else None
    if extra_args is None:
        extra_args = getattr(args, "pytest_args", [])
    plan = build_plan(args.command, extra_args)
    if getattr(args, "dry_run", False):
        print(json.dumps({"steps": [step.to_dict() for step in plan]}, indent=2))
        return
    for step in plan:
        _run_step(step)


def _run_step(step: DevStep) -> None:
    Path(UV_CACHE_DIR).mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("UV_CACHE_DIR", UV_CACHE_DIR)
    env.update(step.env)
    subprocess.run(step.command, check=True, env=env)


def _run_ruff(*ruff_args: str) -> None:
    targets = _python_targets()
    if not targets:
        return
    _run_step(DevStep("ruff", ("uv", "run", "ruff", *ruff_args, *targets)))


def _run_pytest_tracked() -> None:
    tests = tuple(
        path
        for path in _git_lines("ls-files")
        if path.startswith("tests/") and path.endswith(".py") and Path(path).exists()
    )
    if not tests:
        return
    _run_step(DevStep("pytest", ("uv", "run", "pytest", "-q", *tests)))


def _python_targets() -> tuple[str, ...]:
    tracked = _git_lines("ls-files", "*.py")
    staged = _git_lines("diff", "--name-only", "--cached", "--", "*.py")
    deleted = set(_git_lines("diff", "--name-only", "--diff-filter=D", "--cached", "--", "*.py"))
    return tuple(
        sorted(
            path
            for path in {*tracked, *staged}
            if path not in deleted and Path(path).exists() and _is_checkable_python_path(path)
        )
    )


def _git_lines(*args: str) -> list[str]:
    result = subprocess.run(("git", *args), check=True, capture_output=True, text=True)
    return [line for line in result.stdout.splitlines() if line]


def _is_checkable_python_path(path: str) -> bool:
    return path.startswith(("src/", "tests/", "scripts/"))


def _format_check() -> DevStep:
    return DevStep("format-check", ("uv", "run", "python", "-m", "fourok.devtools.dev", "format"))


def _lint() -> DevStep:
    return DevStep("lint", ("uv", "run", "python", "-m", "fourok.devtools.dev", "lint"))


def _file_lengths() -> DevStep:
    return DevStep(
        "file-lengths",
        ("uv", "run", "python", "scripts/check_file_lengths.py", "--staged", "--max-lines", "800"),
    )


def _pytest(extra_args: Sequence[str]) -> DevStep:
    if extra_args:
        return DevStep("pytest", ("uv", "run", "pytest", *tuple(extra_args)))
    return DevStep("pytest", ("uv", "run", "python", "-m", "fourok.devtools.dev", "test-tracked"))


def _goal_audit() -> DevStep:
    return DevStep("goal-audit", ("uv", "run", "fourok", "goal-audit"))


def _whitespace() -> DevStep:
    return DevStep("whitespace", ("git", "diff", "--check"))


def _compose_config() -> DevStep:
    return DevStep(
        "compose-config",
        ("docker", "compose", "--profile", "pipeline", "config", "--quiet"),
        env=_compose_local_env(),
    )


def _app_up() -> DevStep:
    return DevStep(
        "app-up",
        (
            "docker",
            "compose",
            "up",
            "--build",
            "--force-recreate",
            "-d",
            "postgres",
            "app",
        ),
        env=_compose_local_env(),
    )


def _core_up() -> DevStep:
    app_step = _app_up()
    return DevStep("core-up", app_step.command, env=app_step.env)


def _cleanup_smoke_projects() -> DevStep:
    return DevStep(
        "cleanup-smoke-projects",
        (
            "bash",
            "-lc",
            """
set -euo pipefail
projects=$(
  docker ps -a --format '{{.Label "com.docker.compose.project"}}' \
    | sort -u \
    | grep -E '^smoke-(fourok|fourok)' \
    || true
)
for project in $projects; do
  docker compose -p "$project" down --remove-orphans
done
""".strip(),
        ),
        env=_compose_local_env(),
    )


def _observability_up() -> DevStep:
    return DevStep(
        "observability-up",
        ("docker", "compose", "--profile", "observability", "up", "-d", "observability"),
        env=_compose_local_env(),
    )


def _pipeline_up() -> DevStep:
    return DevStep(
        "pipeline-up",
        (
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
        ),
        env=_compose_local_env(),
    )


def _pipeline_ps() -> DevStep:
    return DevStep(
        "pipeline-ps",
        ("docker", "compose", "--profile", "pipeline", "ps"),
        env=_compose_local_env(),
    )


def _pull_observability() -> DevStep:
    return DevStep(
        "pull-observability",
        ("docker", "compose", "--profile", "observability", "pull"),
        env=_compose_local_env(),
    )


def _pull_pipeline() -> DevStep:
    return DevStep(
        "pull-pipeline",
        ("docker", "compose", "--profile", "pipeline", "pull"),
        env=_compose_local_env(),
    )


def _operator_live(extra_args: Sequence[str]) -> DevStep:
    return DevStep(
        "operator-live",
        (
            "uv",
            "run",
            "--group",
            "pipeline",
            "python",
            "-m",
            "fourok.runtime.operator_live",
            *tuple(extra_args),
        ),
        env=_compose_local_env(),
    )


def _operator_live_args(args: argparse.Namespace) -> list[str]:
    extra_args: list[str] = []
    if args.operator_dry_run:
        extra_args.append("--dry-run")
    if args.no_start_dagster:
        extra_args.append("--no-start-dagster")
    for name, option in (
        ("project_root", "--project-root"),
        ("raw_landing", "--raw-landing"),
        ("state", "--state"),
        ("database_url", "--database-url"),
    ):
        value = getattr(args, name)
        if value is not None:
            extra_args.extend([option, str(value)])
    extra_args.extend(args.operator_args)
    return extra_args


def _compose_local_env() -> dict[str, str]:
    env = _dotenv_values(Path(".env"))
    env.setdefault("DAGSTER_POSTGRES_PASSWORD", "local-check")
    env.setdefault("POSTGRES_PASSWORD", "local-check")
    env["COMPOSE_PROJECT_NAME"] = "fourok"
    env.setdefault("FOUROK_IMAGE_TAG", _git_short_head(default="local-check"))
    env.setdefault(
        "FOUROK_DATABASE_URL",
        f"postgresql+psycopg://fourok:{env['POSTGRES_PASSWORD']}@postgres:5432/fourok",
    )
    return env


def compose_env_report(*, redact: bool = True) -> dict[str, object]:
    env = _compose_local_env()
    rendered = {
        key: _redact_env_value(key, value) if redact else value
        for key, value in sorted(env.items())
    }
    return {
        "status": "ok",
        "env": rendered,
        "usage": {
            "compose_config": "uv run fourok-dev compose-config",
            "core_up": "uv run fourok-dev core-up",
            "app_up": "uv run fourok-dev app-up",
            "observability_up": "uv run fourok-dev observability-up",
            "pipeline_up": "uv run fourok-dev pipeline-up",
            "stack_up": "uv run fourok-dev stack-up  # core only",
            "pipeline_ps": "uv run fourok-dev pipeline-ps",
        },
    }


_REQUIRED_CONNECTOR_SECRETS = {
    "slack": ("SLACK_BOT_TOKEN",),
    "linear": ("LINEAR_API_KEY",),
    "twenty": ("TWENTY_API_KEY",),
    "google_drive": (
        "GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON",
        "GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN",
    ),
}


def connector_secret_report(env: dict[str, str] | None = None) -> dict[str, object]:
    effective_env = dict(os.environ if env is None else env)
    connectors: dict[str, dict[str, object]] = {}
    missing_any = False
    for connector, required_keys in _REQUIRED_CONNECTOR_SECRETS.items():
        present = [key for key in required_keys if effective_env.get(key)]
        missing = [key for key in required_keys if not effective_env.get(key)]
        if missing:
            missing_any = True
        connectors[connector] = {
            "status": "missing" if missing else "ok",
            "present": present,
            "missing": missing,
        }
    return {
        "status": "missing" if missing_any else "ok",
        "connectors": connectors,
    }


def logs_status_report(
    *,
    loki_url: str = "http://127.0.0.1:3100",
    since_seconds: int = 3600,
    loki=None,
) -> dict[str, object]:
    import time

    loki_call = loki or _loki_get
    queries = {
        "all_fourok": '{compose_project="fourok"}',
        "dagster_code": '{compose_service="dagster-code"}',
        "dagster_failures": '{compose_service="dagster-code"} |= "STEP_FAILURE"',
    }
    end_ns = int(time.time() * 1_000_000_000)
    start_ns = int((time.time() - since_seconds) * 1_000_000_000)
    compose_services_response = loki_call(loki_url, "/loki/api/v1/label/compose_service/values")
    counts: dict[str, dict[str, int]] = {}
    for name, query in queries.items():
        response = loki_call(
            loki_url,
            "/loki/api/v1/query_range",
            {
                "query": query,
                "start": str(start_ns),
                "end": str(end_ns),
                "limit": "1000",
            },
        )
        streams = response.get("data", {}).get("result", [])
        counts[name] = {
            "streams": len(streams),
            "entries": sum(len(stream.get("values", [])) for stream in streams),
        }
    return {
        "status": "ok" if counts["all_fourok"]["entries"] > 0 else "no_recent_logs",
        "loki_url": loki_url,
        "since_seconds": since_seconds,
        "compose_services": compose_services_response.get("data", []),
        "queries": queries,
        "counts": counts,
        "grafana_dashboard": "http://127.0.0.1:3000/d/fourok-local-runtime-logs/fourok-local-runtime-logs",
    }


def _loki_get(base_url: str, path: str, params: dict[str, str] | None = None) -> dict[str, object]:
    url = base_url.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _connector_secret_env() -> dict[str, str]:
    env = _dotenv_values(Path(".env"))
    env.update(os.environ)
    return env


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


def _git_short_head(*, default: str) -> str:
    try:
        result = subprocess.run(
            ("git", "rev-parse", "--short", "HEAD"),
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return default
    return result.stdout.strip() or default


def _git_hooks_dir(project_root: Path) -> Path:
    git_path = project_root / ".git"
    if git_path.is_dir():
        return git_path / "hooks"
    with suppress(OSError, subprocess.CalledProcessError):
        common_dir = _git_lines("-C", str(project_root), "rev-parse", "--git-common-dir")
        if common_dir:
            return Path(common_dir[0]) / "hooks"
    return git_path / "hooks"


def _redact_env_value(key: str, value: str) -> str:
    sensitive_tokens = ("PASSWORD", "SECRET", "TOKEN", "DATABASE_URL", "API_KEY")
    if any(token in key.upper() for token in sensitive_tokens):
        return "[REDACTED]"
    return value


if __name__ == "__main__":
    main()
