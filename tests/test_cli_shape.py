import json

import pytest

from fourok.cli import main
from fourok.cli_parts.parser import build_parser


def test_public_help_shows_small_client_surface() -> None:
    help_text = build_parser().format_help()

    assert "retrieve" in help_text
    assert "status" in help_text
    assert "onboard" in help_text
    assert "admin" in help_text
    assert "search-state" not in help_text
    assert "runtime-monitor" not in help_text
    assert "postgres-backup" not in help_text


def test_invalid_public_command_hints_only_public_surface(capsys) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["onboardingg"])

    error = capsys.readouterr().err
    assert exc.value.code == 2
    assert "choose from retrieve, status, onboard, admin" in error
    assert "search-state" not in error
    assert "runtime-monitor" not in error


def test_onboarding_alias_runs_onboard(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "onboarding"])
    monkeypatch.setattr(
        "fourok.runtime.cli._safe_client_status_report",
        lambda: {"status": "ok", "checks": []},
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._connector_secret_report",
        lambda: {"status": "ok", "connectors": {}},
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._dagster_code_secret_presence",
        lambda: {"status": "ok", "missing": []},
    )

    main()

    assert "fourok onboarding" in capsys.readouterr().out


def test_admin_help_contains_operator_surface() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["admin", "--help"])

    assert exc.value.code == 0


def test_retrieve_help_stays_client_facing(capsys) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["retrieve", "--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "--json" in output
    assert "--database-url" not in output
    assert "--state" not in output
    assert "--candidate-limit" not in output
    assert "--retrievers" not in output


def test_status_prints_client_safe_summary(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "status"])
    monkeypatch.setattr(
        "fourok.runtime.cli.health_database_url",
        lambda **_kwargs: "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.create_governed_context_state",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.check_runtime_health",
        lambda _state: {
            "status": "ok",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "source_records", "status": "ok", "count": 12},
                {"name": "retrieval_records", "status": "ok", "count": 34},
            ],
        },
    )

    main()

    output = capsys.readouterr().out
    assert "fourok is ready" in output
    assert "Context:" in output
    assert "12 source records" in output
    assert "34 retrieval units" in output
    assert "Try:" in output
    assert "fourok retrieve" in output
    assert "postgresql" not in output
    assert "secret" not in output


def test_status_points_to_onboarding_when_only_demo_context_exists(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "status"])
    monkeypatch.setattr(
        "fourok.runtime.cli.health_database_url",
        lambda **_kwargs: "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.create_governed_context_state",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.check_runtime_health",
        lambda _state: {
            "status": "ok",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "source_records", "status": "ok", "count": 14},
                {"name": "retrieval_records", "status": "ok", "count": 14},
            ],
        },
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._source_system_counts",
        lambda _state: {"local_email": 14},
    )

    with pytest.raises(SystemExit) as exc:
        main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "fourok needs onboarding" in output
    assert "Only demo context is present" in output
    assert "fourok onboard" in output
    assert "fourok onboard connectors" not in output
    assert 'fourok retrieve "What changed this week?"' not in output


def test_status_points_to_onboarding_when_no_context_exists(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "status"])
    monkeypatch.setattr(
        "fourok.runtime.cli.health_database_url",
        lambda **_kwargs: "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.create_governed_context_state",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.check_runtime_health",
        lambda _state: {
            "status": "failed",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "source_records", "status": "failed", "count": 0},
                {"name": "retrieval_records", "status": "failed", "count": 0},
            ],
        },
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._source_system_counts",
        lambda _state: {},
    )

    with pytest.raises(SystemExit) as exc:
        main()

    output = capsys.readouterr().out
    assert exc.value.code == 1
    assert "fourok needs onboarding" in output
    assert "No connector data has been imported yet" in output
    assert 'fourok retrieve "What changed this week?"' not in output


