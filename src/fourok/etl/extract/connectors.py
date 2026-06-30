from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from fourok.etl.extract.email_parser import EmailMessage
from fourok.etl.extract.gmail_singer import gmail_message_to_source_record
from fourok.etl.extract.google_drive_adapter import google_drive_file_source_record_from_raw
from fourok.etl.extract.linear_adapter import (
    linear_comment_source_record_from_raw,
    linear_issue_source_record_from_raw,
    linear_user_source_record_from_raw,
)
from fourok.etl.extract.slack_adapter import (
    slack_message_source_record_from_raw,
    slack_source_record_from_raw,
)
from fourok.etl.extract.source_records import SourceAttachment, SourceIdentity, SourceRecord
from fourok.observability import critical_span, set_safe_span_attributes


class ConnectorPayloadError(ValueError):
    """Permanent connector payload error that should not be retried."""


@dataclass(frozen=True)
class LandingReport:
    record_count: int
    streams: dict[str, int]
    state_messages: int
    schema_messages: int
    state_path: Path | None = None
    latest_state: dict[str, Any] | None = None


def land_singer_records(singer_path: Path, landing_dir: Path) -> LandingReport:
    return land_singer_lines(
        singer_path.read_text(encoding="utf-8").splitlines(),
        landing_dir,
    )


def land_singer_stream(input_stream: TextIO, landing_dir: Path) -> LandingReport:
    return land_singer_lines(input_stream, landing_dir)


def land_singer_lines(lines: Iterable[str], landing_dir: Path) -> LandingReport:
    with critical_span(
        "fourok.raw_landing.write",
        status_attribute="fourok.raw_landing.status",
    ) as span:
        report = _land_singer_lines(lines, landing_dir)
        set_safe_span_attributes(
            span,
            {
                "fourok.raw_landing.status": "succeeded",
                "fourok.raw_landing.record_count": report.record_count,
                "fourok.raw_landing.stream_count": len(report.streams),
                "fourok.raw_landing.schema_message_count": report.schema_messages,
                "fourok.raw_landing.state_message_count": report.state_messages,
            },
        )
        return report


def _land_singer_lines(lines: Iterable[str], landing_dir: Path) -> LandingReport:
    landing_dir.mkdir(parents=True, exist_ok=True)
    streams: dict[str, int] = {}
    state_messages = 0
    schema_messages = 0
    latest_state: dict[str, Any] | None = None

    for message in _read_singer_messages(lines):
        message_type = message.get("type")
        if message_type == "SCHEMA":
            schema_messages += 1
            continue
        if message_type == "STATE":
            state_messages += 1
            latest_state = _required_dict(message, "value")
            continue
        if message_type != "RECORD":
            raise ValueError(f"Unsupported Singer message type: {message_type}")

        stream = _required_string(message, "stream")
        record = _required_dict(message, "record")
        streams[stream] = streams.get(stream, 0) + 1
        with (landing_dir / f"{stream}.jsonl").open("a", encoding="utf-8") as output:
            output.write(json.dumps(record, sort_keys=True))
            output.write("\n")

    state_path = None
    if latest_state is not None:
        state_path = landing_dir / "state.json"
        state_path.write_text(json.dumps(latest_state, sort_keys=True) + "\n", encoding="utf-8")

    return LandingReport(
        record_count=sum(streams.values()),
        streams=dict(sorted(streams.items())),
        state_messages=state_messages,
        schema_messages=schema_messages,
        state_path=state_path,
        latest_state=latest_state,
    )


def load_singer_email_messages(
    singer_path: Path, *, stream: str = "email_messages"
) -> list[EmailMessage]:
    return [
        record.to_email_message()
        for record in load_singer_source_records(singer_path, stream=stream)
    ]


def load_landed_email_messages(
    landing_path: Path, *, stream: str = "email_messages"
) -> list[EmailMessage]:
    return [
        record.to_email_message()
        for record in load_landed_source_records(landing_path, stream=stream)
    ]


