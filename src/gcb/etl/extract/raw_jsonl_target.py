from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from gcb.etl.extract.connectors import land_singer_stream

DEFAULT_LANDING_DIR = Path(".local/raw/singer")


def main() -> None:
    landing_dir = Path(os.environ.get("TARGET_GCB_RAW_JSONL_LANDING_DIR", DEFAULT_LANDING_DIR))
    report = land_singer_stream(sys.stdin, landing_dir)
    print(
        json.dumps(
            {
                "landing_dir": str(landing_dir),
                "record_count": report.record_count,
                "streams": report.streams,
                "schema_messages": report.schema_messages,
                "state_messages": report.state_messages,
                "state_path": str(report.state_path) if report.state_path else "",
            },
            sort_keys=True,
        ),
        file=sys.stderr,
    )
