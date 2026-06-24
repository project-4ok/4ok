from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gcb.etl.extract.email_parser import EmailMessage

RESTRICTING_PERMISSION_SNAPSHOT_STATUSES = frozenset({"missing", "stale", "revoked"})


@dataclass(frozen=True)
class SourceIdentity:
    source_system: str
    identity_ref: str
    identity_type: str
    value: str
    display_name: str = ""


@dataclass(frozen=True)
class SourceAttachment:
    attachment_ref: str
    title: str
    text: str
    content_type: str = "text/plain"


@dataclass(frozen=True)
class SourceRecord:
    source_ref: str
    source_system: str
    source_id: str
    record_type: str
    title: str
    body: str
    occurred_at: str = ""
    updated_at: str = ""
    author_ref: str = ""
    source_url: str = ""
    thread_ref: str = ""
    permission_refs: tuple[str, ...] = ()
    permission_snapshot_status: str = "current"
    attachment_refs: tuple[str, ...] = ()
    identity_refs: tuple[str, ...] = ()
    lifecycle_state: str = "active"
    checksum: str = ""
    version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)
    raw_ref: str = ""
    source_identities: tuple[SourceIdentity, ...] = ()
    attachments: tuple[SourceAttachment, ...] = ()

    @property
    def effective_lifecycle_state(self) -> str:
        if self.lifecycle_state != "active":
            return self.lifecycle_state
        if self.permission_snapshot_status in RESTRICTING_PERMISSION_SNAPSHOT_STATUSES:
            return "restricted"
        return self.lifecycle_state

    @property
    def lifecycle_reason(self) -> str:
        if self.permission_snapshot_status in RESTRICTING_PERMISSION_SNAPSHOT_STATUSES:
            return f"permission_snapshot_{self.permission_snapshot_status}"
        return "source_record_lifecycle"

    def to_email_message(self) -> EmailMessage:
        if self.record_type != "email":
            raise ValueError(f"Source record {self.source_ref} is not an email")
        if not self.body:
            raise ValueError(f"Source record {self.source_ref} requires body")

        return EmailMessage(
            source_ref=self.source_ref,
            subject=self.title,
            from_address=_first_raw_string(self.raw, "from_address", "from", "sender"),
            to_addresses=_raw_string_list(self.raw.get("to_addresses", self.raw.get("to", []))),
            date=self.occurred_at,
            body=_body_with_attachments(self.body, self.attachments),
        )


def email_message_to_source_record(message: EmailMessage) -> SourceRecord:
    identities = _email_source_identities(message)
    return SourceRecord(
        source_ref=message.source_ref,
        source_system="local_email",
        source_id=_source_id_from_ref(message.source_ref),
        record_type="email",
        title=message.subject,
        body=message.body,
        occurred_at=message.date,
        author_ref=_email_identity_ref(message.from_address),
        identity_refs=tuple(identity.identity_ref for identity in identities),
        raw={
            "from_address": message.from_address,
            "to_addresses": message.to_addresses,
        },
        source_identities=tuple(identities),
    )


def _email_source_identities(message: EmailMessage) -> list[SourceIdentity]:
    identities = []
    if message.from_address:
        identities.append(
            SourceIdentity(
                source_system="local_email",
                identity_ref=_email_identity_ref(message.from_address),
                identity_type="sender",
                value=message.from_address,
            )
        )
    for email_address in message.to_addresses:
        identities.append(
            SourceIdentity(
                source_system="local_email",
                identity_ref=_email_identity_ref(email_address),
                identity_type="recipient",
                value=email_address,
            )
        )
    return identities


def _email_identity_ref(email_address: str) -> str:
    return f"local_email:email:{email_address.lower()}" if email_address else ""


def _source_id_from_ref(source_ref: str) -> str:
    return source_ref.removeprefix("local_email:")


def _body_with_attachments(body: str, attachments: tuple[SourceAttachment, ...]) -> str:
    attachment_texts = [
        "\n".join(part for part in [attachment.title, attachment.text] if part)
        for attachment in attachments
        if attachment.text
    ]
    if not attachment_texts:
        return body
    return "\n\n".join([body, *attachment_texts])


def _first_raw_string(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _raw_string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []
