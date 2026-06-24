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
        "fourok.cli_parts.commands_runtime.health_database_url",
        lambda **_kwargs: "postgresql+psycopg://fourok:secret@postgres:5432/fourok",
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.create_governed_context_state",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.check_runtime_health",
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


def test_status_json_is_available_for_agents(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "status", "--json"])
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.health_database_url",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.create_governed_context_state",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.check_runtime_health",
        lambda _state: {"status": "ok", "checks": []},
    )

    main()

    assert json.loads(capsys.readouterr().out)["status"] == "ok"


def test_onboard_connectors_is_guidance_not_secret_collection(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["fourok", "onboard", "connectors"])

    main()

    output = capsys.readouterr().out
    assert "Connector onboarding" in output
    assert "does not collect or store secrets" in output
    assert "fourok admin connector-jobs" in output
