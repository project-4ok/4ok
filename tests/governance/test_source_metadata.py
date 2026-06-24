from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.etl.load.retrieval_records import (
    RetrievalRecord,
    prepare_retrieval_records,
    retrieval_record_rows,
    store_retrieval_records,
)
from fourok.etl.load.source_metadata import (
    denied_source_refs,
    source_identity_rows,
    source_metadata,
    source_record_rows,
    store_source_records,
)
from fourok.governance.policy import PrincipalContext
from fourok.governance.state import create_governed_context_state


def test_store_source_records_replaces_metadata_and_identity_rows() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    first = SourceRecord(
        source_ref="gmail:msg-1",
        source_system="gmail",
        source_id="msg-1",
        record_type="email",
        title="Refund",
        body="Refund request",
        source_url="https://mail.example/msg-1",
        thread_ref="thread-1",
        permission_refs=("group:finance",),
        attachment_refs=("gmail:attachment-1",),
        identity_refs=("gmail:user-1",),
        source_identities=(
            SourceIdentity(
                source_system="gmail",
                identity_ref="gmail:user-1",
                identity_type="sender",
                value="person@example.com",
                display_name="Person Example",
            ),
        ),
    )
    replacement = SourceRecord(
        source_ref="gmail:msg-1",
        source_system="gmail",
        source_id="msg-1",
        record_type="email",
        title="Updated refund",
        body="Updated request",
        occurred_at="2026-01-02T03:04:05Z",
        updated_at="2026-01-02T03:05:06Z",
        author_ref="gmail:user-2",
        permission_refs=("group:support",),
        metadata={"label_ids": ["INBOX"]},
    )

    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        records=[first],
    )
    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        records=[replacement],
    )

    rows = source_record_rows(state.engine, state.source_records)
    checksum = rows[0].pop("checksum")
    version = rows[0].pop("version")
    assert isinstance(checksum, str)
    assert checksum.startswith("sha256:")
    assert version == checksum
    assert rows == [
        {
            "source_ref": "gmail:msg-1",
            "source_system": "gmail",
            "source_id": "msg-1",
            "record_type": "email",
            "title": "Updated refund",
            "retrieval_text": "Updated request",
            "author_ref": "gmail:user-2",
            "occurred_at": "2026-01-02T03:04:05Z",
            "updated_at": "2026-01-02T03:05:06Z",
            "source_url": "",
            "thread_ref": "",
            "permission_refs": '["group:support"]',
            "permission_snapshot_status": "current",
            "attachment_refs": "[]",
            "identity_refs": "[]",
            "lifecycle_state": "active",
            "metadata_json": '{"label_ids": ["INBOX"]}',
            "raw_ref": "",
        }
    ]
    assert source_identity_rows(state.engine, state.source_identities) == []


def test_changed_source_record_marks_retrieval_records_stale() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    first = SourceRecord(
        source_ref="linear:issue:OPS-1",
        source_system="linear",
        source_id="OPS-1",
        record_type="work_item",
        title="Ask Robin",
        body="Ask Robin to move the meeting",
    )
    changed = SourceRecord(
        source_ref="linear:issue:OPS-1",
        source_system="linear",
        source_id="OPS-1",
        record_type="work_item",
        title="Ask Robin",
        body="Ask Robin to move the meeting next week",
    )

    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        retrieval_records_table=state.retrieval_records,
        records=[first],
    )
    first_checksum = source_record_rows(state.engine, state.source_records)[0]["checksum"]
    store_retrieval_records(
        state.engine,
        state.retrieval_records,
        records=[
            RetrievalRecord(
                retrieval_ref="retrieval:linear:issue:OPS-1",
                source_ref="linear:issue:OPS-1",
                unit_index=0,
                start_offset=0,
                end_offset=29,
                index_kind="full_text",
                status="current",
                source_checksum=str(first_checksum),
                prepared_text="Ask Robin to move the meeting",
            )
        ],
    )

    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        retrieval_records_table=state.retrieval_records,
        records=[changed],
    )

    assert retrieval_record_rows(state.engine, state.retrieval_records) == [
        {
            "retrieval_ref": "retrieval:linear:issue:OPS-1",
            "source_ref": "linear:issue:OPS-1",
            "unit_index": 0,
            "start_offset": 0,
            "end_offset": 29,
            "index_kind": "full_text",
            "status": "stale",
            "source_checksum": first_checksum,
            "prepared_text": "Ask Robin to move the meeting",
            "updated_at": "",
        }
    ]


