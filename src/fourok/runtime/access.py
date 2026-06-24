from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

ALLOWED_EXPOSURES = frozenset(
    {
        ("postgres", "127.0.0.1", "5432", "5432", "tcp"),
        ("observability", "127.0.0.1", "3000", "3000", "tcp"),
        ("observability", "127.0.0.1", "3100", "3100", "tcp"),
        ("observability", "127.0.0.1", "3200", "3200", "tcp"),
        ("observability", "127.0.0.1", "4317", "4317", "tcp"),
        ("observability", "127.0.0.1", "4318", "4318", "tcp"),
        ("cerbos", "127.0.0.1", "3592", "3592", "tcp"),
        ("cerbos", "127.0.0.1", "3593", "3593", "tcp"),
        ("dagster-webserver", "127.0.0.1", "3001", "3001", "tcp"),
    }
)
IGNORED_PROFILES = frozenset({"experiments"})
BROAD_HOSTS = frozenset({"", "0.0.0.0", "::"})


def check_compose_access_boundary(
    *,
    compose_file: Path,
    rendered_config: dict[str, Any] | None = None,
    runner=None,
) -> dict[str, object]:
    if rendered_config is not None:
        config = rendered_config
    elif runner is not None:
        config = _load_rendered_compose_config(compose_file=compose_file, runner=runner)
    else:
        config = _load_compose_file(compose_file)
    services = config.get("services", {})
    if not isinstance(services, dict):
        raise ValueError("rendered compose config must contain a services object")

    exposures: list[dict[str, str]] = []
    violations: list[dict[str, str]] = []
    skipped_services: list[dict[str, object]] = []

    for service_name, service in sorted(services.items()):
        if not isinstance(service, dict):
            continue
        profiles = _service_profiles(service)
        if IGNORED_PROFILES.intersection(profiles):
            skipped_services.append({"service": service_name, "profiles": sorted(profiles)})
            continue

        for port in service.get("ports") or []:
            exposure = _exposure(service_name, port)
            if exposure is None:
                continue
            allowed = _exposure_key(exposure) in ALLOWED_EXPOSURES
            exposures.append({**exposure, "status": "allowed" if allowed else "unexpected"})
            if exposure["host_ip"] in BROAD_HOSTS:
                violations.append({**exposure, "reason": "broad_host_binding"})
            elif not allowed:
                violations.append({**exposure, "reason": "unexpected_exposure"})

    return {
        "status": "ok" if not violations else "failed",
        "compose_file": str(compose_file),
        "exposures": exposures,
        "violations": violations,
        "skipped_services": skipped_services,
    }


def _load_compose_file(compose_file: Path) -> dict[str, Any]:
    with compose_file.open(encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("docker compose file did not produce a YAML object")
    return data


def _load_rendered_compose_config(*, compose_file: Path, runner) -> dict[str, Any]:
    command = [
        "docker",
        "compose",
        "--file",
        str(compose_file),
        "config",
        "--format",
        "json",
    ]
    completed = runner(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=_compose_config_env(),
    )
    if completed.returncode != 0:
        raise RuntimeError("docker compose config failed")
    data = json.loads(completed.stdout)
    if not isinstance(data, dict):
        raise ValueError("docker compose config did not produce a JSON object")
    return data


def _compose_config_env() -> dict[str, str]:
    allowlist = {
        "COMPOSE_PROJECT_NAME",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "HOME",
        "PATH",
        "XDG_CONFIG_HOME",
    }
    env = {key: value for key, value in os.environ.items() if key in allowlist}
    env["FOUR_OK_IMAGE_TAG"] = os.environ.get("FOUR_OK_IMAGE_TAG", "access-smoke")
    env["FOUR_OK_DATABASE_URL"] = os.environ.get(
        "FOUR_OK_DATABASE_URL",
        "postgresql+psycopg://fourok:access-smoke@postgres:5432/fourok",
    )
    env["POSTGRES_PASSWORD"] = os.environ.get("POSTGRES_PASSWORD", "access-smoke")
    env["DAGSTER_POSTGRES_PASSWORD"] = os.environ.get(
        "DAGSTER_POSTGRES_PASSWORD",
        "access-smoke",
    )
    return env


def _service_profiles(service: dict[str, Any]) -> set[str]:
    raw_profiles = service.get("profiles") or []
    if isinstance(raw_profiles, str):
        return {raw_profiles}
    if isinstance(raw_profiles, list):
        return {str(item) for item in raw_profiles}
    return set()


def _exposure(service_name: str, port: object) -> dict[str, str] | None:
    if isinstance(port, str):
        return _string_exposure(service_name, port)
    if not isinstance(port, dict):
        return None
    return {
        "service": service_name,
        "host_ip": str(port.get("host_ip") or ""),
        "published": str(port.get("published") or ""),
        "target": str(port.get("target") or ""),
        "protocol": str(port.get("protocol") or "tcp"),
    }


def _exposure_key(exposure: dict[str, str]) -> tuple[str, str, str, str, str]:
    return (
        exposure["service"],
        exposure["host_ip"],
        exposure["published"],
        exposure["target"],
        exposure["protocol"],
    )


def _string_exposure(service_name: str, port: str) -> dict[str, str] | None:
    protocol = "tcp"
    port_spec = port
    if "/" in port:
        port_spec, protocol = port.rsplit("/", 1)

    parts = port_spec.rsplit(":", 2)
    if len(parts) == 3:
        host_ip, published, target = parts
    elif len(parts) == 2:
        host_ip = ""
        published, target = parts
    elif len(parts) == 1:
        host_ip = ""
        published = ""
        target = parts[0]
    else:
        return None

    return {
        "service": service_name,
        "host_ip": host_ip,
        "published": published,
        "target": target,
        "protocol": protocol,
    }
