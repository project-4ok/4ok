import json
from pathlib import Path

import pytest

from fourok.etl.extract.openviking_adapter import (
    load_openviking_messages_jsonl_source_records,
    openviking_message_source_record_from_raw,
)

FIXTURE = (
    Path(__file__).parent.parent.parent.parent
    / "fixtures"
    / "openviking"
    / "messages_variants.jsonl"
)


def test_openviking_messages_jsonl_variants_become_stable_source_records() -> None:
    records = load_openviking_messages_jsonl_source_records(FIXTURE)

    assert [record.source_ref for record in records] == [
        "openviking:conversation:conv-product:session:sess-alpha:message:m-001",
        "openviking:conversation:conv-product:session:sess-alpha:message:m-002",
        "openviking:conversation:conv-support:session:sess-beta:message:m-003",
    ]
    assert [record.source_id for record in records] == [
        "conv-product:sess-alpha:m-001",
        "conv-product:sess-alpha:m-002",
        "conv-support:sess-beta:m-003",
    ]
    assert records[0].title == "OpenViking user message in conv-product"
    assert records[0].body == "Can OpenViking remember the launch checklist for Alpine Robotics?"
    assert records[0].occurred_at == "2026-06-02T09:00:00+00:00"
    assert records[0].updated_at == "2026-06-02T09:00:00+00:00"
    assert records[0].thread_ref == "openviking:conversation:conv-product:thread:sess-alpha"
    assert records[0].author_ref == "openviking:speaker:Maya"
    assert records[0].permission_refs == (
        "operator",
        "openviking:conversation:conv-product",
    )
    assert records[0].metadata == {
        "conversation_id": "conv-product",
        "message_id": "m-001",
        "message_order": 1,
        "role": "user",
        "session_id": "sess-alpha",
        "source_object_type": "conversation_message",
        "source_path": ".local/openviking/messages.jsonl",
        "speaker": "Maya",
        "thread_id": "sess-alpha",
        "workspace": "local-fourok",
    }
    assert records[0].raw["metadata"] == {"workspace": "local-fourok"}
    assert records[0].raw_ref == (
        ".local/openviking/messages.jsonl#openviking:conversation:conv-product:"
        "session:sess-alpha:message:m-001"
    )

    assert records[1].thread_ref == "openviking:conversation:conv-product:thread:thread-launch"
    assert records[1].metadata["message_order"] == 2
    assert records[1].metadata["conversation_title"] == "Product launch"
    assert records[1].author_ref == "openviking:speaker:assistant"
    assert records[1].identity_refs == ("openviking:speaker:assistant",)

    assert records[2].title == "OpenViking human message in conv-support"
    assert records[2].body == (
        "Support handoff note for Beacon Labs: include the escalated billing context."
    )
    assert records[2].metadata["message_order"] == 1
    assert records[2].metadata["client"] == "Beacon Labs"


def test_openviking_message_without_id_uses_line_order_for_stable_ref() -> None:
    record = openviking_message_source_record_from_raw(
        {
            "conversation_id": "conv-one",
            "session_id": "sess-one",
            "role": "assistant",
            "content": "Line-order fallback content.",
            "timestamp": "2026-06-02T09:00:00+00:00",
        },
        source_path=Path(".local/openviking/messages.jsonl"),
        line_number=7,
    )

    assert record.source_ref == (
        "openviking:conversation:conv-one:session:sess-one:message:line-000007"
    )
    assert record.source_id == "conv-one:sess-one:line-000007"
    assert record.metadata["message_order"] == 7


def test_openviking_message_requires_content() -> None:
    with pytest.raises(ValueError, match="requires content"):
        openviking_message_source_record_from_raw(
            {
                "conversation_id": "conv-one",
                "session_id": "sess-one",
                "message_id": "m-empty",
                "role": "assistant",
            },
            source_path=Path("messages.jsonl"),
            line_number=1,
        )


def test_openviking_loader_rejects_non_object_jsonl_line(tmp_path: Path) -> None:
    messages = tmp_path / "messages.jsonl"
    messages.write_text(json.dumps(["not", "an", "object"]) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="line 1 is not an object"):
        load_openviking_messages_jsonl_source_records(messages)
