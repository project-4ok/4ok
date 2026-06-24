from __future__ import annotations

from gcb.devtools.dev import DevStep, build_plan


def test_pipeline_up_loads_project_dotenv_and_sets_stable_local_defaults(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text(
        "LINEAR_API_KEY=linear-token\n"
        "SLACK_BOT_TOKEN=secret-value\n",
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
    assert step.env["LINEAR_API_KEY"] == "linear-token"


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
            "LINEAR_API_KEY": "[REDACTED]",
            "SLACK_BOT_TOKEN": "secret-value",
            "POSTGRES_PASSWORD": "local-check",
            "GCB_DATABASE_URL": "postgresql+psycopg://gcb:local-check@postgres:5432/gcb",
        },
    )

    data = step.to_dict()

    assert data["env"] == {
        "GCB_DATABASE_URL": "[REDACTED]",
        "LINEAR_API_KEY": "[REDACTED]",
        "SLACK_BOT_TOKEN": "[REDACTED]",
        "POSTGRES_PASSWORD": "[REDACTED]",
    }
