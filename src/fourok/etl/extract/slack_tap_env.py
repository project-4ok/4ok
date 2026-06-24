from __future__ import annotations

DEFAULT_SLACK_CHANNEL_TYPES = '["im","mpim","private_channel"]'
DEFAULT_SLACK_SELECTED_CHANNELS = '["C0ASNARACMT"]'
DEFAULT_SLACK_START_DATE = "2026-06-10T00:00:00Z"
DEFAULT_SLACK_THREAD_LOOKBACK_DAYS = "1"


def apply_slack_tap_defaults(env: dict[str, str]) -> dict[str, str]:
    if "SLACK_BOT_TOKEN" in env and "TAP_SLACK_API_KEY" not in env:
        env["TAP_SLACK_API_KEY"] = env["SLACK_BOT_TOKEN"]
    env.setdefault("TAP_SLACK_CHANNEL_TYPES", DEFAULT_SLACK_CHANNEL_TYPES)
    env.setdefault("TAP_SLACK_INCLUDE_ADMIN_STREAMS", "false")
    env.setdefault("TAP_SLACK_SELECTED_CHANNELS", DEFAULT_SLACK_SELECTED_CHANNELS)
    env.setdefault("TAP_SLACK_START_DATE", DEFAULT_SLACK_START_DATE)
    env.setdefault("TAP_SLACK_THREAD_LOOKBACK_DAYS", DEFAULT_SLACK_THREAD_LOOKBACK_DAYS)
    return env
