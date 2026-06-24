from __future__ import annotations

from pathlib import Path

from gcb.secrets.env import (
    effective_env,
    load_dotenv,
    parse_dotenv_export_lines,
    parse_json_export,
    redacted_env_report,
)


def test_parse_dotenv_export_lines_supports_export_quotes_and_comments() -> None:
    values = parse_dotenv_export_lines(
        [
            'export TAP_GMAIL_USER_ID="pilot@example.com"',
            "TAP_GMAIL_MESSAGES_Q='newer_than:30d GCB-PILOT'",
            "# comment",
            "",
        ]
    )

    assert values == {
        "TAP_GMAIL_USER_ID": "pilot@example.com",
        "TAP_GMAIL_MESSAGES_Q": "newer_than:30d GCB-PILOT",
    }


def test_parse_json_export_supports_object_and_list_shapes() -> None:
    assert parse_json_export('{"LINEAR_API_KEY":"linear-secret"}') == {
        "LINEAR_API_KEY": "linear-secret"
    }
    assert parse_json_export(
        '[{"key":"TWENTY_API_KEY","value":"twenty-secret"},'
        '{"secretKey":"SLACK_BOT_TOKEN","secretValue":"slack-secret"}]'
    ) == {
        "TWENTY_API_KEY": "twenty-secret",
        "SLACK_BOT_TOKEN": "slack-secret",
    }


def test_effective_env_loads_dotenv_without_overriding_process_env(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "LINEAR_API_KEY=from-dotenv\nSLACK_BOT_TOKEN=from-dotenv\n",
        encoding="utf-8",
    )

    env = effective_env(dotenv_path=dotenv, base={"LINEAR_API_KEY": "from-process"})

    assert env["LINEAR_API_KEY"] == "from-process"
    assert env["SLACK_BOT_TOKEN"] == "from-dotenv"


def test_load_dotenv_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / ".env") == {}


def test_redacted_env_report_never_exposes_secret_values() -> None:
    report = redacted_env_report(
        {"LINEAR_API_KEY": "linear-secret", "LINEAR_GRAPHQL_URL": "https://api.linear.app/graphql"},
        keys=("LINEAR_API_KEY", "LINEAR_GRAPHQL_URL", "SLACK_BOT_TOKEN"),
    )

    assert report == {
        "LINEAR_API_KEY": "[REDACTED]",
        "LINEAR_GRAPHQL_URL": "https://api.linear.app/graphql",
        "SLACK_BOT_TOKEN": "missing",
    }
    assert "linear-secret" not in str(report)