def test_prepare_retrieval_records_keeps_short_record_as_one_unit() -> None:
    record = SourceRecord(
        source_ref="linear:issue:OPS-2",
        source_system="linear",
        source_id="OPS-2",
        record_type="work_item",
        title="Ask Robin",
        body="Move the customer meeting.",
    )

    rows = prepare_retrieval_records([record])

    assert len(rows) == 1
    assert rows[0].retrieval_ref == "retrieval:linear:issue:OPS-2:0000:full_text"
    assert rows[0].source_ref == "linear:issue:OPS-2"
    assert rows[0].unit_index == 0
    assert rows[0].start_offset == 0
    assert rows[0].end_offset == len("Ask Robin Move the customer meeting.")
    assert rows[0].index_kind == "full_text"
    assert rows[0].status == "current"
    assert rows[0].prepared_text == "Ask Robin Move the customer meeting."


def test_prepare_retrieval_records_splits_long_records_with_overlap() -> None:
    record = SourceRecord(
        source_ref="docs:policy:1",
        source_system="google_drive",
        source_id="policy-1",
        record_type="document",
        title="Policy",
        body=" ".join(f"word{index}" for index in range(12)),
    )

    rows = prepare_retrieval_records([record], max_words=6, overlap_words=2)

    assert [row.unit_index for row in rows] == [0, 1, 2]
    assert [row.prepared_text for row in rows] == [
        "Policy word0 word1 word2 word3 word4",
        "word3 word4 word5 word6 word7 word8",
        "word7 word8 word9 word10 word11",
    ]
    assert all(row.source_checksum.startswith("sha256:") for row in rows)


def test_store_source_records_replaces_existing_source_identity_on_source_ref_change() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )

    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        records=[
            SourceRecord(
                source_ref="linear:old:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Old source ref",
                body="Old body",
            )
        ],
    )
    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        records=[
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Stable source identity",
                body="New body",
            )
        ],
    )

    assert [
        (row["source_ref"], row["source_system"], row["source_id"], row["title"])
        for row in source_record_rows(state.engine, state.source_records)
    ] == [("linear:issue:OPS-1", "linear", "OPS-1", "Stable source identity")]


def test_source_metadata_filters_by_permission_refs_with_group_inheritance() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    store_source_records(
        state.engine,
        source_records_table=state.source_records,
        source_identities_table=state.source_identities,
        records=[
            SourceRecord(
                source_ref="gmail:finance",
                source_system="gmail",
                source_id="finance",
                record_type="email",
                title="Finance",
                body="Finance request",
                source_url="https://mail.example/finance",
                permission_refs=("group:finance",),
                attachment_refs=("gmail:attachment-1",),
            ),
            SourceRecord(
                source_ref="gmail:support",
                source_system="gmail",
                source_id="support",
                record_type="email",
                title="Support",
                body="Support request",
                permission_refs=("group:support",),
            ),
        ],
    )
    principal = PrincipalContext(
        human_id="human:lead",
        agent_id="agent:context",
        roles=("group:finance-leads",),
    )
    group_inheritance = {"group:finance-leads": ("group:finance",)}

    assert source_metadata(
        state.engine,
        state.source_records,
        source_ref="gmail:missing",
        principal=principal,
        group_inheritance=group_inheritance,
    ) == {"status": "not_found", "source_ref": "gmail:missing"}
    assert source_metadata(
        state.engine,
        state.source_records,
        source_ref="gmail:support",
        principal=principal,
        group_inheritance=group_inheritance,
    ) == {
        "status": "denied",
        "source_ref": "gmail:support",
        "reason": "source_permission_denied",
    }
    assert source_metadata(
        state.engine,
        state.source_records,
        source_ref="gmail:finance",
        principal=principal,
        group_inheritance=group_inheritance,
    ) == {
        "status": "allowed",
        "source_ref": "gmail:finance",
        "source_system": "gmail",
        "source_id": "finance",
        "record_type": "email",
        "source_url": "https://mail.example/finance",
        "thread_ref": "",
        "attachment_refs": ["gmail:attachment-1"],
        "lifecycle_state": "active",
    }
    assert denied_source_refs(
        state.engine,
        state.source_records,
        principal=principal,
        group_inheritance=group_inheritance,
    ) == {"gmail:support"}
