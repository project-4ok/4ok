import json
from pathlib import Path

import pytest

from fourok.runtime.access import check_compose_access_boundary


def test_access_boundary_accepts_expected_loopback_ports() -> None:
    report = check_compose_access_boundary(
        compose_file=Path("docker-compose.yml"),
        rendered_config={
            "services": {
                "app": {},
                "postgres": {"ports": [_port("127.0.0.1", 5432, "5432")]},
                "observability": {
                    "ports": [
                        _port("127.0.0.1", 3000, "3000"),
                        _port("127.0.0.1", 3100, "3100"),
                        _port("127.0.0.1", 3200, "3200"),
                        _port("127.0.0.1", 4317, "4317"),
                        _port("127.0.0.1", 4318, "4318"),
                    ]
                },
                "dagster-webserver": {"ports": [_port("127.0.0.1", 3001, "3001")]},
            }
        },
    )

    assert report["status"] == "ok"
    assert report["violations"] == []
    assert report["exposures"] == [
        {
            "service": "dagster-webserver",
            "host_ip": "127.0.0.1",
            "published": "3001",
            "target": "3001",
            "protocol": "tcp",
            "status": "allowed",
        },
        {
            "service": "observability",
            "host_ip": "127.0.0.1",
            "published": "3000",
            "target": "3000",
            "protocol": "tcp",
            "status": "allowed",
        },
        {
            "service": "observability",
            "host_ip": "127.0.0.1",
            "published": "3100",
            "target": "3100",
            "protocol": "tcp",
            "status": "allowed",
        },
        {
            "service": "observability",
            "host_ip": "127.0.0.1",
            "published": "3200",
            "target": "3200",
            "protocol": "tcp",
            "status": "allowed",
        },
        {
            "service": "observability",
            "host_ip": "127.0.0.1",
            "published": "4317",
            "target": "4317",
            "protocol": "tcp",
            "status": "allowed",
        },
        {
            "service": "observability",
            "host_ip": "127.0.0.1",
            "published": "4318",
            "target": "4318",
            "protocol": "tcp",
            "status": "allowed",
        },
        {
            "service": "postgres",
            "host_ip": "127.0.0.1",
            "published": "5432",
            "target": "5432",
            "protocol": "tcp",
            "status": "allowed",
        },
    ]


def test_access_boundary_rejects_broad_or_unexpected_ports() -> None:
    report = check_compose_access_boundary(
        compose_file=Path("docker-compose.yml"),
        rendered_config={
            "services": {
                "app": {"ports": [_port("0.0.0.0", 8080, "8080")]},
                "postgres": {"ports": [_port("", 5432, "5432")]},
            }
        },
    )

    assert report["status"] == "failed"
    assert report["violations"] == [
        {
            "service": "app",
            "host_ip": "0.0.0.0",
            "published": "8080",
            "target": "8080",
            "protocol": "tcp",
            "reason": "broad_host_binding",
        },
        {
            "service": "postgres",
            "host_ip": "",
            "published": "5432",
            "target": "5432",
            "protocol": "tcp",
            "reason": "broad_host_binding",
        },
    ]


def test_access_boundary_ignores_experiment_profile_services_by_default() -> None:
    report = check_compose_access_boundary(
        compose_file=Path("docker-compose.yml"),
        rendered_config={
            "services": {
                "honcho": {
                    "profiles": ["experiments"],
                    "ports": [_port("0.0.0.0", 8000, "8000")],
                },
                "graphiti-neo4j": {
                    "profiles": ["experiments"],
                    "ports": [_port("", 7474, "7474")],
                },
            }
        },
    )

    assert report["status"] == "ok"
    assert report["violations"] == []
    assert report["skipped_services"] == [
        {"service": "graphiti-neo4j", "profiles": ["experiments"]},
        {"service": "honcho", "profiles": ["experiments"]},
    ]


def test_access_boundary_parses_compose_file_without_docker_cli(tmp_path: Path) -> None:
    compose_file = tmp_path / "compose.yml"
    compose_file.write_text(
        "\n".join(
            [
                "services:",
                "  postgres:",
                "    ports:",
                '      - "127.0.0.1:5432:5432"',
                "  honcho:",
                '    profiles: ["experiments"]',
                "    ports:",
                '      - "8000:8000"',
            ]
        ),
        encoding="utf-8",
    )

    report = check_compose_access_boundary(compose_file=compose_file)

    assert report["status"] == "ok"
    assert report["exposures"] == [
        {
            "service": "postgres",
            "host_ip": "127.0.0.1",
            "published": "5432",
            "target": "5432",
            "protocol": "tcp",
            "status": "allowed",
        }
    ]
    assert report["skipped_services"] == [{"service": "honcho", "profiles": ["experiments"]}]


def test_access_boundary_loads_rendered_compose_config_with_safe_env(monkeypatch) -> None:
    captured = {}

    def fake_runner(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        payload = {"services": {"postgres": {"ports": [_port("127.0.0.1", 5432, "5432")]}}}
        return _Completed(stdout=json.dumps(payload), stderr="", returncode=0)

    report = check_compose_access_boundary(
        compose_file=Path("docker-compose.yml"),
        runner=fake_runner,
    )

    assert report["status"] == "ok"
    assert captured["command"] == [
        "docker",
        "compose",
        "--file",
        "docker-compose.yml",
        "config",
        "--format",
        "json",
    ]
    assert captured["env"]["FOUR_OK_IMAGE_TAG"] == "access-smoke"
    assert captured["env"]["FOUR_OK_DATABASE_URL"] == (
        "postgresql+psycopg://fourok:access-smoke@postgres:5432/fourok"
    )
    assert captured["env"]["POSTGRES_PASSWORD"] == "access-smoke"
    assert captured["env"]["DAGSTER_POSTGRES_PASSWORD"] == "access-smoke"


def test_access_boundary_fails_when_compose_config_cannot_render() -> None:
    def fake_runner(command: list[str], **kwargs: object) -> object:
        return _Completed(stdout="", stderr="missing image tag", returncode=1)

    with pytest.raises(RuntimeError, match="docker compose config failed"):
        check_compose_access_boundary(
            compose_file=Path("docker-compose.yml"),
            runner=fake_runner,
        )


def _port(host_ip: str, target: int, published: str) -> dict[str, object]:
    return {
        "mode": "ingress",
        "host_ip": host_ip,
        "target": target,
        "published": published,
        "protocol": "tcp",
    }


class _Completed:
    def __init__(self, *, stdout: str, stderr: str, returncode: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