def load_singer_source_records(
    singer_path: Path, *, stream: str = "email_messages"
) -> list[SourceRecord]:
    records = []
    for message in _read_singer_messages(singer_path.read_text(encoding="utf-8").splitlines()):
        if message.get("type") != "RECORD" or message.get("stream") != stream:
            continue
        try:
            records.append(_source_record_from_record(stream, _required_dict(message, "record")))
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return records


def load_gmail_source_records(singer_path: Path, *, stream: str = "messages") -> list[SourceRecord]:
    records = []
    for message in _read_singer_messages(singer_path.read_text(encoding="utf-8").splitlines()):
        if message.get("type") != "RECORD" or message.get("stream") != stream:
            continue
        record = _required_dict(message, "record")
        try:
            if _looks_like_gmail_message_record(record):
                records.append(gmail_message_to_source_record(record))
                continue
            records.append(gmail_source_record_from_raw(record))
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return records


def load_slack_source_records(
    singer_path: Path, *, stream: str = "slack_messages"
) -> list[SourceRecord]:
    records = []
    for message in _read_singer_messages(singer_path.read_text(encoding="utf-8").splitlines()):
        if message.get("type") != "RECORD" or message.get("stream") != stream:
            continue
        try:
            records.append(slack_source_record_from_raw(stream, _required_dict(message, "record")))
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return records


def load_twenty_source_records(singer_path: Path) -> list[SourceRecord]:
    records = []
    for message in _read_singer_messages(singer_path.read_text(encoding="utf-8").splitlines()):
        if message.get("type") != "RECORD":
            continue
        stream = message.get("stream")
        record = _required_dict(message, "record")
        try:
            if stream == "twenty_companies":
                records.append(twenty_company_source_record_from_raw(record))
            elif stream == "twenty_people":
                records.append(twenty_person_source_record_from_raw(record))
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return records


def load_linear_source_records(singer_path: Path) -> list[SourceRecord]:
    records = []
    for message in _read_singer_messages(singer_path.read_text(encoding="utf-8").splitlines()):
        if message.get("type") != "RECORD":
            continue
        stream = message.get("stream")
        record = _required_dict(message, "record")
        try:
            if stream == "linear_users":
                records.append(linear_user_source_record_from_raw(record))
            elif stream == "linear_issues":
                records.append(linear_issue_source_record_from_raw(record))
            elif stream == "linear_comments":
                records.append(linear_comment_source_record_from_raw(record))
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return records


def load_google_drive_source_records(
    singer_path: Path, *, stream: str = "google_drive_files"
) -> list[SourceRecord]:
    records = []
    for message in _read_singer_messages(singer_path.read_text(encoding="utf-8").splitlines()):
        if message.get("type") != "RECORD" or message.get("stream") != stream:
            continue
        try:
            records.append(
                google_drive_file_source_record_from_raw(_required_dict(message, "record"))
            )
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return records


