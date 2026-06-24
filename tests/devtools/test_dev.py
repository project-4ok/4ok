from __future__ import annotations

from gcb.devtools.dev import DevStep, build_plan


def test_pipeline_up_loads_project_dotenv_and_sets_stable_local_defaults(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "INFISICAL_PROJECT_ID=project-123\n"
        "INFISICAL_ENV=dev\n"
        "INFISICAL_PATH=/customer/runtime\n"
        "INFISICAL_DOMAIN=https://infisical.example\n"
        "INFISICAL_CLIENT_ID=client-id\n"
        "INFISICAL_CLIENT_SECRET=secret-value\n",
        encoding="utf-8",
    )

    [step] = build_plan("pipeline-up", [])

    assert step.command == (
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
    )
    assert step.env["POSTGRES_PASSWORD"] == "local-check"
    assert step.env["DAGSTER_POSTGRES_PASSWORD"] == "local-check"
    assert step.env["GCB_DATABASE_URL"] == "postgresql+psycopg://gcb:local-check@postgres:5432/gcb"
    assert step.env["GCB_INFISICAL_PROJECT_ID"] == "project-123"
    assert step.env["GCB_INFISICAL_ENV"] == "dev"
    assert step.env["GCB_INFISICAL_PATH"] == "/customer/runtime"
    assert step.env["GCB_INFISICAL_DOMAIN"] == "https://infisical.example"
    assert step.env["INFISICAL_CLIENT_SECRET"] == "secret-value"


def test_app_up_and_observability_up_wrap_long_compose_commands(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gcb.devtools.dev._git_short_head", lambda *, default: "abc1234")

    [app_step] = build_plan("app-up", [])
    [observability_step] = build_plan("observability-up", [])

    assert app_step.command == (
        "docker",
        "compose",
        "up",
        "--build",
        "--force-recreate",
        "-d",
        "postgres",
        "cerbos",
        "app",
    )
    assert app_step.env["GCB_IMAGE_TAG"] == "abc1234"
    assert app_step.env["POSTGRES_PASSWORD"] == "local-check"
    assert observability_step.command == (
        "docker",
        "compose",
        "--profile",
        "observability",
        "up",
        "-d",
        "observability",
    )
    assert observability_step.env["GCB_DATABASE_URL"] == (
        "postgresql+psycopg://gcb:local-check@postgres:5432/gcb"
    )


def test_stack_up_starts_runtime_pipeline_and_observability_in_order(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("gcb.devtools.dev._git_short_head", lambda *, default: "abc1234")

    plan = build_plan("stack-up", [])

    assert [step.name for step in plan] == ["app-up", "observability-up", "pipeline-up"]


def test_dev_step_dry_run_redacts_secret_env_values() -> None:
    step = DevStep(
        "example",
        ("example",),
        env={
            "INFISICAL_CLIENT_ID": "client-id",
            "INFISICAL_CLIENT_SECRET": "secret-value",
            "POSTGRES_PASSWORD": "local-check",
            "GCB_DATABASE_URL": "postgresql+psycopg://gcb:local-check@postgres:5432/gcb",
        },
    )

    data = step.to_dict()

    assert data["env"] == {
        "GCB_DATABASE_URL": "[REDACTED]",
        "INFISICAL_CLIENT_ID": "client-id",
        "INFISICAL_CLIENT_SECRET": "[REDACTED]",
        "POSTGRES_PASSWORD": "[REDACTED]",
    }
