from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fourok.etl.extract.source_records import SourceIdentity, SourceRecord


def load_openviking_messages_jsonl_source_records(messages_path: Path) -> list[SourceRecord]:
    records = []
    for line_number, line in enumerate(
        messages_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Invalid OpenViking JSON on line {line_number}: {error.msg}"
            ) from error
        if not isinstance(raw, dict):
            raise ValueError(f"OpenViking messages line {line_number} is not an object")
        records.append(
            openviking_message_source_record_from_raw(
                raw,
                source_path=messages_path,
                line_number=line_number,
            )
        )
    return records


def openviking_message_source_record_from_raw(
    raw: dict[str, Any],
    *,
    source_path: Path,
    line_number: int,
) -> SourceRecord:
    message = _object(raw.get("message"))
    conversation_id = _conversation_id(raw)
    session_id = _session_id(raw)
    thread_id = _thread_id(raw, session_id=session_id)
    message_id = _message_id(raw, message=message, line_number=line_number)
    role = _role(raw, message=message)
    speaker = _speaker(raw, message=message, role=role)
    body = _first_string(message, "content", "text", "body") or _first_string(
        raw, "content", "text", "body"
    )
    if not body:
        raise ValueError(f"OpenViking message {message_id} requires content, text, or body")

    timestamp = _timestamp(raw, message=message)
    source_ref = (
        f"openviking:conversation:{_ref_part(conversation_id)}:"
        f"session:{_ref_part(session_id)}:message:{_ref_part(message_id)}"
    )
    source_id = f"{conversation_id}:{session_id}:{message_id}"
    source_path_ref = _source_path_ref(raw, source_path)
    identities = _speaker_identities(speaker)

    return SourceRecord(
        source_ref=source_ref,
        source_system="openviking",
        source_id=source_id,
        record_type="message",
        title=f"OpenViking {role} message in {conversation_id}",
        body=body,
        occurred_at=timestamp,
        updated_at=timestamp,
        author_ref=f"openviking:speaker:{speaker}" if speaker else "",
        thread_ref=(
            f"openviking:conversation:{_ref_part(conversation_id)}:thread:{_ref_part(thread_id)}"
        ),
        permission_refs=tuple(_permission_refs(raw, conversation_id)),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        metadata=_metadata(
            raw,
            message=message,
            conversation_id=conversation_id,
            session_id=session_id,
            thread_id=thread_id,
            message_id=message_id,
            role=role,
            speaker=speaker,
            source_path_ref=source_path_ref,
            line_number=line_number,
        ),
        raw=raw,
        raw_ref=f"{source_path_ref}#{source_ref}",
        source_identities=tuple(identities),
    )


def _conversation_id(raw: dict[str, Any]) -> str:
    conversation = raw.get("conversation")
    if isinstance(conversation, str):
        return conversation
    if isinstance(conversation, dict):
        value = _first_string(conversation, "id", "conversation_id")
        if value:
            return value
    return _first_string(raw, "conversation_id", "conversationId", "conversation_ref") or "unknown"


def _session_id(raw: dict[str, Any]) -> str:
    session = raw.get("session")
    if isinstance(session, str):
        return session
    if isinstance(session, dict):
        value = _first_string(session, "id", "session_id")
        if value:
            return value
    return _first_string(raw, "session_id", "sessionId", "chat_id", "run_id") or "default"


def _thread_id(raw: dict[str, Any], *, session_id: str) -> str:
    thread = raw.get("thread")
    if isinstance(thread, str):
        return thread
    if isinstance(thread, dict):
        value = _first_string(thread, "id", "thread_id")
        if value:
            return value
    return _first_string(raw, "thread_id", "threadId", "thread_ref") or session_id


def _message_id(raw: dict[str, Any], *, message: dict[str, Any], line_number: int) -> str:
    return (
        _first_string(message, "id", "message_id", "messageId")
        or _first_string(raw, "message_id", "messageId", "id")
        or f"line-{line_number:06d}"
    )


def _role(raw: dict[str, Any], *, message: dict[str, Any]) -> str:
    return (
        _first_string(message, "role", "sender_role")
        or _first_string(raw, "role", "sender_role")
        or "unknown"
    )


def _speaker(raw: dict[str, Any], *, message: dict[str, Any], role: str) -> str:
    message_speaker = message.get("speaker")
    if isinstance(message_speaker, dict):
        value = _first_string(message_speaker, "id", "name", "display_name")
        if value:
            return value
    if isinstance(message_speaker, str) and message_speaker:
        return message_speaker

    author = raw.get("author")
    if isinstance(author, dict):
        value = _first_string(author, "id", "name", "display_name")
        if value:
            return value
    return _first_string(raw, "speaker", "sender", "author_id", "user_id") or role


def _timestamp(raw: dict[str, Any], *, message: dict[str, Any]) -> str:
    return (
        _first_string(
            message,
            "timestamp",
            "created_at",
            "createdAt",
            "updated_at",
            "updatedAt",
        )
        or _first_string(
            raw,
            "timestamp",
            "created_at",
            "createdAt",
            "updated_at",
            "updatedAt",
        )
        or ""
    )


def _permission_refs(raw: dict[str, Any], conversation_id: str) -> list[str]:
    explicit = (
        _string_list(raw.get("permission_refs"))
        or _string_list(raw.get("permissions"))
        or _string_list(raw.get("acl"))
    )
    if explicit:
        return _dedupe_strings(explicit)
    return [f"openviking:conversation:{conversation_id}"]


def _metadata(
    raw: dict[str, Any],
    *,
    message: dict[str, Any],
    conversation_id: str,
    session_id: str,
    thread_id: str,
    message_id: str,
    role: str,
    speaker: str,
    source_path_ref: str,
    line_number: int,
) -> dict[str, object]:
    metadata = {
        "conversation_id": conversation_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "message_id": message_id,
        "message_order": _message_order(raw, message=message, line_number=line_number),
        "role": role,
        "speaker": speaker,
        "source_path": source_path_ref,
        "source_object_type": "conversation_message",
    }
    conversation = _object(raw.get("conversation"))
    conversation_title = _first_string(conversation, "title", "name")
    if conversation_title:
        metadata["conversation_title"] = conversation_title
    metadata.update(_object(raw.get("metadata")))
    metadata.update(_object(raw.get("extra")))
    return _compact_metadata(metadata)


def _message_order(raw: dict[str, Any], *, message: dict[str, Any], line_number: int) -> int:
    value = message.get("index", raw.get("message_index", raw.get("order")))
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return line_number


def _speaker_identities(speaker: str) -> list[SourceIdentity]:
    if not speaker:
        return []
    return [
        SourceIdentity(
            source_system="openviking",
            identity_ref=f"openviking:speaker:{speaker}",
            identity_type="speaker",
            value=speaker,
            display_name=speaker,
        )
    ]


def _source_path_ref(raw: dict[str, Any], source_path: Path) -> str:
    return _first_string(raw, "source_path", "path", "file_path") or source_path.as_posix()


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _compact_metadata(values: dict[str, object]) -> dict[str, object]:
    return {key: value for key, value in values.items() if value not in {"", None}}


def _ref_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip())
    return normalized.strip("-") or "unknown"
