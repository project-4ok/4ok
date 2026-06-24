from __future__ import annotations

from pathlib import Path

from fourok.secrets.env import (
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
            "TAP_GMAIL_MESSAGES_Q='newer_than:30d fourok-PILOT'",
            "# comment",
            "",
        ]
    )

    assert values == {
        "TAP_GMAIL_USER_ID": "pilot@example.com",
        "TAP_GMAIL_MESSAGES_Q": "newer_than:30d fourok-PILOT",
    }


def test_parse_dotenv_export_lines_accepts_empty_and_unquoted_values_with_spaces() -> None:
    values = parse_dotenv_export_lines(
        [
            "LINEAR_LIMIT=1000",
            "TAP_SLACK_SELECTED_CHANNELS=",
            "OPENAI_API_KEY=value with spaces copied from a shell",
        ]
    )

    assert values == {
        "LINEAR_LIMIT": "1000",
        "TAP_SLACK_SELECTED_CHANNELS": "",
        "OPENAI_API_KEY": "value with spaces copied from a shell",
    }


def test_parse_json_export_supports_object_and_list_shapes() -> None:
    assert parse_json_export('{"LINEAR_API_KEY":"linear-value"}') == {
        "LINEAR_API_KEY": "linear-value"
    }
    assert parse_json_export(
        '[{"key":"TWENTY_API_KEY","value":"twenty-value"},'
        '{"secretKey":"SLACK_BOT_TOKEN","secretValue":"slack-value"}]'
    ) == {
        "TWENTY_API_KEY": "twenty-value",
        "SLACK_BOT_TOKEN": "slack-value",
    }


def test_effective_env_loads_dotenv_without_overriding_process_env(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text(
        "LINEAR_API_KEY=from_file\nSLACK_BOT_TOKEN=from_file\n",
        encoding="utf-8",
    )

    env = effective_env(dotenv_path=dotenv, base={"LINEAR_API_KEY": "from_process"})

    assert env["LINEAR_API_KEY"] == "from_process"
    assert env["SLACK_BOT_TOKEN"] == "from_file"


def test_load_dotenv_returns_empty_for_missing_file(tmp_path: Path) -> None:
    assert load_dotenv(tmp_path / ".env") == {}


def test_redacted_env_report_never_exposes_values_for_sensitive_keys() -> None:
    report = redacted_env_report(
        {"LINEAR_API_KEY": "linear-value", "LINEAR_GRAPHQL_URL": "https://api.linear.app/graphql"},
        keys=("LINEAR_API_KEY", "LINEAR_GRAPHQL_URL", "SLACK_BOT_TOKEN"),
    )

    assert report == {
        "LINEAR_API_KEY": "[REDACTED]",
        "LINEAR_GRAPHQL_URL": "https://api.linear.app/graphql",
        "SLACK_BOT_TOKEN": "missing",
    }
    assert "linear-value" not in str(report)
