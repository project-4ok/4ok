from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from fourok.devtools.goal_audit import audit_goal_alignment
from fourok.runtime.access import check_compose_access_boundary
from fourok.runtime.dependency_contracts import dependency_contract_report

ACTIVE_COMPOSE_SERVICES = ("postgres", "observability", "app")
REQUIRED_APP_ENV = (
    "FOUROK_DATABASE_URL",
    "OTEL_EXPORTER_OTLP_ENDPOINT",
    "OTEL_SERVICE_NAME",
)
REQUIRED_RUNBOOK_TERMS = (
    "deploy",
    "health",
    "import",
    "search",
    "dashboard",
    "telemetry",
    "backup",
    "restore",
)


def internal_prod_readiness_report(
    *,
    project_root: Path = Path("."),
    compose_file: Path = Path("docker-compose.yml"),
) -> dict[str, object]:
    root = project_root.resolve()
    compose_path = compose_file if compose_file.is_absolute() else root / compose_file
    compose = _load_compose(compose_path)
    services = compose.get("services", {})
    volumes = compose.get("volumes", {})

    checks = [
        _check_active_services(services),
        _check_images(services),
        _check_restart_policies(services),
        _check_healthchecks(services),
        _check_persistent_volumes(services, volumes),
        _check_app_environment(services),
        _check_no_reference_runtime_dependency(compose),
        _check_runbook(root),
        _check_dependency_contracts(),
        _check_goal_audit(root),
        _check_access_boundary(compose_path),
    ]
    status = "ok" if all(check["status"] == "ok" for check in checks) else "failed"
    return {
        "checks": checks,
        "compose_file": str(compose_path),
        "status": status,
        "summary": {
            "passed": sum(1 for check in checks if check["status"] == "ok"),
            "failed": sum(1 for check in checks if check["status"] != "ok"),
            "total": len(checks),
        },
    }


def _load_compose(compose_path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("docker-compose.yml must contain a YAML object")
    return loaded


def _check_active_services(services: dict[str, Any]) -> dict[str, object]:
    missing = [service for service in ACTIVE_COMPOSE_SERVICES if service not in services]
    return _check("active_services", missing=missing)


def _check_images(services: dict[str, Any]) -> dict[str, object]:
    problems: list[str] = []
    app_image = str(services.get("app", {}).get("image", ""))
    if "${FOUROK_IMAGE_TAG:?set FOUROK_IMAGE_TAG}" not in app_image:
        problems.append("app image must be tagged by FOUROK_IMAGE_TAG")
    for service_name, service in services.items():
        image = str(service.get("image", ""))
        if image.endswith(":latest") or image == "latest":
            problems.append(f"{service_name} uses latest image tag")
    return _check("pinned_images", missing=problems)


def _check_restart_policies(services: dict[str, Any]) -> dict[str, object]:
    missing = [
        service
        for service in ACTIVE_COMPOSE_SERVICES
        if services.get(service, {}).get("restart") != "unless-stopped"
    ]
    return _check("restart_policies", missing=missing)


def _check_healthchecks(services: dict[str, Any]) -> dict[str, object]:
    missing = [
        service
        for service in ACTIVE_COMPOSE_SERVICES
        if "healthcheck" not in services.get(service, {})
    ]
    return _check("healthchecks", missing=missing)


def _check_persistent_volumes(
    services: dict[str, Any],
    volumes: dict[str, Any],
) -> dict[str, object]:
    required = {
        "postgres-data": ("postgres", "/var/lib/postgresql/data"),
        "observability-data": ("observability", "/data"),
        "fourok-local": ("app", "/app/.local"),
        "fourok-data": ("app", "/var/lib/fourok"),
    }
    missing: list[str] = []
    for volume_name, (service_name, mount_path) in required.items():
        if volume_name not in volumes:
            missing.append(f"missing named volume {volume_name}")
        service_volumes = services.get(service_name, {}).get("volumes") or []
        expected = f"{volume_name}:{mount_path}"
        if expected not in service_volumes:
            missing.append(f"{service_name} missing {expected}")
    return _check("persistent_volumes", missing=missing)


def _check_app_environment(services: dict[str, Any]) -> dict[str, object]:
    app_environment = services.get("app", {}).get("environment") or {}
    missing = [name for name in REQUIRED_APP_ENV if name not in app_environment]
    if "${FOUROK_DATABASE_URL:?set FOUROK_DATABASE_URL}" not in str(
        app_environment.get("FOUROK_DATABASE_URL", "")
    ):
        missing.append("FOUROK_DATABASE_URL must fail fast when missing")
    return _check("app_environment", missing=missing)


def _check_no_reference_runtime_dependency(compose: dict[str, Any]) -> dict[str, object]:
    text = yaml.safe_dump(compose, sort_keys=True)
    missing = [".reference runtime dependency"] if ".reference" in text else []
    return _check("no_reference_runtime_dependency", missing=missing)


def _check_runbook(project_root: Path) -> dict[str, object]:
    docs = "\n".join(
        [
            (project_root / "docs" / "internal-prod.md").read_text(encoding="utf-8").lower(),
            (project_root / "docs" / "operations.md").read_text(encoding="utf-8").lower(),
        ]
    )
    missing = [term for term in REQUIRED_RUNBOOK_TERMS if term not in docs]
    return _check("runbook", missing=missing)


def _check_dependency_contracts() -> dict[str, object]:
    report = dependency_contract_report()
    missing = [] if report["status"] == "ok" else ["dependency contracts failed"]
    return _check("dependency_contracts", missing=missing, detail=report["summary"])


def _check_goal_audit(project_root: Path) -> dict[str, object]:
    report = audit_goal_alignment(project_root)
    missing = [] if report["status"] == "ok" else ["goal audit failed"]
    return _check("goal_audit", missing=missing, detail=report["summary"])


def _check_access_boundary(compose_path: Path) -> dict[str, object]:
    report = check_compose_access_boundary(compose_file=compose_path)
    missing = [] if report["status"] == "ok" else ["access boundary failed"]
    return _check("access_boundary", missing=missing, detail={"violations": report["violations"]})


def _check(
    name: str,
    *,
    missing: list[str],
    detail: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "detail": detail or {},
        "missing": missing,
        "name": name,
        "status": "ok" if not missing else "failed",
    }
