from __future__ import annotations

import base64
from datetime import UTC, datetime
from email.utils import getaddresses
from typing import Any

from fourok.etl.extract.source_records import SourceAttachment, SourceIdentity, SourceRecord

_PERMISSION_SNAPSHOT_STATUSES = frozenset({"current", "missing", "stale", "revoked"})
_LIFECYCLE_STATES = frozenset({"active", "restricted", "deleted"})


def gmail_message_to_source_record(message_or_record: dict[str, Any]) -> SourceRecord:
    record = _gmail_record(message_or_record)
    source_id = _required_string(record, "id")
    thread_id = _string(record.get("threadId")) or _string(record.get("thread_id"))
    snippet = _string(record.get("snippet"))
    payload = _dict(record.get("payload"))
    headers = _headers_by_name(payload)

    identities = _identities(headers)
    attachments = tuple(_attachments(source_id, payload))
    occurred_at = _occurred_at(_string(record.get("internalDate")))
    title = headers.get("subject") or snippet
    body = _plain_text_body(payload) or snippet
    user_id = _string(record.get("userId")) or _string(record.get("user_id"))
    lifecycle_state, lifecycle_mapping_missing = _lifecycle_state(record)
    permission_refs = _string_list(record.get("permission_refs"))
    permission_snapshot_status = _permission_snapshot_status(
        _string(record.get("permission_snapshot_status"))
        or _string(record.get("permissionSnapshotStatus"))
        or _string(record.get("permission_status"))
    )

    sender = ""
    if identities and identities[0].identity_type == "sender":
        sender = identities[0].value
    recipients = [
        identity.value for identity in identities if identity.identity_type == "recipient"
    ]

    raw = {
        "gmail_record": record,
        "from_address": sender,
        "to_addresses": recipients,
        "lifecycle_mapping_missing": lifecycle_mapping_missing,
        "permission_incomplete": permission_snapshot_status != "current",
        "permission_snapshot_status": permission_snapshot_status,
    }

    return SourceRecord(
        source_ref=f"gmail:message:{source_id}",
        source_system="gmail",
        source_id=source_id,
        record_type="email",
        title=title,
        body=body,
        occurred_at=occurred_at,
        source_url=_source_url(user_id, thread_id, source_id),
        thread_ref=f"gmail:thread:{thread_id}" if thread_id else "",
        permission_refs=tuple(permission_refs),
        permission_snapshot_status=permission_snapshot_status,
        attachment_refs=tuple(attachment.attachment_ref for attachment in attachments),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        lifecycle_state=lifecycle_state,
        raw=raw,
        source_identities=tuple(identities),
        attachments=attachments,
    )


def _gmail_record(message_or_record: dict[str, Any]) -> dict[str, Any]:
    if _string(message_or_record.get("type")) != "RECORD":
        return message_or_record
    if _string(message_or_record.get("stream")) != "messages":
        raise ValueError("Gmail Singer adapter only supports the messages stream")
    record = message_or_record.get("record")
    if not isinstance(record, dict):
        raise ValueError("Gmail Singer RECORD message requires object field: record")
    return record


def _required_string(record: dict[str, Any], key: str) -> str:
    value = _string(record.get(key))
    if not value:
        raise ValueError(f"Gmail record requires string field: {key}")
    return value


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _normalized_string(value: Any) -> str:
    return _string(value).strip().casefold()


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _headers_by_name(payload: dict[str, Any]) -> dict[str, str]:
    headers = payload.get("headers")
    if not isinstance(headers, list):
        return {}
    indexed: dict[str, str] = {}
    for header in headers:
        if not isinstance(header, dict):
            continue
        name = _string(header.get("name")).strip().casefold()
        value = _string(header.get("value")).strip()
        if name and value and name not in indexed:
            indexed[name] = value
    return indexed