def load_landed_source_records(
    landing_path: Path, *, stream: str = "email_messages"
) -> list[SourceRecord]:
    record_path = landing_path / f"{stream}.jsonl"
    if not record_path.exists():
        return []
    records = []
    for line_number, line in enumerate(
        record_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid landed JSON on line {line_number}: {error.msg}") from error
        if not isinstance(record, dict):
            raise ValueError(f"Landed record line {line_number} is not an object")
        records.append(_source_record_from_landed_record(stream, record))
    return records


def _read_singer_messages(lines: Iterable[str]) -> list[dict[str, Any]]:
    messages = []
    for line_number, line in enumerate(lines, start=1):
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


def _source_record_from_record(stream: str, record: dict[str, Any]) -> SourceRecord:
    source_id = _first_string(record, "source_ref", "id", "message_id")
    if source_id is None:
        raise ValueError("Singer email record requires source_ref, id, or message_id")

    source_ref = source_id if source_id.startswith("singer:") else f"singer:{stream}:{source_id}"
    subject = _first_string(record, "subject", "title") or ""
    body = _first_string(record, "body", "text", "plain_text") or ""
    if not body:
        raise ValueError(f"Singer email record {source_ref} requires body, text, or plain_text")
    attachments = tuple(_source_attachments(record))
    identities = tuple(_source_identities(record))

    return SourceRecord(
        source_ref=source_ref,
        source_system=_first_string(record, "source_system", "system") or "singer",
        source_id=source_id,
        record_type=_first_string(record, "record_type", "kind", "type") or "email",
        title=subject,
        body=body,
        occurred_at=_first_string(record, "date", "timestamp", "updated_at", "created_at") or "",
        source_url=_first_string(record, "source_url", "web_url", "url") or "",
        thread_ref=_first_string(record, "thread_ref", "thread_id", "conversation_id") or "",
        permission_refs=tuple(_string_list(record.get("permission_refs", []))),
        permission_snapshot_status=_first_string(
            record,
            "permission_snapshot_status",
            "permission_status",
            "acl_snapshot_status",
        )
        or "current",
        attachment_refs=tuple(_attachment_refs(record, attachments)),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state=_first_string(record, "lifecycle_state", "state") or "active",
        raw=record,
        source_identities=identities,
        attachments=attachments,
    )


def _source_record_from_landed_record(stream: str, record: dict[str, Any]) -> SourceRecord:
    if stream == "slack_messages":
        try:
            return slack_message_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    if stream == "twenty_companies":
        try:
            return twenty_company_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    if stream == "twenty_people":
        try:
            return twenty_person_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    if stream == "linear_users":
        try:
            return linear_user_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    if stream == "linear_issues":
        try:
            return linear_issue_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    if stream == "linear_comments":
        try:
            return linear_comment_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    if stream == "google_drive_files":
        try:
            return google_drive_file_source_record_from_raw(record)
        except ValueError as exc:
            raise ConnectorPayloadError(str(exc)) from exc
    return _source_record_from_record(stream, record)


def gmail_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _first_string(record, "id", "message_id", "messageId")
    if source_id is None:
        raise ValueError("Gmail record requires id, message_id, or messageId")

    body = _first_string(record, "body", "text", "plain_text", "snippet")
    if not body:
        raise ValueError(f"Gmail record gmail:messages:{source_id} requires body, text, or snippet")

    normalized = {
        **record,
        "source_system": "gmail",
        "source_ref": f"gmail:messages:{source_id}",
        "source_url": _gmail_source_url(record, source_id),
        "thread_ref": _first_string(record, "thread_id", "threadId", "thread_ref") or "",
        "date": _first_string(
            record, "date", "timestamp", "internalDate", "created_at", "updated_at"
        )
        or "",
        "body": body,
        "from_address": _first_string(record, "from_address", "from", "sender") or "",
        "to_addresses": _string_list(record.get("to_addresses", record.get("to", []))),
        "permission_snapshot_status": _first_string(
            record,
            "permission_snapshot_status",
            "permission_status",
            "acl_snapshot_status",
        )
        or "missing",
        "attachment_refs": _gmail_attachment_refs(record),
    }

    identities = tuple(_source_identities(normalized))

    return SourceRecord(
        source_ref=normalized["source_ref"],
        source_system="gmail",
        source_id=source_id,
        record_type="email",
        title=_first_string(record, "subject", "title") or "",
        body=body,
        occurred_at=normalized["date"],
        source_url=normalized["source_url"],
        thread_ref=normalized["thread_ref"],
        permission_refs=tuple(_string_list(record.get("permission_refs", []))),
        permission_snapshot_status=normalized["permission_snapshot_status"],
        attachment_refs=tuple(_dedupe_strings(normalized["attachment_refs"])),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state=_gmail_lifecycle_state(record),
        raw=normalized,
        source_identities=identities,
        attachments=tuple(_source_attachments(normalized)),
    )


def twenty_company_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _first_string(record, "id", "source_id")
    if source_id is None:
        raise ValueError("Twenty company record requires id")

    name = _first_string(record, "name", "display_name") or source_id
    domain = _first_string(record, "domainName", "domain_name", "domain") or ""

    return SourceRecord(
        source_ref=f"twenty:company:{source_id}",
        source_system="twenty",
        source_id=source_id,
        record_type="organization",
        title=name,
        body=_join_text(name, domain),
        occurred_at=_first_string(record, "created_at", "createdAt") or "",
        updated_at=_first_string(record, "updated_at", "updatedAt") or "",
        source_url=_first_string(record, "url", "source_url") or "",
        metadata=_compact_metadata(
            {
                "domain": domain,
                "source_object_type": "company",
            }
        ),
        raw=record,
    )


def twenty_person_source_record_from_raw(record: dict[str, Any]) -> SourceRecord:
    source_id = _first_string(record, "id", "source_id")
    if source_id is None:
        raise ValueError("Twenty person record requires id")

    display_name = _twenty_person_display_name(record) or source_id
    emails = _twenty_emails(record)
    company_id = _first_string(record, "company_id", "companyId")
    company_name = _first_string(record, "company_name", "companyName")
    job_title = _first_string(record, "jobTitle", "job_title")
    identities = _email_identities("twenty", emails)

    return SourceRecord(
        source_ref=f"twenty:person:{source_id}",
        source_system="twenty",
        source_id=source_id,
        record_type="person",
        title=display_name,
        body=_join_text(display_name, job_title, company_name, *emails),
        occurred_at=_first_string(record, "created_at", "createdAt") or "",
        updated_at=_first_string(record, "updated_at", "updatedAt") or "",
        source_url=_first_string(record, "url", "source_url") or "",
        identity_refs=tuple(identity.identity_ref for identity in identities),
        metadata=_compact_metadata(
            {
                "company_id": company_id or "",
                "company_name": company_name or "",
                "job_title": job_title or "",
                "source_object_type": "person",
            }
        ),
        raw=record,
        source_identities=tuple(identities),
    )


def _looks_like_gmail_message_record(record: dict[str, Any]) -> bool:
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return False
    headers = payload.get("headers")
    parts = payload.get("parts")
    body = payload.get("body")
    return isinstance(headers, list) or isinstance(parts, list) or isinstance(body, dict)


def _required_string(message: dict[str, Any], key: str) -> str:
    value = message.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Singer message requires string field: {key}")
    return value


def _required_dict(message: dict[str, Any], key: str) -> dict[str, Any]:
    value = message.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"Singer message requires object field: {key}")
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


