from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_INPUT = Path(".local/gmail-pilot/tap-gmail-output.jsonl")
DEFAULT_OUTPUT = Path(".local/gmail-pilot/inspection-summary.json")
REQUIRED_SOURCE_FIELDS = {
    "id": ("id", "message_id"),
    "thread": ("thread_id", "threadId", "thread_ref"),
    "timestamp": ("date", "timestamp", "internalDate", "created_at", "updated_at"),
    "body": ("body", "text", "plain_text", "snippet"),
}
DESIRABLE_SOURCE_FIELDS = {
    "source_url": ("source_url", "web_url", "url"),
    "attachments": ("attachments", "attachment_refs", "parts", "payload"),
    "labels": ("label_ids", "labelIds", "labels"),
}
SENSITIVE_FIELD_HINTS = (
    "body",
    "text",
    "plain_text",
    "html",
    "snippet",
    "payload",
    "raw",
    "value",
    "access_token",
    "refresh_token",
    "client_secret",
)


@dataclass(frozen=True)
class StreamInspection:
    stream: str
    record_count: int
    fields: list[str]
    required_presence: dict[str, bool]
    desirable_presence: dict[str, bool]
    sample_shape: dict[str, Any]


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    detail: str


def inspect_singer_output(path: Path) -> dict[str, Any]:
    schemas = 0
    states = 0
    streams: Counter[str] = Counter()
    fields_by_stream: dict[str, set[str]] = defaultdict(set)
    sample_by_stream: dict[str, dict[str, Any]] = {}

    for message in _read_messages(path):
        message_type = message.get("type")
        if message_type == "SCHEMA":
            schemas += 1
            continue
        if message_type == "STATE":
            states += 1
            continue
        if message_type != "RECORD":
            continue

        stream = _string(message.get("stream"), default="unknown")
        record = message.get("record")
        if not isinstance(record, dict):
            continue
        streams[stream] += 1
        fields_by_stream[stream].update(record.keys())
        sample_by_stream.setdefault(stream, _shape(record))

    stream_inspections = [
        StreamInspection(
            stream=stream,
            record_count=count,
            fields=sorted(fields_by_stream[stream]),
            required_presence=_presence(fields_by_stream[stream], REQUIRED_SOURCE_FIELDS),
            desirable_presence=_presence(fields_by_stream[stream], DESIRABLE_SOURCE_FIELDS),
            sample_shape=sample_by_stream.get(stream, {}),
        )
        for stream, count in sorted(streams.items())
    ]
    return {
        "input": path.as_posix(),
        "schema_messages": schemas,
        "state_messages": states,
        "record_count": sum(streams.values()),
        "streams": [asdict(stream) for stream in stream_inspections],
        "checks": [asdict(check) for check in _checks(schemas, states, stream_inspections)],
    }


def write_summary(summary: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect raw Gmail pilot Singer output safely.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    summary = inspect_singer_output(args.input)
    write_summary(summary, args.output)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _read_messages(path: Path) -> list[dict[str, Any]]:
    messages = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid Singer JSON on line {line_number}: {error.msg}") from error
        if not isinstance(message, dict):
            raise ValueError(f"Singer message line {line_number} is not an object")
        messages.append(message)
    return messages


def _presence(fields: set[str], groups: dict[str, tuple[str, ...]]) -> dict[str, bool]:
    return {
        name: any(field in fields for field in candidates) for name, candidates in groups.items()
    }


def _checks(
    schemas: int,
    states: int,
    streams: list[StreamInspection],
) -> list[CheckResult]:
    checks = [
        CheckResult(
            name="records_present",
            status="pass" if any(stream.record_count for stream in streams) else "fail",
            detail="At least one connector record is required.",
        ),
        CheckResult(
            name="state_messages_present",
            status="pass" if states else "warning",
            detail="State messages are needed to validate incremental sync behavior.",
        ),
        CheckResult(
            name="schema_messages_present",
            status="pass" if schemas else "warning",
            detail="Schema messages help understand connector stream contracts.",
        ),
    ]
    if not streams:
        checks.append(
            CheckResult(
                name="source_record_required_fields",
                status="fail",
                detail="No record stream was available to inspect for source-record fields.",
            )
        )
        return checks

    best_stream = _best_stream(streams)
    missing_required = [
        name for name, present in best_stream.required_presence.items() if not present
    ]
    missing_desirable = [
        name for name, present in best_stream.desirable_presence.items() if not present
    ]
    checks.append(
        CheckResult(
            name="source_record_required_fields",
            status="pass" if not missing_required else "fail",
            detail=(
                f"Best stream {best_stream.stream!r} missing required groups: "
                f"{', '.join(missing_required) or 'none'}."
            ),
        )
    )
    checks.append(
        CheckResult(
            name="source_record_desirable_fields",
            status="pass" if not missing_desirable else "warning",
            detail=(
                f"Best stream {best_stream.stream!r} missing desirable groups: "
                f"{', '.join(missing_desirable) or 'none'}."
            ),
        )
    )
    return checks


def _best_stream(streams: list[StreamInspection]) -> StreamInspection:
    return max(
        streams,
        key=lambda stream: (
            sum(stream.required_presence.values()),
            sum(stream.desirable_presence.values()),
            stream.record_count,
        ),
    )


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        shaped = {}
        for key, nested in sorted(value.items()):
            if _is_sensitive_field(key):
                shaped[key] = _redacted_shape(nested)
            else:
                shaped[key] = _shape(nested)
        return shaped
    if isinstance(value, list):
        if not value:
            return {"type": "list", "length": 0}
        return {"type": "list", "length": len(value), "sample": _shape(value[0])}
    return {"type": type(value).__name__, "present": value is not None}


def _redacted_shape(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        return {"type": "str", "redacted": True, "length": len(value)}
    if isinstance(value, list):
        return {"type": "list", "redacted": True, "length": len(value)}
    if isinstance(value, dict):
        return {"type": "dict", "redacted": True, "keys": sorted(value.keys())}
    return {"type": type(value).__name__, "redacted": True}


def _is_sensitive_field(field: str) -> bool:
    normalized = field.casefold()
    return any(hint in normalized for hint in SENSITIVE_FIELD_HINTS)


def _string(value: Any, *, default: str) -> str:
    if isinstance(value, str) and value:
        return value
    return default


if __name__ == "__main__":
    raise SystemExit(main())
