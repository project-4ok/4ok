from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).parents[3] / "scripts" / "inspect_gmail_pilot_output.py"
SPEC = importlib.util.spec_from_file_location("inspect_gmail_pilot_output", SCRIPT_PATH)
assert SPEC is not None
inspector = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = inspector
SPEC.loader.exec_module(inspector)

inspect_singer_output = inspector.inspect_singer_output
write_summary = inspector.write_summary


def test_gmail_pilot_output_inspector_summarizes_stream_fields(tmp_path: Path) -> None:
    raw_output = tmp_path / "tap-output.jsonl"
    raw_output.write_text(
        "\n".join(
            [
                '{"type":"SCHEMA","stream":"messages","schema":{}}',
                (
                    '{"type":"RECORD","stream":"messages","record":'
                    '{"id":"msg-1","thread_id":"thread-1","date":"2026-05-24",'
                    '"body":"secret body text","snippet":"secret snippet",'
                    '"attachments":[{"filename":"note.txt","body":"secret attachment"}]}}'
                ),
                '{"type":"STATE","value":{"bookmark":"msg-1"}}',
            ]
        ),
        encoding="utf-8",
    )

    summary = inspect_singer_output(raw_output)

    assert summary["schema_messages"] == 1
    assert summary["state_messages"] == 1
    assert summary["record_count"] == 1
    assert summary["checks"] == [
        {
            "detail": "At least one connector record is required.",
            "name": "records_present",
            "status": "pass",
        },
        {
            "detail": "State messages are needed to validate incremental sync behavior.",
            "name": "state_messages_present",
            "status": "pass",
        },
        {
            "detail": "Schema messages help understand connector stream contracts.",
            "name": "schema_messages_present",
            "status": "pass",
        },
        {
            "detail": "Best stream 'messages' missing required groups: none.",
            "name": "source_record_required_fields",
            "status": "pass",
        },
        {
            "detail": "Best stream 'messages' missing desirable groups: source_url, labels.",
            "name": "source_record_desirable_fields",
            "status": "warning",
        },
    ]
    assert summary["streams"][0]["stream"] == "messages"
    assert summary["streams"][0]["fields"] == [
        "attachments",
        "body",
        "date",
        "id",
        "snippet",
        "thread_id",
    ]
    assert summary["streams"][0]["required_presence"] == {
        "body": True,
        "id": True,
        "thread": True,
        "timestamp": True,
    }
    serialized = json.dumps(summary)
    assert "secret body text" not in serialized
    assert "secret snippet" not in serialized
    assert "secret attachment" not in serialized
    assert '"redacted": true' in serialized


def test_gmail_pilot_output_inspector_reports_missing_required_fields(tmp_path: Path) -> None:
    raw_output = tmp_path / "tap-output.jsonl"
    raw_output.write_text(
        '{"type":"RECORD","stream":"messages","record":{"id":"msg-1"}}\n',
        encoding="utf-8",
    )

    stream = inspect_singer_output(raw_output)["streams"][0]

    assert stream["required_presence"] == {
        "body": False,
        "id": True,
        "thread": False,
        "timestamp": False,
    }

    checks = inspect_singer_output(raw_output)["checks"]
    assert {(check["name"], check["status"]) for check in checks} >= {
        ("state_messages_present", "warning"),
        ("schema_messages_present", "warning"),
        ("source_record_required_fields", "fail"),
    }


def test_gmail_pilot_output_inspector_writes_summary(tmp_path: Path) -> None:
    output = tmp_path / "nested" / "summary.json"
    summary = {"record_count": 1, "streams": []}

    write_summary(summary, output)

    assert output.read_text(encoding="utf-8") == '{\n  "record_count": 1,\n  "streams": []\n}'
