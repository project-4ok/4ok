from __future__ import annotations

import os
from pathlib import Path

from fourok.cli_parts.shared import DEFAULT_STATE, StoreExplicitState


def add_runtime_commands(subparsers) -> None:
    stage1_parser = subparsers.add_parser(
        "stage1-acceptance",
        help="Run the local Stage 1 health/retrieval/permission/Dagster/Grafana gate.",
    )
    stage1_parser.add_argument("--json", action="store_true", help="Print JSON output.")
    stage1_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    stage1_parser.add_argument("--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL"))
    stage1_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/retrieval_eval/live_retrieval_case_set.json"),
    )
    stage1_parser.add_argument("--case-limit", type=int, default=5)
    stage1_parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/stage1-acceptance-live-retrieval.md"),
    )
    stage1_parser.add_argument("--dagster-url", default="http://127.0.0.1:3001/graphql")
    stage1_parser.add_argument("--grafana-url", default="http://127.0.0.1:3000")
    stage1_parser.add_argument("--skip-dagster", action="store_true")
    stage1_parser.add_argument("--skip-grafana", action="store_true")
    stage1_parser.set_defaults(state_explicit=False)

    acceptance_parser = subparsers.add_parser(
        "acceptance-proof",
        help="Run the internal v0 health/import/search/audit/OTel/backup proof.",
        description=(
            "Run the internal v0 health/import/search/audit/OTel/backup proof. "
            "Fixture seed for deterministic regression proof only."
        ),
    )
    acceptance_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    acceptance_parser.add_argument("--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL"))
    acceptance_parser.add_argument("--config", type=Path)
    acceptance_parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("docker-compose.yml"),
        help="Docker Compose file used for the internal access-boundary smoke check.",
    )
    acceptance_parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/context_substrate/source_snapshot_eval.json"),
        help="Fixture seed for deterministic regression proof only.",
    )
    acceptance_parser.add_argument("--query", default="Robin Scharf")
    acceptance_parser.add_argument(
        "--backup-database-url",
        default=os.environ.get("FOUR_OK_BACKUP_DATABASE_URL") or os.environ.get("FOUR_OK_DATABASE_URL"),
    )
    acceptance_parser.add_argument(
        "--backup-output",
        type=Path,
        default=Path(".local/backups/acceptance-proof.dump"),
    )
    acceptance_parser.add_argument(
        "--observability-endpoint",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "console"),
    )
    acceptance_parser.add_argument(
        "--observability-service-name",
        default=os.environ.get("OTEL_SERVICE_NAME", "fourok-acceptance-proof"),
    )

    dashboard_parser = subparsers.add_parser(
        "dashboard",
        help="Print operator import, lifecycle, link, connector, and audit stats.",
    )
    dashboard_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    dashboard_parser.add_argument("--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL"))
    dashboard_parser.add_argument("--config", type=Path)

    operator_status_parser = subparsers.add_parser(
        "operator-status",
        help="Print compact local runtime import and connector counts.",
    )
    operator_status_parser.set_defaults(state_explicit=False)
    operator_status_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        action=StoreExplicitState,
    )
    operator_status_parser.add_argument("--database-url")
    operator_status_parser.add_argument("--config", type=Path)
    operator_status_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic freshness checks.",
    )

    goal_audit_parser = subparsers.add_parser(
        "goal-audit",
        help="Check active goal alignment invariants that commonly drift.",
    )
    goal_audit_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Repository root to inspect.",
    )

    rebuild_retrieval_parser = subparsers.add_parser(
        "rebuild-retrieval-units",
        help="Recreate derived retrieval units from source records.",
    )
    rebuild_retrieval_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    rebuild_retrieval_parser.add_argument(
        "--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL")
    )
    rebuild_retrieval_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with [retrieval] chunk settings.",
    )
    rebuild_retrieval_parser.add_argument(
        "--confirm-rebuild",
        action="store_true",
        help="Required because this deletes and recreates derived retrieval-unit rows.",
    )

    health_parser = subparsers.add_parser(
        "health",
        help="Check database connectivity and whether source/retrieval records exist.",
    )
    health_parser.set_defaults(state_explicit=False)
    health_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        action=StoreExplicitState,
    )
    health_parser.add_argument("--database-url")

    monitor_parser = subparsers.add_parser(
        "runtime-monitor",
        help="Keep the local app container alive and emit periodic health reports.",
    )
    monitor_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    monitor_parser.add_argument("--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL"))
    monitor_parser.add_argument(
        "--raw-store",
        type=Path,
        help="Filesystem raw source store path. Overrides [raw_store].path in --config.",
    )
    monitor_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with runtime settings to check.",
    )
    monitor_parser.add_argument(
        "--interval-seconds",
        type=float,
        default=60.0,
        help="Seconds to wait between health reports.",
    )
    monitor_parser.add_argument(
        "--max-checks",
        type=int,
        help="Exit after this many checks. Omit for the container runtime.",
    )

    subparsers.add_parser(
        "runtime-services",
        help="Print current service and worker boundaries.",
    )

    subparsers.add_parser(
        "dependency-contracts",
        help="Print external dependency contract-spike proofs.",
    )

    readiness_parser = subparsers.add_parser(
        "internal-prod-readiness",
        help="Check static internal-prod Docker Compose readiness requirements.",
    )
    readiness_parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Repository root to inspect.",
    )
    readiness_parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("docker-compose.yml"),
        help="Docker Compose file to inspect.",
    )

    access_smoke_parser = subparsers.add_parser(
        "access-smoke",
        help="Check Docker Compose internal-v0 host port exposure.",
    )
    access_smoke_parser.add_argument(
        "--compose-file",
        type=Path,
        default=Path("docker-compose.yml"),
        help="Docker Compose file to render and inspect.",
    )

    observability_smoke_parser = subparsers.add_parser(
        "observability-smoke",
        help="Emit a safe local OpenTelemetry smoke trace and log.",
    )
    observability_smoke_parser.add_argument(
        "--endpoint",
        default=os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318"),
        help="OTLP HTTP endpoint base URL, or 'console' for deterministic local output.",
    )
    observability_smoke_parser.add_argument(
        "--service-name",
        default="fourok-local-smoke",
        help="OpenTelemetry service.name for the smoke signal.",
    )