def test_status_json_is_available_for_agents(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "status", "--json"])
    monkeypatch.setattr(
        "fourok.runtime.cli.health_database_url",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.create_governed_context_state",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "fourok.runtime.cli.check_runtime_health",
        lambda _state: {"status": "ok", "checks": []},
    )

    main()
    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_onboard_reports_current_blockers_and_next_actions(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "onboard"])
    monkeypatch.setattr(
        "fourok.runtime.cli._safe_client_status_report",
        lambda: {
            "status": "needs_onboarding",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "source_records", "status": "ok", "count": 14},
                {"name": "retrieval_records", "status": "ok", "count": 14},
            ],
            "source_system_counts": {"local_email": 14},
            "detail": "only demo context is present",
        },
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._connector_secret_report",
        lambda: {
            "status": "missing",
            "connectors": {
                "slack": {"status": "ok", "missing": []},
                "linear": {"status": "ok", "missing": []},
                "twenty": {"status": "ok", "missing": []},
                "google_drive": {
                    "status": "missing",
                    "missing": ["GOOGLE_WORKSPACE_DRIVE_IDS"],
                },
            },
        },
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._dagster_code_secret_presence",
        lambda: {"status": "missing", "missing": ["SLACK_BOT_TOKEN"]},
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._embedding_secret_report",
        lambda: {"status": "missing", "provider": "hash"},
    )

    main()

    output = capsys.readouterr().out
    assert "Current state" in output
    assert "only demo context is present" in output
    assert "fourok works best when you connect your whole workspace" in output
    assert "These connectors are already implemented" in output
    assert "Add their secrets to .env, then refresh fourok:" in output
    assert "1. fourok onboard initial-run" in output
    assert "2. fourok status" in output
    assert "3. fourok retrieve \"What changed this week?\"" in output
    assert "google_drive: missing GOOGLE_WORKSPACE_DRIVE_IDS" in output
    assert "Better semantic search:" in output
    assert "Set OPENAI_API_KEY in .env" in output
    assert "Without it, fourok falls back to local hash embeddings" in output
    assert "Need another connector?" in output
    assert "gh issue create --repo project-4ok/4ok" in output
    assert "dagster-code is not receiving connector credentials" in output
    assert "docker compose up -d --build dagster-code" in output
    assert "fourok onboard initial-run" in output
    assert "fourok status" in output


def test_onboard_calls_out_initial_run_when_connector_configured_but_no_data(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "onboard"])
    monkeypatch.setattr(
        "fourok.runtime.cli._safe_client_status_report",
        lambda: {
            "status": "needs_onboarding",
            "checks": [
                {"name": "database", "status": "ok"},
                {"name": "source_records", "status": "failed", "count": 0},
                {"name": "retrieval_records", "status": "failed", "count": 0},
            ],
        },
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._connector_secret_report",
        lambda: {
            "status": "missing",
            "connectors": {
                "twenty": {"status": "ok", "missing": []},
                "slack": {"status": "missing", "missing": ["SLACK_BOT_TOKEN"]},
            },
        },
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._dagster_code_secret_presence",
        lambda: {"status": "ok", "missing": []},
    )
    monkeypatch.setattr(
        "fourok.runtime.cli._embedding_secret_report",
        lambda: {"status": "ok", "provider": "openai"},
    )

    main()

    output = capsys.readouterr().out
    assert "twenty: configured" in output
    assert "twenty is configured, but no connector data has been imported yet" in output
    assert "Run the initial import now:" in output
    assert "fourok onboard initial-run" in output


def test_onboard_has_no_connector_subcommand(capsys) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["onboard", "connectors"])

    assert exc.value.code == 2
    error = capsys.readouterr().err
    assert "invalid choice: 'connectors'" in error
    assert "initial-run" in error


def test_onboard_initial_run_recreates_dagster_code_and_triggers_backfill(
    capsys, monkeypatch
) -> None:
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        stdout = "ok\n" if command[0] == "docker" else '{"status": "ok"}\n'
        return type("Completed", (), {"returncode": 0, "stdout": stdout, "stderr": ""})()

    monkeypatch.setattr("sys.argv", ["fourok", "onboard", "initial-run"])
    monkeypatch.setattr("fourok.runtime.cli.subprocess.run", fake_run)

    main()

    assert commands == [
        [
            "docker",
            "compose",
            "up",
            "-d",
            "--build",
            "--force-recreate",
            "dagster-code",
        ],
        [
            "uv",
            "run",
            "fourok",
            "admin",
            "run-live-ingestion",
            "--source",
            "all",
            "--verify-live-db",
        ],
    ]
    output = capsys.readouterr().out
    assert "Recreating dagster-code" in output
    assert "Running initial live backfill" in output
    assert "fourok status" in output


def test_onboard_initial_run_fails_when_backfill_is_partial(monkeypatch) -> None:
    responses = [
        type("Completed", (), {"returncode": 0, "stdout": "ok\n", "stderr": ""})(),
        type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": '{"status": "partial", "sources": []}\n',
                "stderr": "",
            },
        )(),
    ]

    def fake_run(_command, **_kwargs):
        return responses.pop(0)

    monkeypatch.setattr("sys.argv", ["fourok", "onboard", "initial-run"])
    monkeypatch.setattr("fourok.runtime.cli.subprocess.run", fake_run)

    with pytest.raises(SystemExit) as exc:
        main()

    assert "Initial live backfill did not complete: partial" in str(exc.value)
