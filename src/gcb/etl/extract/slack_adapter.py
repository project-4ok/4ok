from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from gcb.etl.extract.source_records import SourceIdentity, SourceRecord

SLACK_LANDED_STREAMS = ("channels", "messages", "threads", "users", "channel_members")


def load_slack_landed_source_records(
    landing_path: Path,
    *,
    streams: tuple[str, ...] = SLACK_LANDED_STREAMS,
) -> list[SourceRecord]:
    records = []
    for stream in streams:
        record_path = landing_path / f"{stream}.jsonl"
        if not record_path.exists():
            continue
        for line_number, line in enumerate(
            record_path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"Invalid landed Slack JSON on line {line_number}: {error.msg}"
                ) from error
            if not isinstance(record, dict):
                raise ValueError(f"Landed Slack record line {line_number} is not an object")
            records.append(slack_source_record_from_raw(stream, record))
    return sorted(records, key=lambda record: record.source_ref)


def slack_source_record_from_raw(stream: str, record: dict[str, Any]) -> SourceRecord:
    if stream in {"messages", "threads", "slack_messages"}:
        return slack_message_source_record_from_raw(record, stream=stream)
    if stream == "users":
        return slack_user_source_record_from_raw(record)
    if stream == "channels":
        return slack_channel_source_record_from_raw(record)
    if stream == "channel_members":
        return slack_channel_member_source_record_from_raw(record)
    raise ValueError(f"Unsupported Slack stream: {stream}")


def slack_message_source_record_from_raw(
    record: dict[str, Any], *, stream: str = "messages"
) -> SourceRecord:
    channel_id = _first_string(record, "channel_id", "channel")
    timestamp = _first_string(record, "ts", "timestamp")
    if channel_id is None or timestamp is None:
        raise ValueError("Slack message record requires channel_id and ts")

    text = _first_string(record, "text", "body", "plain_text")
    text_missing = not bool(text)
    if not text:
        text = _slack_textless_message_body(record)

    user_id = _first_string(record, "user", "user_id", "author_id")
    metadata = {
        "channel_id": channel_id,
        "channel_name": _first_string(record, "channel_name", "conversation_name") or channel_id,
        "source_object_type": "message",
        "team_id": _first_string(record, "team_id", "team") or "",
        "user_name": _first_string(record, "user_name", "author_name") or "",
        "conversation_id": _first_string(record, "conversation_id") or "",
    }
    if text_missing:
        metadata["text_missing"] = "true"
        metadata["subtype"] = _first_string(record, "subtype") or ""
    channel_name = _first_string(record, "channel_name", "conversation_name") or channel_id
    thread_ts = _first_string(record, "thread_ts") or timestamp
    identities = _slack_message_identities(record, user_id)

    return SourceRecord(
        source_ref=f"slack:message:{channel_id}:{timestamp}",
        source_system="slack",
        source_id=f"{channel_id}:{timestamp}",
        record_type="message",
        title=f"#{channel_name}",
        body=text,
        occurred_at=timestamp,
        updated_at=_first_string(record, "updated_at", "edited_ts") or "",
        author_ref=f"slack:user:{user_id}" if user_id else "",
        source_url=_first_string(record, "permalink", "source_url", "url") or "",
        thread_ref=f"slack:thread:{channel_id}:{thread_ts}",
        permission_refs=tuple(_slack_permission_refs(record, channel_id)),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state="deleted" if record.get("deleted") is True else "active",
        metadata=_compact_metadata(metadata),
        raw=record,
        raw_ref=f"slack:raw:{stream}:{channel_id}:{timestamp}",
        source_identities=tuple(identities),
    )


def slack_user_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _required_string(record, "id", "Slack user record requires id")
    display_name = _first_string(record, "real_name", "name") or source_id
    profile = record.get("profile") if isinstance(record.get("profile"), dict) else {}
    email = _first_string(profile, "email") if isinstance(profile, dict) else None
    identities = _slack_user_identities(source_id, email, display_name)

    return SourceRecord(
        source_ref=f"slack:user:{source_id}",
        source_system="slack",
        source_id=source_id,
        record_type="person",
        title=display_name,
        body=_join_text(display_name, _first_string(record, "name"), email),
        updated_at=str(record.get("updated") or ""),
        permission_refs=tuple(_slack_user_permission_refs(record)),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state="deleted" if record.get("deleted") is True else "active",
        metadata=_compact_metadata(
            {
                "source_object_type": "user",
                "team_id": _first_string(record, "team_id") or "",
                "is_bot": str(record.get("is_bot")).lower()
                if isinstance(record.get("is_bot"), bool)
                else "",
            }
        ),
        raw=record,
        source_identities=tuple(identities),
    )


