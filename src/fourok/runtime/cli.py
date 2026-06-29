from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from fourok.cli_parts.runtime_helpers import _config_from_args, _context_state_from_args
from fourok.cli_parts.shared import DEFAULT_STATE
from fourok.devtools.goal_audit import audit_goal_alignment
from fourok.governance.state import create_governed_context_state
from fourok.observability import emit_observability_smoke
from fourok.runtime.acceptance import internal_v0_acceptance_proof
from fourok.runtime.access import check_compose_access_boundary
from fourok.runtime.dashboard import operator_dashboard, operator_status
from fourok.runtime.dependency_contracts import dependency_contract_report
from fourok.runtime.operator_live import _dotenv_values, host_database_url, operator_environment
from fourok.runtime.readiness import internal_prod_readiness_report
from fourok.runtime.rebuild import rebuild_retrieval_units
from fourok.runtime.services import runtime_service_boundaries
from fourok.runtime.stage1_acceptance import run_stage1_acceptance
from fourok.storage.health import check_database_health, check_runtime_health


def dispatch_runtime_commands(args: argparse.Namespace) -> bool:
    if args.command == "onboard":
        if args.onboard_step == "initial-run":
            print(_run_onboard_initial_run())
            return True
        print(_onboard_message(args))
        return True

    if args.command == "status":
        database_url = health_database_url(
            state=DEFAULT_STATE,
            state_explicit=False,
            explicit_database_url=None,
        )
        state = create_governed_context_state(
            state_path=DEFAULT_STATE,
            database_url=database_url,
            raw_store_path=None,
        )
        report = check_runtime_health(state)
        report = _client_status_report(state, report)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            print(_format_client_status(report))
        if report["status"] != "ok":
            raise SystemExit(1)
        return True

    if args.command == "stage1-acceptance":
        database_url = host_operator_database_url(
            state=args.state,
            state_explicit=getattr(args, "state_explicit", False),
            explicit_database_url=args.database_url,
        )
        report = run_stage1_acceptance(
            state_path=args.state,
            database_url=database_url,
            cases_path=args.cases,
            case_limit=args.case_limit,
            report_path=args.report,
            dagster_url=args.dagster_url,
            grafana_url=args.grafana_url,
            skip_dagster=args.skip_dagster,
            skip_grafana=args.skip_grafana,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        if report.get("status") != "ok":
            raise SystemExit(1)
        return True

    if args.command == "acceptance-proof":
        proof = internal_v0_acceptance_proof(
            state_path=args.state,
            database_url=args.database_url,
            config_path=args.config,
            fixture_path=args.fixture,
            query=args.query,
            backup_database_url=args.backup_database_url,
            backup_output=args.backup_output,
            observability_smoke=lambda: emit_observability_smoke(
                service_name=args.observability_service_name,
                endpoint=args.observability_endpoint,
            ),
            access_smoke=lambda: check_compose_access_boundary(compose_file=args.compose_file),
        )
        print(
            json.dumps(
                proof,
                indent=2,
                sort_keys=True,
            )
        )
        if proof.get("status") != "ok":
            raise SystemExit(1)
        return True

    if args.command == "dashboard":
        state = _context_state_from_args(args)
        config = _config_from_args(args)
        print(
            json.dumps(
                operator_dashboard(
                    state,
                    retry_delay_seconds=config.scheduler.retry_delay_seconds,
                    max_retry_attempts=config.scheduler.max_attempts,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "operator-status":
        args.database_url = host_operator_database_url(
            state=args.state,
            state_explicit=args.state_explicit,
            explicit_database_url=args.database_url,
        )
        state = _context_state_from_args(args)
        config = _config_from_args(args)
        print(
            json.dumps(
                operator_status(
                    state,
                    now=datetime.fromisoformat(args.now) if args.now else None,
                    stale_after_minutes=config.scheduler.import_interval_minutes,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "goal-audit":
        report = audit_goal_alignment(args.project_root)
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "ok":
            raise SystemExit(1)
        return True

    if args.command == "rebuild-retrieval-units":
        if not args.confirm_rebuild:
            raise SystemExit("rebuild-retrieval-units requires --confirm-rebuild")
        config = _config_from_args(args)
        state = _context_state_from_args(args)
        print(
            json.dumps(
                rebuild_retrieval_units(state, retrieval_config=config.retrieval),
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "health":
        if args.database_url is None:
            args.database_url = health_database_url(
                state=args.state,
                state_explicit=args.state_explicit,
                explicit_database_url=None,
            )
        state = create_governed_context_state(
            state_path=args.state,
            database_url=args.database_url,
            raw_store_path=None,
        )
        report = check_database_health(state) if args.database_only else check_runtime_health(state)
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "ok":
            raise SystemExit(1)
        return True

    if args.command == "runtime-monitor":
        run_runtime_monitor(args)
        return True

    if args.command == "runtime-services":
        print(
            json.dumps(
                {"services": [boundary.to_dict() for boundary in runtime_service_boundaries()]},
                indent=2,
            )
        )
        return True

    if args.command == "dependency-contracts":
        report = dependency_contract_report()
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "ok":
            raise SystemExit(1)
        return True

    if args.command == "internal-prod-readiness":
        report = internal_prod_readiness_report(
            project_root=args.project_root,
            compose_file=args.compose_file,
        )
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "ok":
            raise SystemExit(1)
        return True

    if args.command == "access-smoke":
        report = check_compose_access_boundary(compose_file=args.compose_file)
        print(json.dumps(report, indent=2, sort_keys=True))
        if report["status"] != "ok":
            raise SystemExit(1)
        return True

    if args.command == "observability-smoke":
        print(
            json.dumps(
                emit_observability_smoke(
                    service_name=args.service_name,
                    endpoint=args.endpoint,
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return True
    return False


_DEMO_SOURCE_SYSTEMS = frozenset({"local_email", "context-fixture", "fixture"})


def _client_status_report(state, report: dict) -> dict:
    source_counts = _source_system_counts(state)
    checks = report.get("checks", [])
    counts = {check.get("name"): check.get("count") for check in checks if isinstance(check, dict)}
    source_count = counts.get("source_records")
    live_source_count = sum(
        count
        for source_system, count in source_counts.items()
        if source_system not in _DEMO_SOURCE_SYSTEMS
    )
    client_status = dict(report)
    client_status["source_system_counts"] = source_counts
    client_status["live_source_records"] = live_source_count
    if not client_status.get("freshness"):
        try:
            client_status["freshness"] = operator_status(state).get("freshness", {})
        except Exception:
            client_status["freshness"] = {}
    client_status["configured_connectors"] = _configured_connector_names(
        _connector_secret_report()
    )
    if source_count is not None and int(source_count) == 0:
        client_status["status"] = "needs_onboarding"
        client_status["detail"] = "no connector data has been imported yet"
    elif source_counts and live_source_count == 0:
        client_status["status"] = "needs_onboarding"
        client_status["detail"] = "only demo context is present"
    return client_status


def _source_system_counts(state) -> dict[str, int]:
    try:
        with state.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT source_system, count(*) FROM source_records "
                    "WHERE lifecycle_state = 'active' GROUP BY source_system"
                )
            )
            return {str(source_system): int(count) for source_system, count in rows}
    except Exception:
        return {}


def _format_client_status(report: dict) -> str:
    checks = report.get("checks", [])
    counts = {check.get("name"): check.get("count") for check in checks if isinstance(check, dict)}
    source_count = counts.get("source_records") or 0
    retrieval_count = counts.get("retrieval_records") or 0
    if report.get("status") == "needs_onboarding":
        detail = str(report.get("detail") or "")
        data_line = (
            "Only demo context is present; no connector data has been imported yet."
            if detail == "only demo context is present"
            else "No connector data has been imported yet."
        )
        return "\n".join(
            [
                "fourok needs onboarding",
                "",
                f"Context: {source_count} source records, {retrieval_count} retrieval units",
                data_line,
                "",
                "Next:",
                "  fourok onboard",
            ]
        )
    ready_line = "fourok is ready" if report.get("status") == "ok" else "fourok needs attention"
    pipeline_lines = _client_pipeline_lines(report)
    return "\n".join(
        [
            ready_line,
            "",
            f"Context: {source_count} source records, {retrieval_count} retrieval units",
            *pipeline_lines,
            "",
            "Try:",
            '  fourok retrieve "What changed this week?"',
        ]
    )


def _client_pipeline_lines(report: dict) -> list[str]:
    live_ingestion = (
        report.get("freshness", {}).get("live_ingestion", {})
        if isinstance(report.get("freshness"), dict)
        else {}
    )
    if not isinstance(live_ingestion, dict):
        return []
    sources = live_ingestion.get("sources", {})
    if not isinstance(sources, dict) or not sources:
        return []
    configured_connectors = report.get("configured_connectors")
    if isinstance(configured_connectors, list):
        configured = {str(source) for source in configured_connectors}
        sources = {
            source: source_report
            for source, source_report in sources.items()
            if str(source) in configured
        }
    if not sources:
        return []
    has_attention = any(
        _client_source_needs_attention(source_report)
        for source_report in sources.values()
        if isinstance(source_report, dict)
    )
    pipeline_line = (
        "Data pipeline: needs attention" if has_attention else "Data pipeline: working well"
    )
    lines = ["", pipeline_line, "Sources:"]
    for source, source_report in sorted(sources.items()):
        if not isinstance(source_report, dict):
            continue
        lines.append(f"  {_client_source_status_line(str(source), source_report)}")
    return lines


def _client_source_status_line(source: str, source_report: dict) -> str:
    freshness = str(source_report.get("freshness_status") or "")
    latest_status = str(source_report.get("latest_status") or "")
    if freshness == "missing" or latest_status == "missing":
        return f"{source}: not connected yet"
    age = _relative_age_from_seconds(source_report.get("age_seconds"))
    count = source_report.get("source_record_count")
    count_text = (
        f" ({int(count)} {_plural(int(count), 'record')})"
        if isinstance(count, int)
        else ""
    )
    if freshness == "fresh" and latest_status == "succeeded":
        return f"{source}: working well, imported {age}{count_text}"
    if latest_status == "failed" or freshness in {"failed", "stale"}:
        return f"{source}: needs attention, last checked {age}{count_text}"
    return f"{source}: {freshness or latest_status or 'unknown'}, last checked {age}{count_text}"


def _client_source_needs_attention(source_report: dict) -> bool:
    freshness = str(source_report.get("freshness_status") or "")
    latest_status = str(source_report.get("latest_status") or "")
    return freshness != "fresh" or latest_status != "succeeded"


def _relative_age_from_seconds(value: object) -> str:
    if not isinstance(value, int):
        return "not yet"
    if value < 60:
        return "just now"
    minutes = value // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    return f"{days} d ago"


def _plural(count: int, word: str) -> str:
    return word if count == 1 else f"{word}s"


_REQUIRED_CONNECTOR_SECRETS = {
    "slack": ("SLACK_BOT_TOKEN",),
    "linear": ("LINEAR_API_KEY",),
    "twenty": ("TWENTY_API_KEY",),
    "google_drive": (
        "GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON",
        "GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN",
        "GOOGLE_WORKSPACE_DRIVE_IDS",
    ),
}


def _onboard_message(args: argparse.Namespace) -> str:
    status_report = _safe_client_status_report()
    secret_report = _connector_secret_report()
    embedding_report = _embedding_secret_report()
    dagster_secret_presence = _dagster_code_secret_presence()
    checks = status_report.get("checks", [])
    counts = {check.get("name"): check.get("count") for check in checks if isinstance(check, dict)}
    source_count = counts.get("source_records") or 0
    retrieval_count = counts.get("retrieval_records") or 0
    lines = [
        "fourok onboarding",
        "",
        "Current state:",
        f"  runtime: {status_report.get('status', 'unknown')}",
        f"  context: {source_count} source records, {retrieval_count} retrieval units",
    ]
    if status_report.get("status") == "needs_onboarding":
        detail = str(status_report.get("detail") or "")
        data_line = (
            "  data: only demo context is present; no connector data has been imported yet"
            if detail == "only demo context is present"
            else "  data: no connector data has been imported yet"
        )
        lines.append(data_line)
    lines.extend(
        [
            "",
            "Connect your workspace:",
            "  fourok works best when you connect your whole workspace.",
            *_connector_setup_lines(secret_report),
            *_configured_connector_initial_run_lines(secret_report, source_count=source_count),
            *_post_connection_lines(
                status=str(status_report.get("status") or ""), source_count=source_count
            ),
            *_embedding_lines(embedding_report),
            "",
            "Need another connector?",
            "  Create a GitHub issue on project-4ok/4ok with the workspace app,",
            "  auth method, record types, and permission model you need:",
            '    gh issue create --repo project-4ok/4ok --title "Connector: <workspace app>"',
        ]
    )
    if dagster_secret_presence.get("status") == "missing":
        lines.extend(
            [
                "",
                "Pipeline issue:",
                "  dagster-code is not receiving connector credentials from the local environment.",
                "  Recreate it after updating this checkout:",
                "    docker compose up -d --build dagster-code",
            ]
        )
    lines.extend(_onboard_next_lines(status=str(status_report.get("status") or "")))
    if args.demo:
        lines.extend(["", "Demo:", '  fourok retrieve "refund cancellation payment"'])
    return "\n".join(lines)


def _run_onboard_initial_run() -> str:
    steps = [
        (
            "Recreating dagster-code",
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--build",
                "--force-recreate",
                "dagster-code",
            ],
        ),
        (
            "Running initial live backfill",
            [
                "uv",
                "run",
                "fourok",
                "admin",
                "run-live-ingestion",
                "--source",
                "all",
                "--verify-live-db",
            ],
        ),
    ]
    lines = ["fourok initial onboarding run", ""]
    for label, command in steps:
        lines.append(f"{label}: {' '.join(command)}")
        completed = subprocess.run(command, check=False, capture_output=True, text=True)
        if completed.stdout.strip():
            lines.append(completed.stdout.strip())
        if completed.stderr.strip():
            lines.append(completed.stderr.strip())
        if completed.returncode != 0:
            lines.append(f"Failed: {label}")
            raise SystemExit("\n".join(lines))
        if label == "Running initial live backfill":
            _ensure_initial_backfill_completed(completed.stdout, lines)
    lines.extend(
        [
            "",
            "Initial run finished.",
            "Next:",
            "  fourok status",
            '  fourok retrieve "What changed this week?"',
            "  fourok admin connector-jobs",
        ]
    )
    return "\n".join(lines)


def _ensure_initial_backfill_completed(stdout: str, lines: list[str]) -> None:
    try:
        report = json.loads(stdout)
    except json.JSONDecodeError:
        return
    status = report.get("status")
    if status != "ok":
        lines.append(f"Initial live backfill did not complete: {status}")
        raise SystemExit("\n".join(lines))


def _safe_client_status_report() -> dict:
    try:
        database_url = health_database_url(
            state=DEFAULT_STATE,
            state_explicit=False,
            explicit_database_url=None,
        )
        state = create_governed_context_state(
            state_path=DEFAULT_STATE,
            database_url=database_url,
            raw_store_path=None,
        )
        return _client_status_report(state, check_runtime_health(state))
    except Exception as error:
        return {"status": "failed", "detail": str(error), "checks": []}


def _connector_secret_report() -> dict[str, object]:
    env = _dotenv_values(Path(".env"))
    env.update({key: value for key, value in os.environ.items() if value})
    connectors: dict[str, dict[str, object]] = {}
    missing_any = False
    for connector, required_keys in _REQUIRED_CONNECTOR_SECRETS.items():
        missing = [key for key in required_keys if not env.get(key)]
        if missing:
            missing_any = True
        connectors[connector] = {"status": "missing" if missing else "ok", "missing": missing}
    return {"status": "missing" if missing_any else "ok", "connectors": connectors}


def _configured_connector_names(secret_report: dict[str, object]) -> list[str]:
    connectors = secret_report.get("connectors", {})
    if not isinstance(connectors, dict):
        return []
    return [
        str(connector)
        for connector, data in sorted(connectors.items())
        if isinstance(data, dict) and data.get("status") == "ok"
    ]


def _connector_setup_lines(secret_report: dict[str, object]) -> list[str]:
    connectors = secret_report.get("connectors", {})
    if not isinstance(connectors, dict):
        return ["", "Connected now:", "  unknown"]
    configured: list[str] = []
    available: list[tuple[str, list[str]]] = []
    for connector in sorted(connectors):
        data = connectors[connector]
        if not isinstance(data, dict):
            continue
        missing = data.get("missing", [])
        if missing:
            available.append((connector, [str(item) for item in missing]))
        else:
            configured.append(connector)

    lines: list[str] = ["", "Connected now:"]
    lines.extend(f"  {connector}" for connector in configured)
    if not configured:
        lines.append("  none yet")
    if available:
        lines.extend(["", "More connections you can add:"])
        for connector, missing in available:
            lines.append(f"  {connector}")
            lines.extend(f"    add {key} to .env" for key in missing)
    return lines


def _post_connection_lines(*, status: str, source_count: int) -> list[str]:
    if status == "ok" or source_count > 0 and status != "needs_onboarding":
        return []
    return [
        "",
        "After adding a connection:",
        "  1. fourok onboard initial-run   # imports your workspace data",
        "  2. fourok status                # confirm data is available",
        '  3. fourok retrieve "What changed this week?"',
    ]


def _onboard_next_lines(*, status: str) -> list[str]:
    if status == "ok":
        return [
            "",
            "Next:",
            "  fourok status",
            '  fourok retrieve "What changed this week?"',
        ]
    return [
        "",
        "Next:",
        "  fourok onboard initial-run",
        "  fourok status",
    ]


def _configured_connector_initial_run_lines(
    secret_report: dict[str, object], *, source_count: int
) -> list[str]:
    if source_count > 0:
        return []
    connectors = secret_report.get("connectors", {})
    if not isinstance(connectors, dict):
        return []
    configured = [
        name
        for name, data in sorted(connectors.items())
        if isinstance(data, dict) and data.get("status") == "ok"
    ]
    if not configured:
        return []
    connector_text = ", ".join(str(name) for name in configured)
    verb = "is" if len(configured) == 1 else "are"
    return [
        "",
        f"  {connector_text} {verb} configured, but no connector data has been imported yet.",
        "  Run the initial import now:",
        "    fourok onboard initial-run",
    ]


def _embedding_secret_report() -> dict[str, object]:
    env = _dotenv_values(Path(".env"))
    env.update({key: value for key, value in os.environ.items() if value})
    provider = str(env.get("FOUROK_EMBEDDING_PROVIDER") or "").strip().casefold()
    if env.get("OPENAI_API_KEY") or provider == "openai":
        return {"status": "ok", "provider": "openai"}
    return {"status": "missing", "provider": "hash"}


def _embedding_lines(embedding_report: dict[str, object]) -> list[str]:
    if embedding_report.get("status") != "missing":
        return [
            "",
            "Better semantic search:",
            "  OPENAI_API_KEY is configured for OpenAI embeddings.",
        ]
    return [
        "",
        "Better semantic search:",
        "  Set OPENAI_API_KEY in .env so fourok uses OpenAI embeddings.",
        "  Without it, fourok falls back to local hash embeddings, which are much weaker.",
        "  After adding OPENAI_API_KEY, run fourok onboard initial-run to rebuild embeddings.",
    ]


def _dagster_code_secret_presence() -> dict[str, object]:
    keys = sorted({key for keys in _REQUIRED_CONNECTOR_SECRETS.values() for key in keys})
    try:
        result = subprocess.run(
            ["docker", "compose", "exec", "-T", "dagster-code", "printenv"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"status": "unknown", "missing": keys}
    if result.returncode != 0:
        return {"status": "unknown", "missing": keys}
    present = {line.split("=", 1)[0] for line in result.stdout.splitlines() if "=" in line}
    missing = [key for key in keys if key not in present]
    return {"status": "missing" if missing else "ok", "missing": missing}


def host_operator_database_url(
    *,
    state,
    state_explicit: bool = False,
    explicit_database_url: str | None,
) -> str | None:
    if explicit_database_url:
        return explicit_database_url
    if state_explicit or state != DEFAULT_STATE:
        return None
    if app_database_url := _running_app_database_url():
        return host_database_url(app_database_url)
    dotenv_env = _dotenv_values(Path(".") / ".env")
    if compose_database_url := dotenv_env.get("FOUROK_DATABASE_URL"):
        return host_database_url(compose_database_url)
    if postgres_password := dotenv_env.get("POSTGRES_PASSWORD"):
        return host_database_url(
            f"postgresql+psycopg://fourok:{postgres_password}@postgres:5432/fourok"
        )
    operator_env = operator_environment(Path("."))
    if compose_database_url := operator_env.get("FOUROK_DATABASE_URL"):
        return host_database_url(compose_database_url)
    if env_database_url := os.environ.get("FOUROK_DATABASE_URL"):
        return host_database_url(env_database_url)
    return None


def health_database_url(
    *,
    state,
    state_explicit: bool = False,
    explicit_database_url: str | None,
) -> str | None:
    if explicit_database_url:
        return explicit_database_url
    if state_explicit or state != DEFAULT_STATE:
        return None
    if _running_in_container() and (env_database_url := os.environ.get("FOUROK_DATABASE_URL")):
        return env_database_url
    return host_operator_database_url(
        state=state,
        state_explicit=state_explicit,
        explicit_database_url=None,
    )


def _running_in_container() -> bool:
    return Path("/.dockerenv").exists() or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))


def _running_app_database_url() -> str:
    container_id = _running_app_container_id()
    if not container_id:
        return ""
    try:
        result = subprocess.run(
            [
                "docker",
                "exec",
                container_id,
                "printenv",
                "FOUROK_DATABASE_URL",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _running_app_container_id() -> str:
    container_id = _compose_app_container_id()
    if container_id:
        return container_id
    return _labeled_app_container_id()


def _compose_app_container_id() -> str:
    try:
        result = subprocess.run(
            ["docker", "compose", "ps", "-q", "app"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _labeled_app_container_id() -> str:
    try:
        result = subprocess.run(
            [
                "docker",
                "ps",
                "--filter",
                "label=com.docker.compose.project=fourok",
                "--filter",
                "label=com.docker.compose.service=app",
                "--format",
                "{{.ID}}",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def run_runtime_monitor(args: argparse.Namespace) -> None:
    if args.interval_seconds <= 0:
        raise SystemExit("runtime-monitor requires --interval-seconds greater than 0")
    if args.max_checks is not None and args.max_checks <= 0:
        raise SystemExit("runtime-monitor requires --max-checks greater than 0")

    config = _config_from_args(args)
    state = create_governed_context_state(
        state_path=args.state,
        database_url=args.database_url,
        raw_store_path=args.raw_store,
        raw_store_config=config.raw_store if args.raw_store is None else None,
    )
    checks_run = 0
    while args.max_checks is None or checks_run < args.max_checks:
        report = check_database_health(state) if args.database_only else check_runtime_health(state)
        print(
            json.dumps(
                {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "health": report,
                    "status": report["status"],
                },
                sort_keys=True,
            ),
            flush=True,
        )
        checks_run += 1
        if args.max_checks is not None and checks_run >= args.max_checks:
            return
        time.sleep(args.interval_seconds)
