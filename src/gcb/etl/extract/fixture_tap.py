from __future__ import annotations

import os
import sys
from pathlib import Path

DEFAULT_FIXTURE = Path("fixtures/connectors/singer_email_messages.jsonl")


def main() -> None:
    fixture_path = Path(
        os.environ.get("TAP_GCB_FIXTURE_FIXTURE_PATH")
        or os.environ.get("TAP_GCB_SLACK_FIXTURE_FIXTURE_PATH")
        or os.environ.get("TAP_GCB_TWENTY_FIXTURE_FIXTURE_PATH")
        or os.environ.get("TAP_GCB_LINEAR_FIXTURE_FIXTURE_PATH")
        or os.environ.get("TAP_GCB_GOOGLE_DRIVE_FIXTURE_FIXTURE_PATH")
        or DEFAULT_FIXTURE
    )
    with fixture_path.open(encoding="utf-8") as fixture:
        for line in fixture:
            sys.stdout.write(line)
