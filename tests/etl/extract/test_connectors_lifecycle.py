from pathlib import Path

import pytest

from fourok.etl.extract.connectors import (
    load_singer_email_messages,
    load_singer_source_records,
)
from fourok.etl.extract.source_records import SourceAttachment, SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext

FIXTURES = Path(__file__).parents[3] / "fixtures" / "connectors"
SINGER_EMAILS = FIXTURES / "singer_email_messages.jsonl"


def _source_record_legacy_fields(row: dict[str, object]) -> dict[str, object]:
    keys = [
        "source_ref",
        "source_system",
        "source_id",
        "record_type",
        "source_url",
        "thread_ref",
        "permission_refs",
        "permission_snapshot_status",
        "attachment_refs",
        "identity_refs",
        "lifecycle_state",
    ]
    return {key: row[key] for key in keys}


def test_source_record_permission_refs_support_transitive_group_inheritance() -> None:
    context = GovernedContext(
        group_inheritance={
            "group:finance-emea": ("group:finance",),
            "group:refunds-berlin": ("group:finance-emea",),
        }
    )
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="singer:email_messages:finance-parent",
                source_system="gmail",
                source_id="finance-parent",
                record_type="email",
                title="Nested permission",
                body="nestedpermissionmarker finance refund",
                permission_refs=("group:finance",),
            )
        ]
    )

    response = context.search_context(
        "nestedpermissionmarker",
        principal=PrincipalContext(
            human_id="human:refunds-berlin-1",
            agent_id="agent:context-helper",
            roles=("refunds-berlin",),
        ),
    )
    denied = GovernedContext()
    denied.ingest_source_records(
        [
            SourceRecord(
                source_ref="singer:email_messages:finance-parent",
                source_system="gmail",
                source_id="finance-parent",
                record_type="email",
                title="Nested permission",
                body="nestedpermissionmarker finance refund",
                permission_refs=("group:finance",),
            )
        ]
    )

    assert [result.source_ref for result in response.results] == [
        "singer:email_messages:finance-parent"
    ]
    assert (
        denied.search_context(
            "nestedpermissionmarker",
            principal=PrincipalContext(
                human_id="human:refunds-berlin-1",
                agent_id="agent:context-helper",
                roles=("refunds-berlin",),
            ),
        ).results
        == []
    )


def test_source_record_text_attachments_are_raw_searchable_and_permission_filtered() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="singer:email_messages:attachment-finance",
                source_system="gmail",
                source_id="attachment-finance",
                record_type="email",
                title="Refund attachment",
                body="The email body does not contain the attachment marker.",
                permission_refs=("group:finance",),
                attachment_refs=("attachment:refund-note",),
                attachments=(
                    SourceAttachment(
                        attachment_ref="attachment:refund-note",
                        title="refund-note.txt",
                        text="attachmentuniquemarker refund IBAN DE89370400440532013000",
                    ),
                ),
            )
        ]
    )

    finance_response = context.search_context(
        "attachmentuniquemarker",
        principal=PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
    )
    support_response = context.search_context(
        "attachmentuniquemarker",
        principal=PrincipalContext(
            human_id="human:support-1",
            agent_id="agent:context-helper",
            roles=("support",),
        ),
    )

    assert [result.source_ref for result in finance_response.results] == [
        "singer:email_messages:attachment-finance"
    ]
    assert support_response.results == []
    assert "BANK_ACCOUNT_" not in str(finance_response)
    assert not hasattr(finance_response, "sensitive_tokens")


def test_singer_attachment_objects_populate_attachment_refs_and_content(tmp_path: Path) -> None:
    singer_file = tmp_path / "attachments.jsonl"
    singer_file.write_text(
        (
            '{"type":"RECORD","stream":"email_messages","record":'
            '{"id":"msg-attachment","subject":"Attachment","body":"Email body",'
            '"attachments":[{"id":"att-1","filename":"note.txt",'
            '"text":"attachment object text searchable"}]}}\n'
        ),
        encoding="utf-8",
    )

    record = load_singer_source_records(singer_file)[0]
    message = record.to_email_message()

    assert record.attachment_refs == ("att-1",)
    assert len(record.attachments) == 1
    assert "attachment object text searchable" in message.body


def test_singer_email_record_requires_body(tmp_path: Path) -> None:
    singer_file = tmp_path / "missing-body.jsonl"
    singer_file.write_text(
        '{"type":"RECORD","stream":"email_messages","record":{"id":"msg-003"}}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires body"):
        load_singer_email_messages(singer_file)