def _plain_text_body(payload: dict[str, Any]) -> str:
    for part in _walk_parts(payload):
        if _string(part.get("mimeType")).casefold() != "text/plain":
            continue
        body = _dict(part.get("body"))
        decoded = _decode_base64url(_string(body.get("data")))
        if decoded:
            return decoded
    body = _dict(payload.get("body"))
    return _decode_base64url(_string(body.get("data")))


def _walk_parts(payload: dict[str, Any]) -> list[dict[str, Any]]:
    parts = payload.get("parts")
    if not isinstance(parts, list):
        return []
    walked: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        walked.append(part)
        walked.extend(_walk_parts(part))
    return walked


def _decode_base64url(value: str) -> str:
    if not value:
        return ""
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(f"{value}{padding}").decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""


def _occurred_at(internal_date: str) -> str:
    if not internal_date:
        return ""
    try:
        millis = int(internal_date)
    except ValueError:
        return ""
    return datetime.fromtimestamp(millis / 1000, tz=UTC).isoformat()


def _identities(headers: dict[str, str]) -> list[SourceIdentity]:
    identities: list[SourceIdentity] = []
    sender = _mailbox(headers.get("from", ""))
    if sender is not None:
        identities.append(sender)
    for header_name in ("to", "cc", "bcc"):
        for recipient in _mailboxes(headers.get(header_name, ""), identity_type="recipient"):
            identities.append(recipient)
    return _dedupe_identities(identities)


def _mailbox(value: str) -> SourceIdentity | None:
    mailboxes = _mailboxes(value, identity_type="sender")
    return mailboxes[0] if mailboxes else None


def _mailboxes(value: str, *, identity_type: str) -> list[SourceIdentity]:
    identities = []
    for display_name, email_address in getaddresses([value]):
        normalized = email_address.strip().casefold()
        if not normalized:
            continue
        identities.append(
            SourceIdentity(
                source_system="gmail",
                identity_ref=f"gmail:email:{normalized}",
                identity_type=identity_type,
                value=normalized,
                display_name=display_name.strip(),
            )
        )
    return identities


def _dedupe_identities(identities: list[SourceIdentity]) -> list[SourceIdentity]:
    seen = set()
    deduped = []
    for identity in identities:
        if identity.identity_ref in seen:
            continue
        seen.add(identity.identity_ref)
        deduped.append(identity)
    return deduped


def _attachments(source_id: str, payload: dict[str, Any]) -> list[SourceAttachment]:
    attachments = []
    for part in _walk_parts(payload):
        filename = _string(part.get("filename")).strip()
        body = _dict(part.get("body"))
        attachment_id = _string(body.get("attachmentId")).strip()
        if not filename or not attachment_id:
            continue
        attachments.append(
            SourceAttachment(
                attachment_ref=f"gmail:message:{source_id}:attachment:{attachment_id}",
                title=filename,
                text="",
                content_type=_string(part.get("mimeType")) or "text/plain",
            )
        )
    return attachments


def _lifecycle_state(record: dict[str, Any]) -> tuple[str, bool]:
    explicit = _normalized_string(record.get("lifecycle_state")) or _normalized_string(
        record.get("state")
    )
    if explicit in _LIFECYCLE_STATES:
        return explicit, False
    if _truthy(record.get("deleted")):
        return "deleted", False
    if _truthy(record.get("restricted")):
        return "restricted", False
    labels = {
        label.strip().casefold()
        for label in _string_list(record.get("labelIds") or record.get("label_ids"))
    }
    if "trash" in labels:
        return "deleted", False
    return "active", True


def _permission_snapshot_status(value: Any) -> str:
    normalized = _normalized_string(value)
    if normalized in _PERMISSION_SNAPSHOT_STATUSES:
        return normalized
    return "missing"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes"}
    return False


def _source_url(user_id: str, thread_id: str, source_id: str) -> str:
    if not thread_id or not source_id:
        return ""
    mailbox = user_id or "0"
    return f"https://mail.google.com/mail/u/{mailbox}/#all/{thread_id}/{source_id}"