def _source_identities(record: dict[str, Any]) -> list[SourceIdentity]:
    source_system = _first_string(record, "source_system", "system") or "singer"
    identities = []
    sender = _first_string(record, "from_address", "from", "sender")
    if sender:
        identities.append(
            SourceIdentity(
                source_system=source_system,
                identity_ref=_identity_ref(source_system, "email", sender),
                identity_type="sender",
                value=sender,
                display_name=_first_string(record, "from_name", "sender_name") or "",
            )
        )

    for recipient in _string_list(record.get("to_addresses", record.get("to", []))):
        identities.append(
            SourceIdentity(
                source_system=source_system,
                identity_ref=_identity_ref(source_system, "email", recipient),
                identity_type="recipient",
                value=recipient,
            )
        )

    return _dedupe_identities(identities)


def _email_identities(source_system: str, emails: list[str]) -> list[SourceIdentity]:
    return _dedupe_identities(
        [
            SourceIdentity(
                source_system=source_system,
                identity_ref=_identity_ref(source_system, "email", email),
                identity_type="email",
                value=email,
            )
            for email in emails
        ]
    )


def _twenty_person_display_name(record: dict[str, Any]) -> str:
    explicit = _first_string(record, "display_name", "displayName", "full_name", "fullName")
    if explicit:
        return explicit
    name = record.get("name")
    if isinstance(name, dict):
        return _join_text(
            _first_string(name, "firstName", "first_name", "first"),
            _first_string(name, "lastName", "last_name", "last"),
        )
    if isinstance(name, str):
        return name
    return ""