def slack_channel_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _required_string(record, "id", "Slack channel record requires id")
    name = _first_string(record, "name", "name_normalized") or source_id

    return SourceRecord(
        source_ref=f"slack:channel:{source_id}",
        source_system="slack",
        source_id=source_id,
        record_type="work_item",
        title=f"#{name}",
        body=_join_text(name, _nested_value(record, "topic"), _nested_value(record, "purpose")),
        occurred_at=str(record.get("created") or ""),
        author_ref=_first_string(record, "creator") or "",
        thread_ref=f"slack:channel:{source_id}",
        permission_refs=tuple(_slack_permission_refs(record, source_id)),
        lifecycle_state="deleted" if record.get("is_archived") is True else "active",
        metadata=_compact_metadata(
            {
                "source_object_type": "channel",
                "channel_name": name,
                "num_members": str(record.get("num_members") or ""),
            }
        ),
        raw=record,
    )


def slack_channel_member_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    channel_id = _required_string(
        record,
        "channel_id",
        "Slack channel member record requires channel_id",
    )
    member_id = _required_string(
        record,
        "member_id",
        "Slack channel member record requires member_id",
    )

    return SourceRecord(
        source_ref=f"slack:channel_member:{channel_id}:{member_id}",
        source_system="slack",
        source_id=f"{channel_id}:{member_id}",
        record_type="relationship",
        title=f"{member_id} in {channel_id}",
        body=f"Slack user {member_id} is a member of channel {channel_id}",
        thread_ref=f"slack:channel:{channel_id}",
        permission_refs=(f"slack:channel:{channel_id}",),
        identity_refs=(f"slack:user:{member_id}",),
        metadata={
            "source_object_type": "channel_member",
            "channel_id": channel_id,
            "member_id": member_id,
        },
        raw=record,
    )


def _slack_message_identities(record: dict[str, Any], user_id: str | None) -> list[SourceIdentity]:
    if not user_id:
        return []
    return [
        SourceIdentity(
            source_system="slack",
            identity_ref=f"slack:user:{user_id}",
            identity_type="author",
            value=user_id,
            display_name=_first_string(record, "user_name", "author_name") or "",
        )
    ]


def _slack_user_identities(
    source_id: str, email: str | None, display_name: str
) -> list[SourceIdentity]:
    identities = [
        SourceIdentity(
            source_system="slack",
            identity_ref=f"slack:user:{source_id}",
            identity_type="user",
            value=source_id,
            display_name=display_name,
        )
    ]
    if email:
        identities.append(
            SourceIdentity(
                source_system="slack",
                identity_ref=f"slack:email:{email.strip().casefold()}",
                identity_type="email",
                value=email,
                display_name=display_name,
            )
        )
    return identities


def _slack_permission_refs(record: dict[str, Any], channel_id: str) -> list[str]:
    explicit = _string_list(record.get("permission_refs", []))
    if explicit:
        return _dedupe_strings(explicit)
    return [f"slack:channel:{channel_id}"]


def _slack_user_permission_refs(record: dict[str, Any]) -> list[str]:
    team_id = _first_string(record, "team_id")
    return [f"slack:team:{team_id}"] if team_id else []


def _slack_textless_message_body(record: dict[str, Any]) -> str:
    subtype = _first_string(record, "subtype") or "message"
    user = _first_string(record, "user", "user_id", "author_id")
    return _join_text("Slack message without text", subtype, user)


def _required_string(record: dict[str, Any], key: str, message: str) -> str:
    value = _first_string(record, key)
    if value is None:
        raise ValueError(message)
    return value


def _first_string(record: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _join_text(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _nested_value(record: dict[str, Any], key: str) -> str:
    value = record.get(key)
    if not isinstance(value, dict):
        return ""
    return _first_string(value, "value") or ""


def _compact_metadata(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped
