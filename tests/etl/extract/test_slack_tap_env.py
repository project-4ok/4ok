from __future__ import annotations

from fourok.etl.extract.slack_tap_env import apply_slack_tap_defaults


def test_slack_tap_defaults_bound_live_backfill_to_safe_hourly_scope() -> None:
    env = apply_slack_tap_defaults({})

    assert env["TAP_SLACK_INCLUDE_ADMIN_STREAMS"] == "false"
    assert env["TAP_SLACK_SELECTED_CHANNELS"] == '["C0ASNARACMT"]'
    assert env["TAP_SLACK_START_DATE"] == "2026-06-10T00:00:00Z"
    assert env["TAP_SLACK_THREAD_LOOKBACK_DAYS"] == "1"


def test_slack_tap_defaults_preserve_explicit_operator_scope() -> None:
    env = apply_slack_tap_defaults(
        {
            "TAP_SLACK_SELECTED_CHANNELS": '["CEXPLICIT"]',
            "TAP_SLACK_START_DATE": "2026-01-01T00:00:00Z",
        }
    )

    assert env["TAP_SLACK_SELECTED_CHANNELS"] == '["CEXPLICIT"]'
    assert env["TAP_SLACK_START_DATE"] == "2026-01-01T00:00:00Z"
