from __future__ import annotations

from fourok.etl.extract.slack_tap_env import apply_slack_tap_defaults


def test_slack_tap_defaults_import_all_readable_channel_types() -> None:
    env = apply_slack_tap_defaults({})

    assert env["TAP_SLACK_INCLUDE_ADMIN_STREAMS"] == "false"
    assert env["TAP_SLACK_CHANNEL_TYPES"] == '["public_channel","private_channel","mpim","im"]'
    assert "TAP_SLACK_SELECTED_CHANNELS" not in env
    assert env["TAP_SLACK_START_DATE"] == "2026-06-10T00:00:00Z"
    assert env["TAP_SLACK_THREAD_LOOKBACK_DAYS"] == "1"


def test_slack_tap_defaults_remove_operator_channel_limits() -> None:
    env = apply_slack_tap_defaults(
        {
            "TAP_SLACK_SELECTED_CHANNELS": '["CEXPLICIT"]',
            "TAP_SLACK_CHANNEL_TYPES": '["private_channel"]',
            "TAP_SLACK_START_DATE": "2026-01-01T00:00:00Z",
        }
    )

    assert "TAP_SLACK_SELECTED_CHANNELS" not in env
    assert env["TAP_SLACK_CHANNEL_TYPES"] == '["public_channel","private_channel","mpim","im"]'
    assert env["TAP_SLACK_START_DATE"] == "2026-01-01T00:00:00Z"
