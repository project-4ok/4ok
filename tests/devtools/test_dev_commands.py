import subprocess
from pathlib import Path

from fourok.devtools.dev import (
    build_plan,
    compose_env_report,
    connector_secret_report,
    dagster_status_report,
    install_hooks,
    logs_status_report,
)


def test_fast_plan_runs_reusable_local_gate_with_optional_pytest_args() -> None:
    plan = build_plan("fast", ["tests/runtime/test_compose.py", "-q"])

    assert [step.name for step in plan] == [
        "lint",
        "format-check",
        "file-lengths",
        "pytest",
        "whitespace",
    ]
    assert plan[3].command == (
        "uv",
        "run",
        "pytest",
        "tests/runtime/test_compose.py",
        "-q",
    )


def test_lint_and_format_check_ignore_untracked_parallel_work() -> None:
    plan = build_plan("fast", [])

    assert plan[0].command == ("uv", "run", "python", "-m", "fourok.devtools.dev", "lint")
    assert plan[1].command == ("uv", "run", "python", "-m", "fourok.devtools.dev", "format")


def test_fast_plan_defaults_to_default_pytest_suite() -> None:
    plan = build_plan("fast", [])

    assert plan[3].command == ("uv", "run", "python", "-m", "fourok.devtools.dev", "test-tracked")


def test_full_plan_includes_goal_audit_and_default_pytest() -> None:
    plan = build_plan("full", [])

    assert [step.name for step in plan] == [
        "lint",
        "format-check",
        "file-lengths",
        "pytest",
        "goal-audit",
        "whitespace",
    ]
    assert plan[3].command == ("uv", "run", "python", "-m", "fourok.devtools.dev", "test-tracked")
    assert plan[4].command == ("uv", "run", "fourok", "goal-audit")


def test_operator_live_plan_runs_pipeline_group_module() -> None:
    plan = build_plan("operator-live", ["--dry-run"])

    assert [step.name for step in plan] == ["operator-live"]
    assert plan[0].command == (
        "uv",
        "run",
        "--group",
        "pipeline",
        "python",
        "-m",
        "fourok.runtime.operator_live",
        "--dry-run",
    )