def _twenty_emails(record: dict[str, Any]) -> list[str]:
    emails = _string_list(record.get("emails", []))
    for key in ("email", "primaryEmail", "primary_email"):
        value = _first_string(record, key)
        if value:
            emails.append(value)
    raw_email = record.get("email")
    if isinstance(raw_email, dict):
        value = _first_string(raw_email, "primaryEmail", "primary_email", "value")
        if value:
            emails.append(value)
    return _dedupe_strings(emails)


def _join_text(*parts: str | None) -> str:
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _compact_metadata(values: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in values.items() if value}


def _source_attachments(record: dict[str, Any]) -> list[SourceAttachment]:
    raw_attachments = record.get("attachments", [])
    if not isinstance(raw_attachments, list):
        return []

    attachments = []
    for index, raw_attachment in enumerate(raw_attachments, start=1):
        if not isinstance(raw_attachment, dict):
            continue
        text = _first_string(raw_attachment, "text", "plain_text", "body") or ""
        if not text:
            continue
        attachment_ref = _first_string(raw_attachment, "attachment_ref", "id", "file_id")
        title = _first_string(raw_attachment, "title", "name", "filename") or ""
        attachments.append(
            SourceAttachment(
                attachment_ref=attachment_ref or f"attachment:{index}",
                title=title,
                text=text,
                content_type=_first_string(raw_attachment, "content_type", "mime_type")
                or "text/plain",
            )
        )
    return attachments


def _attachment_refs(
    record: dict[str, Any], attachments: tuple[SourceAttachment, ...]
) -> list[str]:
    refs = _string_list(record.get("attachment_refs", []))
    refs.extend(attachment.attachment_ref for attachment in attachments)
    return _dedupe_strings(refs)


def _gmail_source_url(record: dict[str, Any], source_id: str) -> str:
    explicit = _first_string(record, "source_url", "web_url", "url")
    if explicit:
        return explicit
    return f"https://mail.google.com/mail/u/0/#all/{source_id}"


def _gmail_attachment_refs(record: dict[str, Any]) -> list[str]:
    refs = _string_list(record.get("attachment_refs", []))
    attachments = record.get("attachments", [])
    if isinstance(attachments, list):
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            attachment_id = _first_string(attachment, "attachment_ref", "id", "file_id")
            if attachment_id:
                refs.append(attachment_id)
    payload = record.get("payload")
    if isinstance(payload, dict):
        refs.extend(_gmail_payload_attachment_refs(payload))
    return _dedupe_strings(refs)


def _gmail_payload_attachment_refs(payload: dict[str, Any]) -> list[str]:
    refs = []
    parts = payload.get("parts", [])
    if not isinstance(parts, list):
        return refs
    for part in parts:
        if not isinstance(part, dict):
            continue
        body = part.get("body")
        if isinstance(body, dict):
            attachment_id = _first_string(body, "attachmentId", "attachment_id")
            if attachment_id:
                refs.append(attachment_id)
        nested_payload = {"parts": part.get("parts", [])}
        refs.extend(_gmail_payload_attachment_refs(nested_payload))
    return refs


def _gmail_lifecycle_state(record: dict[str, Any]) -> str:
    explicit = _first_string(record, "lifecycle_state", "state")
    if explicit in {"active", "restricted", "deleted"}:
        return explicit
    label_values = record.get("labelIds", record.get("label_ids", []))
    labels = {label.casefold() for label in _string_list(label_values)}
    if "trash" in labels:
        return "deleted"
    return "active"


def _identity_ref(source_system: str, value_type: str, value: str) -> str:
    return f"{source_system}:{value_type}:{value.strip().casefold()}"


def _dedupe_strings(values: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _dedupe_identities(identities: list[SourceIdentity]) -> list[SourceIdentity]:
    seen = set()
    deduped = []
    for identity in identities:
        key = (identity.identity_ref, identity.identity_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(identity)
    return deduped
