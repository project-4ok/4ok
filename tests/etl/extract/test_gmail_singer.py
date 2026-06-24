from __future__ import annotations

import pytest

from gcb.etl.extract.gmail_singer import gmail_message_to_source_record


def test_gmail_message_to_source_record_accepts_singer_record_message() -> None:
    record = gmail_message_to_source_record(
        {
            "type": "RECORD",
            "stream": "messages",
            "record": {
                "id": "msg-123",
                "threadId": "thread-456",
                "internalDate": "1716998096000",
                "snippet": "snippet fallback",
                "userId": "me",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Pilot subject"},
                        {"name": "From", "value": "Sender Name <Sender@Example.com>"},
                        {"name": "To", "value": "Ops@example.com, Team@example.com"},
                        {"name": "Cc", "value": "Ops@example.com"},
                        {"name": "Bcc", "value": "Audit@example.com"},
                    ],
                    "parts": [
                        {
                            "mimeType": "multipart/alternative",
                            "parts": [
                                {
                                    "mimeType": "text/plain",
                                    "body": {"data": "UGlsb3QgYm9keSB0ZXh0"},
                                }
                            ],
                        },
                        {
                            "filename": "note.txt",
                            "mimeType": "text/plain",
                            "body": {"attachmentId": "att-1"},
                        },
                    ],
                },
            },
        }
    )

    assert record.source_system == "gmail"
    assert record.record_type == "email"
    assert record.source_id == "msg-123"
    assert record.source_ref == "gmail:message:msg-123"
    assert record.thread_ref == "gmail:thread:thread-456"
    assert record.source_url == "https://mail.google.com/mail/u/me/#all/thread-456/msg-123"
    assert record.title == "Pilot subject"
    assert record.body == "Pilot body text"
    assert record.occurred_at == "2024-05-29T15:54:56+00:00"
    assert record.identity_refs == (
        "gmail:email:sender@example.com",
        "gmail:email:ops@example.com",
        "gmail:email:team@example.com",
        "gmail:email:audit@example.com",
    )
    assert record.source_identities[0].identity_type == "sender"
    assert record.source_identities[0].display_name == "Sender Name"
    assert tuple(identity.identity_type for identity in record.source_identities[1:]) == (
        "recipient",
        "recipient",
        "recipient",
    )
    assert record.attachment_refs == ("gmail:message:msg-123:attachment:att-1",)
    assert record.attachments[0].attachment_ref == "gmail:message:msg-123:attachment:att-1"
    assert record.attachments[0].title == "note.txt"
    assert record.attachments[0].content_type == "text/plain"
    assert record.attachments[0].text == ""
    assert record.permission_snapshot_status == "missing"
    assert record.effective_lifecycle_state == "restricted"
    assert record.raw["permission_incomplete"] is True


def test_gmail_message_to_source_record_accepts_nested_record_payload() -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-789",
            "threadId": "thread-789",
            "snippet": "snippet body",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": "PGRpdj5odG1sIG9ubHk8L2Rpdj4="},
                    }
                ],
            },
        }
    )

    assert record.title == "snippet body"
    assert record.body == "snippet body"
    assert record.source_url == "https://mail.google.com/mail/u/0/#all/thread-789/msg-789"
    assert record.thread_ref == "gmail:thread:thread-789"
    assert record.identity_refs == ()
    assert record.attachment_refs == ()


def test_gmail_message_to_source_record_maps_explicit_lifecycle_signals() -> None:
    deleted = gmail_message_to_source_record(
        {
            "id": "msg-deleted",
            "threadId": "thread-deleted",
            "labelIds": ["INBOX", "TRASH"],
            "payload": {"headers": [], "body": {"data": "ZGVsZXRlZA=="}},
        }
    )
    restricted = gmail_message_to_source_record(
        {
            "id": "msg-restricted",
            "threadId": "thread-restricted",
            "restricted": True,
            "payload": {"headers": [], "body": {"data": "cmVzdHJpY3RlZA=="}},
        }
    )

    assert deleted.lifecycle_state == "deleted"
    assert deleted.effective_lifecycle_state == "deleted"
    assert deleted.raw["lifecycle_mapping_missing"] is False
    assert restricted.lifecycle_state == "restricted"
    assert restricted.effective_lifecycle_state == "restricted"
    assert restricted.raw["lifecycle_mapping_missing"] is False


def test_gmail_message_to_source_record_marks_missing_lifecycle_mapping() -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-active",
            "threadId": "thread-active",
            "payload": {"headers": [], "body": {"data": "YWN0aXZl"}},
        }
    )

    assert record.lifecycle_state == "active"
    assert record.raw["lifecycle_mapping_missing"] is True


