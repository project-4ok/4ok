from __future__ import annotations

from pathlib import Path

import yaml

PUBLIC_DAGSTER_RUNTIME_IMAGE = (
    "docker.io/dagster/dagster-k8s:1.13.8@"
    "sha256:24661edd6c98705eba61823804afab65ecd4691bf74a697b7c0d0659df5ed301"
)


def test_publish_runtime_workflow_builds_wheel_and_pinned_images() -> None:
    workflow = Path(".github/workflows/publish-runtime.yml")
    text = workflow.read_text(encoding="utf-8")

    assert "uv build --wheel" in text
    assert "docker/build-push-action" in text
    assert "docker/app.Dockerfile" in text
    assert "docker/dagster.Dockerfile" in text
    assert "target: dagster-code" in text
    assert "target: dagster-runtime" not in text
    assert "4ok-app" in text
    assert "4ok-dagster-code" in text
    assert "4ok-dagster-runtime" not in text
    assert PUBLIC_DAGSTER_RUNTIME_IMAGE in text
    assert "runtime-manifest.json" in text
    assert "sha256sum dist/4ok" in text


def test_pinned_runtime_compose_uses_public_dagster_runtime_image_without_builds() -> None:
    compose_path = Path("deploy/runtime/docker-compose.pinned.yml")
    compose_text = compose_path.read_text(encoding="utf-8")
    compose = yaml.safe_load(compose_text)

    assert "build:" not in compose_text
    assert ":latest" not in compose_text

    services = compose["services"]
    assert services["app"]["image"] == "${GCB_APP_IMAGE:?set GCB_APP_IMAGE to a digest image ref}"
    assert services["gcb-metrics-exporter"]["image"] == services["app"]["image"]
    assert services["dagster-code"]["image"] == (
        "${GCB_DAGSTER_CODE_IMAGE:?set GCB_DAGSTER_CODE_IMAGE to a digest image ref}"
    )
    assert services["dagster-webserver"]["image"] == (
        "${GCB_DAGSTER_RUNTIME_IMAGE:-" + PUBLIC_DAGSTER_RUNTIME_IMAGE + "}"
    )
    assert services["dagster-daemon"]["image"] == services["dagster-webserver"]["image"]
    assert (
        services["dagster-webserver"]["environment"]["DAGSTER_HOME"] == "/opt/dagster/dagster_home"
    )
    assert services["dagster-daemon"]["environment"]["DAGSTER_HOME"] == "/opt/dagster/dagster_home"
    assert (
        "../dagster/dagster.yaml:/tmp/gcb-dagster-home/dagster.yaml:ro"
        in services["dagster-webserver"]["volumes"]
    )
    assert (
        "../dagster/workspace.yaml:/tmp/gcb-dagster-home/workspace.yaml:ro"
        in services["dagster-webserver"]["volumes"]
    )
    assert services["dagster-code"]["environment"]["DAGSTER_CURRENT_IMAGE"] == (
        "${GCB_DAGSTER_CODE_IMAGE:?set GCB_DAGSTER_CODE_IMAGE to a digest image ref}"
    )
    assert "GCB_DATABASE_URL" in services["app"]["environment"]
    assert services["dagster-webserver"]["ports"] == ["127.0.0.1:3001:3001"]


def test_standalone_cli_install_script_builds_clean_python313_wheel() -> None:
    script = Path("scripts/verify_standalone_cli_install.sh").read_text(encoding="utf-8")

    assert "uv build --wheel" in script
    assert "uv venv --python 3.13" in script
    assert "uv pip install" in script
    assert "gcb --help" in script
    assert "grep" in script and "retrieve" in script


def test_runtime_env_example_exposes_pinned_artifact_contract() -> None:
    example = Path("deploy/runtime/gcb-runtime.env.example").read_text(encoding="utf-8")

    assert "GCB_GIT_SHA=" in example
    assert "GCB_CLI_WHEEL_URL=" in example
    assert "GCB_CLI_WHEEL_SHA256=" in example
    assert "GCB_APP_IMAGE=ghcr.io/project-4ok/4ok-app@sha256:" in example
    assert "GCB_DAGSTER_CODE_IMAGE=ghcr.io/project-4ok/4ok-dagster-code@sha256:" in example
    assert f"GCB_DAGSTER_RUNTIME_IMAGE={PUBLIC_DAGSTER_RUNTIME_IMAGE}" in example