def test_compose_config_plan_uses_safe_required_env_defaults(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("fourok.devtools.dev._git_short_head", lambda *, default: default)

    plan = build_plan("compose-config", [])

    assert len(plan) == 1
    assert plan[0].env == {
        "DAGSTER_POSTGRES_PASSWORD": "local-check",
        "FOUR_OK_DATABASE_URL": "postgresql+psycopg://fourok:local-check@postgres:5432/fourok",
        "FOUR_OK_IMAGE_TAG": "local-check",
        "POSTGRES_PASSWORD": "local-check",
    }
    assert plan[0].command == ("docker", "compose", "--profile", "pipeline", "config")


def test_compose_env_report_redacts_runtime_env_and_keeps_non_secret_values(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("fourok.devtools.dev._git_short_head", lambda *, default: "abc1234")
    (tmp_path / ".env").write_text(
        "POSTGRES_PASSWORD=super-secret\n"
        "LINEAR_API_KEY=linear-token\n"
        "",
        encoding="utf-8",
    )

    report = compose_env_report()

    assert report["status"] == "ok"
    assert report["env"]["POSTGRES_PASSWORD"] == "[REDACTED]"
    assert report["env"]["FOUR_OK_DATABASE_URL"] == "[REDACTED]"
    assert report["env"]["FOUR_OK_IMAGE_TAG"] == "abc1234"
    assert report["env"]["LINEAR_API_KEY"] == "linear-token"
    assert report["usage"]["pipeline_ps"] == "uv run fourok-dev pipeline-ps"
    assert report["usage"]["app_up"] == "uv run fourok-dev app-up"
    assert report["usage"]["core_up"] == "uv run fourok-dev core-up"
    assert report["usage"]["observability_up"] == "uv run fourok-dev observability-up"
    assert report["usage"]["stack_up"] == "uv run fourok-dev stack-up  # core only"


def test_connector_secret_report_flags_missing_required_live_connector_keys() -> None:
    report = connector_secret_report(
        {
            "SLACK_BOT_TOKEN": "xoxb",
            "LINEAR_API_KEY": "lin",
            "TWENTY_API_KEY": "twenty",
            "GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON": "{}",
        }
    )

    assert report["status"] == "missing"
    assert report["connectors"]["slack"]["status"] == "ok"
    assert report["connectors"]["linear"]["status"] == "ok"
    assert report["connectors"]["twenty"]["status"] == "ok"
    assert report["connectors"]["google_drive"]["status"] == "missing"
    assert report["connectors"]["google_drive"]["missing"] == [
        "GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN"
    ]
    assert "values" not in report["connectors"]["slack"]


def test_warm_docker_plan_pulls_known_slow_profiles() -> None:
    plan = build_plan("warm-docker", [])

    assert [step.name for step in plan] == [
        "pull-observability",
        "pull-pipeline",
    ]
    assert plan[0].command == ("docker", "compose", "--profile", "observability", "pull")
    assert plan[1].command == ("docker", "compose", "--profile", "pipeline", "pull")


def test_install_hooks_writes_versioned_hook_entrypoints(tmp_path: Path) -> None:
    hooks_dir = tmp_path / ".git" / "hooks"
    hooks_dir.mkdir(parents=True)

    written = install_hooks(tmp_path)

    assert written == [
        hooks_dir / "pre-commit",
        hooks_dir / "pre-push",
    ]
    assert (hooks_dir / "pre-commit").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\nset -euo pipefail\n\nuv run fourok-dev fast\n"
    )
    assert (hooks_dir / "pre-push").read_text(encoding="utf-8") == (
        "#!/usr/bin/env bash\nset -euo pipefail\n\nuv run fourok-dev full\n"
    )


def test_install_hooks_supports_linked_worktree_git_file(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "worktree"
    common_git_dir = tmp_path / "repo" / ".git"
    hooks_dir = common_git_dir / "hooks"
    project_root.mkdir()
    hooks_dir.mkdir(parents=True)
    (project_root / ".git").write_text(
        f"gitdir: {common_git_dir / 'worktrees' / 'operator-live-ux'}\n",
        encoding="utf-8",
    )

    def fake_git_lines(*args: str) -> list[str]:
        assert args == ("-C", str(project_root), "rev-parse", "--git-common-dir")
        return [str(common_git_dir)]

    monkeypatch.setattr("fourok.devtools.dev._git_lines", fake_git_lines)

    written = install_hooks(project_root)

    assert written == [
        hooks_dir / "pre-commit",
        hooks_dir / "pre-push",
    ]


def test_logs_status_report_summarizes_loki_labels_counts_and_queries() -> None:
    calls: list[dict[str, object]] = []

    def fake_loki(url: str, path: str, params=None):
        calls.append({"url": url, "path": path, "params": params or {}})
        if path == "/loki/api/v1/label/compose_service/values":
            return {"status": "success", "data": ["dagster-code", "dagster-daemon"]}
        return {
            "status": "success",
            "data": {
                "result": [
                    {"stream": {"compose_service": "dagster-code"}, "values": [["1", "line"]]},
                    {"stream": {"compose_service": "dagster-daemon"}, "values": [["2", "line"]]},
                ]
            },
        }

    report = logs_status_report(loki_url="http://loki.example", loki=fake_loki)

    assert report["status"] == "ok"
    assert report["compose_services"] == ["dagster-code", "dagster-daemon"]
    assert report["queries"]["all_fourok"] == '{compose_project="4ok"}'
    assert (
        report["queries"]["dagster_failures"]
        == '{compose_service="dagster-code"} |= "STEP_FAILURE"'
    )
    assert report["counts"]["all_fourok"]["entries"] == 2
    assert len(calls) == 4


def test_dagster_status_entrypoint_reports_repository_health() -> None:
    payloads: list[dict[str, object]] = []

    def fake_graphql(url: str, query: str, variables=None):
        payloads.append({"url": url, "query": query, "variables": variables})
        if "repositoriesOrError" in query:
            return {
                "data": {
                    "repositoriesOrError": {
                        "__typename": "RepositoryConnection",
                        "nodes": [
                            {
                                "name": "__repository__",
                                "location": {"name": "fourok_pipeline"},
                                "pipelines": [{"name": "fourok_hourly_live_backfill"}],
                                "schedules": [
                                    {
                                        "name": "fourok_hourly_live_backfill_schedule",
                                        "scheduleState": {"status": "RUNNING"},
                                    }
                                ],
                                "sensors": [
                                    {
                                        "name": "fourok_webhook_backlog_sensor",
                                        "sensorState": {"status": "RUNNING"},
                                    }
                                ],
                            }
                        ],
                    }
                }
            }
        return {
            "data": {
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "run-1",
                            "status": "SUCCESS",
                            "startTime": 1781164400.0,
                            "endTime": 9999999999.0,
                            "stepStats": [
                                {"stepKey": "fourok_retrieval_records", "status": "SUCCESS"}
                            ],
                        }
                    ],
                }
            }
        }

    report = dagster_status_report(
        dagster_url="http://dagster.example/graphql",
        graphql=fake_graphql,
    )

    assert report["repository_status"] == "ok"
    runtime_status = report["runtime_status"]
    assert isinstance(runtime_status, dict)
    assert runtime_status["status"] == "ok"
    assert runtime_status["latest_run_status"] == "SUCCESS"
    assert report["schedules"]["fourok_hourly_live_backfill_schedule"] == "RUNNING"
    assert report["latest_runs"][0]["run_id"] == "run-1"
    assert report["latest_runs"][0]["step_statuses"]["fourok_retrieval_records"] == "SUCCESS"
    assert len(payloads) == 2