def test_gmail_message_to_source_record_collects_nested_attachment_metadata_only() -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-attachments",
            "threadId": "thread-attachments",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "mimeType": "multipart/mixed",
                        "parts": [
                            {
                                "filename": "statement.pdf",
                                "mimeType": "application/pdf",
                                "body": {
                                    "attachmentId": "att-pdf",
                                    "data": "cGRmLWJ5dGVzLXNob3VsZC1ub3QtYmUtdXNlZA==",
                                },
                            },
                            {
                                "mimeType": "multipart/related",
                                "parts": [
                                    {
                                        "filename": "diagram.png",
                                        "mimeType": "image/png",
                                        "body": {
                                            "attachmentId": "att-image",
                                            "data": "aW1hZ2UtYnl0ZXMtc2hvdWxkLW5vdC1iZS11c2Vk",
                                        },
                                    }
                                ],
                            },
                        ],
                    }
                ],
            },
        }
    )

    assert record.attachment_refs == (
        "gmail:message:msg-attachments:attachment:att-pdf",
        "gmail:message:msg-attachments:attachment:att-image",
    )
    assert [attachment.attachment_ref for attachment in record.attachments] == list(
        record.attachment_refs
    )
    assert [attachment.title for attachment in record.attachments] == [
        "statement.pdf",
        "diagram.png",
    ]
    assert [attachment.content_type for attachment in record.attachments] == [
        "application/pdf",
        "image/png",
    ]
    assert all(attachment.text == "" for attachment in record.attachments)


def test_gmail_message_to_source_record_marks_missing_permissions_explicitly() -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-permissions-missing",
            "threadId": "thread-permissions-missing",
            "payload": {"headers": [], "body": {"data": "cGVybWlzc2lvbnM="}},
        }
    )

    assert record.permission_snapshot_status == "missing"
    assert record.permission_refs == ()
    assert record.raw["permission_snapshot_status"] == "missing"
    assert record.raw["permission_incomplete"] is True


@pytest.mark.parametrize(
    ("permission_snapshot_status", "expected_status"),
    [
        (" MISSING ", "missing"),
        ("STALE", "stale"),
        (" revoked\t", "revoked"),
        ("", "missing"),
        ("  unexpected  ", "missing"),
    ],
)
def test_gmail_message_to_source_record_normalizes_permission_snapshot_statuses(
    permission_snapshot_status: str,
    expected_status: str,
) -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-permissions-normalized",
            "threadId": "thread-permissions-normalized",
            "permissionSnapshotStatus": permission_snapshot_status,
            "payload": {"headers": [], "body": {"data": "cGVybWlzc2lvbnM="}},
        }
    )

    assert record.permission_snapshot_status == expected_status
    assert record.raw["permission_snapshot_status"] == expected_status
    assert record.effective_lifecycle_state == "restricted"
    assert record.raw["permission_incomplete"] is True


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_state"),
    [
        ("lifecycle_state", " DELETED ", "deleted"),
        ("state", "RESTRICTED", "restricted"),
    ],
)
def test_gmail_message_to_source_record_normalizes_explicit_lifecycle_state(
    field_name: str,
    field_value: str,
    expected_state: str,
) -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-lifecycle-normalized",
            "threadId": "thread-lifecycle-normalized",
            field_name: field_value,
            "permissionSnapshotStatus": "current",
            "payload": {"headers": [], "body": {"data": "bGlmZWN5Y2xl"}},
        }
    )

    assert record.permission_snapshot_status == "current"
    assert record.lifecycle_state == expected_state
    assert record.effective_lifecycle_state == expected_state
    assert record.raw["lifecycle_mapping_missing"] is False
    assert record.raw["permission_incomplete"] is False


def test_gmail_message_to_source_record_rejects_non_message_stream() -> None:
    with pytest.raises(ValueError, match="messages stream"):
        gmail_message_to_source_record(
            {
                "type": "RECORD",
                "stream": "threads",
                "record": {"id": "msg-123", "snippet": "body"},
            }
        )


def test_gmail_message_to_source_record_preserves_explicit_permission_snapshot() -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-999",
            "threadId": "thread-999",
            "snippet": "synthetic body",
            "permissionSnapshotStatus": "current",
            "permission_refs": ["group:finance"],
            "payload": {
                "headers": [],
                "body": {"data": "c3ludGhldGljIGJvZHk="},
            },
        }
    )

    assert record.permission_snapshot_status == "current"
    assert record.permission_refs == ("group:finance",)
    assert record.effective_lifecycle_state == "active"
    assert record.raw["permission_incomplete"] is False


def test_gmail_message_to_source_record_preserves_synthetic_pii_for_governed_ingest() -> None:
    record = gmail_message_to_source_record(
        {
            "id": "msg-pii-pilot",
            "threadId": "thread-pii-pilot",
            "permissionSnapshotStatus": "current",
            "payload": {
                "headers": [
                    {
                        "name": "Subject",
                        "value": "Falcon review for alicia.audit@example.com",
                    },
                    {
                        "name": "From",
                        "value": "Alicia Example <alicia.audit@example.com>",
                    },
                    {"name": "To", "value": "ops@example.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {
                            "data": (
                                "Q2FsbCArMSAoNDE1KSA1NTUtMDE5OSBhYm91dCBGYWxjb24gcmVmdW5kIGFuZCB1"
                                "c2UgSUJBTiBERTQ0NTAwMTA1MTc1NDA3MzI0OTMxLg=="
                            )
                        },
                    }
                ],
            },
        }
    )

    assert record.title == "Falcon review for alicia.audit@example.com"
    assert record.body == (
        "Call +1 (415) 555-0199 about Falcon refund and use IBAN DE44500105175407324931."
    )
    assert record.raw["from_address"] == "alicia.audit@example.com"
    assert record.permission_snapshot_status == "current"
    assert record.effective_lifecycle_state == "active"
