from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

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
from fourok.storage.health import check_runtime_health


def dispatch_runtime_commands(args: argparse.Namespace) -> bool:
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
        report = check_runtime_health(state)
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
        report = check_runtime_health(state)
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
