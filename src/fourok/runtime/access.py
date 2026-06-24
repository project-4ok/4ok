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
            normalized_exposure = _normalized_exposure(exposure)
            allowed = _exposure_key(
                normalized_exposure
            ) in ALLOWED_EXPOSURES or _is_allowed_dynamic_mcp(exposure)
            exposures.append({**exposure, "status": "allowed" if allowed else "unexpected"})
            if normalized_exposure["host_ip"] in BROAD_HOSTS or exposure["host_ip"] in BROAD_HOSTS:
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
    env["FOUROK_IMAGE_TAG"] = os.environ.get("FOUROK_IMAGE_TAG", "access-smoke")
    env["FOUROK_DATABASE_URL"] = os.environ.get(
        "FOUROK_DATABASE_URL",
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


def _is_allowed_dynamic_mcp(exposure: dict[str, str]) -> bool:
    return (
        exposure["service"] == "mcp"
        and exposure["host_ip"].startswith("127.0.0.1")
        and exposure["target"] == "8010"
        and exposure["protocol"] == "tcp"
    )


def _normalized_exposure(exposure: dict[str, str]) -> dict[str, str]:
    return {
        **exposure,
        "host_ip": _normalize_port_expression(exposure["host_ip"]),
        "published": _normalize_port_expression(exposure["published"]),
        "target": _normalize_port_expression(exposure["target"]),
    }


def _normalize_port_expression(value: str) -> str:
    if not (value.startswith("${") and value.endswith("}")):
        return value

    variable_expr = value[2:-1]
    default_delimiter = ":-"
    default_index = variable_expr.find(default_delimiter)
    if default_index < 0:
        return value

    return variable_expr[default_index + len(default_delimiter) :]


def _string_exposure(service_name: str, port: str) -> dict[str, str] | None:
    protocol = "tcp"
    port_spec = port
    if "/" in port:
        port_spec, protocol = port.rsplit("/", 1)

    parts = _split_port_mapping(port_spec)
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


def _split_port_mapping(port_spec: str) -> list[str]:
    if not port_spec:
        return []

    parts: list[str] = []
    in_placeholder = False
    start = 0

    for index, char in enumerate(port_spec):
        if (
            not in_placeholder
            and char == "$"
            and index + 1 < len(port_spec)
            and port_spec[index + 1] == "{"
        ):
            in_placeholder = True
        elif in_placeholder and char == "}":
            in_placeholder = False
        elif char == ":" and not in_placeholder:
            parts.append(port_spec[start:index])
            start = index + 1

    parts.append(port_spec[start:])
    return parts