def test_dagster_status_flags_failed_latest_step_as_runtime_failure() -> None:
    def fake_graphql(url: str, query: str, variables=None):
        if "repositoriesOrError" in query:
            return {
                "data": {
                    "repositoriesOrError": {
                        "__typename": "RepositoryConnection",
                        "nodes": [
                            {
                                "name": "__repository__",
                                "location": {"name": "fourok_pipeline"},
                                "pipelines": [{"name": "fourok_hourly_live_backfill"}],
                                "schedules": [
                                    {
                                        "name": "fourok_hourly_live_backfill_schedule",
                                        "scheduleState": {"status": "RUNNING"},
                                    }
                                ],
                                "sensors": [],
                            }
                        ],
                    }
                }
            }
        return {
            "data": {
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [
                        {
                            "runId": "run-failed",
                            "status": "FAILURE",
                            "endTime": 9999999999.0,
                            "stepStats": [
                                {
                                    "stepKey": "meltano_slack_live_raw_landing",
                                    "status": "FAILURE",
                                }
                            ],
                        },
                        {
                            "runId": "run-success",
                            "status": "SUCCESS",
                            "endTime": 9999999998.0,
                            "stepStats": [],
                        },
                    ],
                }
            }
        }

    report = dagster_status_report(
        dagster_url="http://dagster.example/graphql",
        graphql=fake_graphql,
    )

    runtime_status = report["runtime_status"]
    assert isinstance(runtime_status, dict)
    assert runtime_status["status"] == "failed"
    assert runtime_status["latest_run_status"] == "FAILURE"
    assert runtime_status["failed_or_incomplete_steps"] == {
        "meltano_slack_live_raw_landing": "FAILURE"
    }


def test_dagster_status_entrypoint_discovers_fourok_repository_from_multiple_nodes() -> None:
    def fake_graphql(url: str, query: str, variables=None):
        if "repositoriesOrError" in query:
            return {
                "data": {
                    "repositoriesOrError": {
                        "__typename": "RepositoryConnection",
                        "nodes": [
                            {
                                "name": "other_repository",
                                "location": {"name": "other-location"},
                                "pipelines": [{"name": "other_job"}],
                                "schedules": [
                                    {
                                        "name": "other_schedule",
                                        "scheduleState": {"status": "RUNNING"},
                                    }
                                ],
                                "sensors": [],
                            },
                            {
                                "name": "__repository__",
                                "location": {"name": "fourok_pipeline"},
                                "pipelines": [{"name": "fourok_hourly_live_backfill"}],
                                "schedules": [
                                    {
                                        "name": "fourok_hourly_live_backfill_schedule",
                                        "scheduleState": {"status": "RUNNING"},
                                    }
                                ],
                                "sensors": [
                                    {
                                        "name": "fourok_webhook_backlog_sensor",
                                        "sensorState": {"status": "RUNNING"},
                                    }
                                ],
                            },
                        ],
                    }
                }
            }
        return {
            "data": {
                "runsOrError": {
                    "__typename": "Runs",
                    "results": [],
                }
            }
        }

    report = dagster_status_report(
        dagster_url="http://dagster.example/graphql",
        graphql=fake_graphql,
    )

    assert report["repository_status"] == "ok"
    assert report["location"] == "fourok_pipeline"
    assert report["schedules"]["fourok_hourly_live_backfill_schedule"] == "RUNNING"
    assert report["sensors"]["fourok_webhook_backlog_sensor"] == "RUNNING"


def test_module_entrypoint_executes_dev_cli() -> None:
    result = subprocess.run(
        ["python", "-m", "fourok.devtools.dev", "fast", "--dry-run"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "format-check" in result.stdout
    assert "test-tracked" in result.stdout
