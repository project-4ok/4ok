from pathlib import Path

from fourok.runtime.readiness import internal_prod_readiness_report


def test_internal_prod_readiness_report_passes_for_current_compose() -> None:
    report = internal_prod_readiness_report()

    assert report["status"] == "ok"
    assert report["summary"]["failed"] == 0
    checks = {check["name"]: check for check in report["checks"]}
    assert {
        "active_services",
        "pinned_images",
        "restart_policies",
        "healthchecks",
        "persistent_volumes",
        "app_environment",
        "no_reference_runtime_dependency",
        "runbook",
        "dependency_contracts",
        "goal_audit",
        "access_boundary",
    } <= set(checks)


def test_internal_prod_readiness_report_catches_latest_app_tag(tmp_path: Path) -> None:
    compose_file = tmp_path / "docker-compose.yml"
    compose_file.write_text(
        Path("docker-compose.yml")
        .read_text(encoding="utf-8")
        .replace(
            "fourok-app:${FOUROK_IMAGE_TAG:?set FOUROK_IMAGE_TAG}",
            "fourok-app:latest",
        ),
        encoding="utf-8",
    )

    report = internal_prod_readiness_report(compose_file=compose_file)

    checks = {check["name"]: check for check in report["checks"]}
    assert report["status"] == "failed"
    assert "app image must be tagged by FOUROK_IMAGE_TAG" in checks["pinned_images"]["missing"]
    assert "app uses latest image tag" in checks["pinned_images"]["missing"]
