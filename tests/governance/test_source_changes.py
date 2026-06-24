from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.etl.load.retrieval_records import retrieval_record_rows
from fourok.governance import GovernedContext, SourceChange
from fourok.governance.state import create_governed_context_state
from fourok.storage.config import RetrievalConfig


def test_source_change_restriction_hides_non_email_record_and_keeps_lifecycle_state() -> None:
    context = GovernedContext()
    record = SourceRecord(
        source_ref="linear:issue:OPS-1",
        source_system="linear",
        source_id="OPS-1",
        record_type="work_item",
        title="Ask Robin",
        body="Ask Robin to move the customer meeting.",
    )
    context.ingest_source_records([record])

    context.apply_source_changes(
        [
            SourceChange(
                operation="restrict",
                source_ref="linear:issue:OPS-1",
                reason="permission_revoked",
            )
        ]
    )

    assert context.search_context("customer meeting").results == []
    assert context.source_records()[0]["lifecycle_state"] == "restricted"
    assert context.canonical_objects()[0]["lifecycle_state"] == "restricted"
    assert context.source_lifecycle() == [
        {
            "source_ref": "linear:issue:OPS-1",
            "state": "restricted",
            "reason": "permission_revoked",
        }
    ]


def test_restrict_source_convenience_method_uses_source_change_applier() -> None:
    context = GovernedContext()
    record = SourceRecord(
        source_ref="linear:issue:OPS-shortcut",
        source_system="linear",
        source_id="OPS-shortcut",
        record_type="work_item",
        title="Shortcut customer issue",
        body="Shortcut customer issue.",
    )
    context.ingest_source_records([record])

    context.restrict_source("linear:issue:OPS-shortcut", reason="permission_revoked")

    assert context.search_context("shortcut customer").results == []
    assert context.source_records()[0]["lifecycle_state"] == "restricted"
    assert context.canonical_objects()[0]["lifecycle_state"] == "restricted"
    assert context.entity_links() == []


def test_inactive_source_change_removes_source_identity_rows_until_restore() -> None:
    context = GovernedContext()
    record = SourceRecord(
        source_ref="linear:user:olivia",
        source_system="linear",
        source_id="user-olivia",
        record_type="person",
        title="Olivia",
        body="Olivia workspace member",
        identity_refs=("linear:user:olivia",),
        source_identities=(
            SourceIdentity(
                source_system="linear",
                identity_ref="linear:user:olivia",
                identity_type="email",
                value="olivia@example.com",
                display_name="Olivia",
            ),
        ),
    )
    context.ingest_source_records([record])

    context.apply_source_changes(
        [SourceChange(operation="restrict", source_ref=record.source_ref, reason="permission")]
    )

    assert context.source_identities() == []

    context.apply_source_changes([SourceChange(operation="restore", record=record)])

    assert context.source_identities() == [
        {
            "source_ref": "linear:user:olivia",
            "source_system": "linear",
            "identity_ref": "linear:user:olivia",
            "identity_type": "email",
            "value": "olivia@example.com",
            "display_name": "Olivia",
        }
    ]


def test_upsert_does_not_revive_restricted_record_without_restore_change() -> None:
    context = GovernedContext()
    original = SourceRecord(
        source_ref="linear:issue:OPS-2",
        source_system="linear",
        source_id="OPS-2",
        record_type="work_item",
        title="Original customer issue",
        body="Original customer issue.",
    )
    updated = SourceRecord(
        source_ref="linear:issue:OPS-2",
        source_system="linear",
        source_id="OPS-2",
        record_type="work_item",
        title="Updated customer issue",
        body="Updated customer issue.",
    )
    context.ingest_source_records([original])
    context.apply_source_changes(
        [SourceChange(operation="restrict", source_ref=original.source_ref, reason="hold")]
    )

    context.ingest_source_records([updated])

    row = context.source_records()[0]
    assert row["title"] == "Updated customer issue"
    assert row["lifecycle_state"] == "restricted"
    assert context.search_context("updated customer").results == []


def test_same_batch_inactive_change_prevents_later_upsert_from_reviving_record() -> None:
    context = GovernedContext()
    original = SourceRecord(
        source_ref="linear:issue:OPS-3",
        source_system="linear",
        source_id="OPS-3",
        record_type="work_item",
        title="Original batch issue",
        body="Original batch issue.",
    )
    updated = SourceRecord(
        source_ref="linear:issue:OPS-3",
        source_system="linear",
        source_id="OPS-3",
        record_type="work_item",
        title="Updated batch issue",
        body="Updated batch issue should stay hidden.",
    )
    context.ingest_source_records([original])

    context.apply_source_changes(
        [
            SourceChange(operation="restrict", source_ref=original.source_ref, reason="acl_hold"),
            SourceChange(operation="upsert", record=updated),
        ]
    )

    assert context.source_records()[0]["title"] == "Updated batch issue"
    assert context.source_records()[0]["lifecycle_state"] == "restricted"
    assert context.search_context("updated batch").results == []
    assert context.source_lifecycle() == [
        {"source_ref": "linear:issue:OPS-3", "state": "restricted", "reason": "acl_hold"}
    ]


def test_restore_source_change_reactivates_record_and_search_index() -> None:
    context = GovernedContext()
    record = SourceRecord(
        source_ref="gmail:message:restore-1",
        source_system="gmail",
        source_id="restore-1",
        record_type="email",
        title="Restore customer request",
        body="Customer request should be searchable after restore.",
        raw={"from": "ops@example.com", "to": ["finance@example.com"]},
    )
    context.ingest_source_records([record])
    context.apply_source_changes(
        [SourceChange(operation="delete", source_ref=record.source_ref, reason="source_deleted")]
    )

    context.apply_source_changes([SourceChange(operation="restore", record=record)])

    assert context.source_lifecycle() == []
    assert context.source_records()[0]["lifecycle_state"] == "active"
    assert [result.source_ref for result in context.search_context("after restore").results] == [
        "gmail:message:restore-1"
    ]


def test_restrict_and_restore_update_vector_index_for_non_email_records() -> None:
    context = GovernedContext()
    record = SourceRecord(
        source_ref="linear:issue:vector-restore",
        source_system="linear",
        source_id="vector-restore",
        record_type="work_item",
        title="Vector restore issue",
        body="Vector restoration marker should follow lifecycle changes.",
    )
    context.ingest_source_records([record])
    vector_index = context.build_vector_index()

    assert [result.source_ref for result in vector_index.search("restoration marker", limit=1)] == [
        record.source_ref
    ]

    context.apply_source_changes(
        [SourceChange(operation="restrict", source_ref=record.source_ref, reason="acl_hold")]
    )

    assert record.source_ref not in [
        result.source_ref for result in vector_index.search("restoration marker", limit=3)
    ]

    context.apply_source_changes([SourceChange(operation="restore", record=record)])

    assert [result.source_ref for result in vector_index.search("restoration marker", limit=1)] == [
        record.source_ref
    ]


def test_duplicate_and_supersede_changes_hide_records_without_deleting_raw_state() -> None:
    context = GovernedContext()
    records = [
        SourceRecord(
            source_ref="linear:issue:duplicate",
            source_system="linear",
            source_id="duplicate",
            record_type="work_item",
            title="Duplicate customer meeting",
            body="Duplicate customer meeting.",
        ),
        SourceRecord(
            source_ref="linear:issue:superseded",
            source_system="linear",
            source_id="superseded",
            record_type="work_item",
            title="Superseded customer meeting",
            body="Superseded customer meeting.",
        ),
    ]
    context.ingest_source_records(records)

    context.apply_source_changes(
        [
            SourceChange(operation="duplicate", source_ref="linear:issue:duplicate"),
            SourceChange(operation="supersede", source_ref="linear:issue:superseded"),
        ]
    )

    assert context.search_context("customer meeting").results == []
    assert {row["source_ref"]: row["lifecycle_state"] for row in context.source_records()} == {
        "linear:issue:duplicate": "duplicate",
        "linear:issue:superseded": "supersede",
    }
    assert context.source_lifecycle() == [
        {"source_ref": "linear:issue:duplicate", "state": "duplicate", "reason": "duplicate"},
        {"source_ref": "linear:issue:superseded", "state": "supersede", "reason": "supersede"},
    ]


def test_duplicate_and_supersede_changes_preserve_cleanup_provenance() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:duplicate",
                source_system="linear",
                source_id="duplicate",
                record_type="work_item",
                title="Duplicate customer meeting",
                body="Duplicate customer meeting.",
            ),
            SourceRecord(
                source_ref="linear:issue:superseded",
                source_system="linear",
                source_id="superseded",
                record_type="work_item",
                title="Superseded customer meeting",
                body="Superseded customer meeting.",
            ),
        ]
    )

    context.apply_source_changes(
        [
            SourceChange(
                operation="duplicate",
                source_ref="linear:issue:duplicate",
                duplicate_group_ref="duplicate-group:customer-meeting",
            ),
            SourceChange(
                operation="supersede",
                source_ref="linear:issue:superseded",
                replacement_ref="linear:issue:replacement",
            ),
        ]
    )

    assert context.source_lifecycle() == [
        {
            "source_ref": "linear:issue:duplicate",
            "state": "duplicate",
            "reason": "duplicate",
            "duplicate_group_ref": "duplicate-group:customer-meeting",
        },
        {
            "source_ref": "linear:issue:superseded",
            "state": "supersede",
            "reason": "supersede",
            "replacement_ref": "linear:issue:replacement",
        },
    ]


def test_source_change_import_prepares_and_replaces_retrieval_units(tmp_path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    first = SourceRecord(
        source_ref="docs:runbook:1",
        source_system="google_drive",
        source_id="runbook-1",
        record_type="document",
        title="Customer runbook",
        body="firstonly searchable text",
    )
    second = SourceRecord(
        source_ref="docs:runbook:1",
        source_system="google_drive",
        source_id="runbook-1",
        record_type="document",
        title="Customer runbook",
        body="updatedonly searchable text",
    )

    context.ingest_source_records([first])
    context.ingest_source_records([second])

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    rows = retrieval_record_rows(state.engine, state.retrieval_records)
    assert rows == [
        {
            "retrieval_ref": "retrieval:docs:runbook:1:0000:full_text",
            "source_ref": "docs:runbook:1",
            "unit_index": 0,
            "start_offset": 0,
            "end_offset": len("Customer runbook updatedonly searchable text"),
            "index_kind": "full_text",
            "status": "current",
            "source_checksum": context.source_records()[0]["checksum"],
            "prepared_text": "Customer runbook updatedonly searchable text",
            "updated_at": "",
        }
    ]
    assert context.search_context("updatedonly").results[0].source_ref == "docs:runbook:1"
    assert context.search_context("firstonly").results == []


def test_source_change_import_is_idempotent_for_repeated_records_in_one_batch(
    tmp_path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    original = SourceRecord(
        source_ref="google_drive:file:runbook-duplicate",
        source_system="google_drive",
        source_id="runbook-duplicate",
        record_type="document",
        title="Customer runbook",
        body="oldonly landing text",
    )
    updated = SourceRecord(
        source_ref="google_drive:file:runbook-duplicate",
        source_system="google_drive",
        source_id="runbook-duplicate",
        record_type="document",
        title="Customer runbook",
        body="newonly landing text",
    )

    context.ingest_source_records([original])
    context.ingest_source_records([original, updated])

    assert context.source_records()[0]["retrieval_text"] == "newonly landing text"
    assert [unit["prepared_text"] for unit in context.retrieval_units()] == [
        "Customer runbook newonly landing text"
    ]
    assert context.search_context("newonly").results[0].source_ref == (
        "google_drive:file:runbook-duplicate"
    )
    assert context.search_context("oldonly").results == []


def test_source_change_import_removes_old_email_index_when_source_ref_changes() -> None:
    context = GovernedContext()
    first = SourceRecord(
        source_ref="gmail:old-message-ref",
        source_system="gmail",
        source_id="message-1",
        record_type="email",
        title="Customer update",
        body="oldonly searchable email text",
    )
    second = SourceRecord(
        source_ref="gmail:new-message-ref",
        source_system="gmail",
        source_id="message-1",
        record_type="email",
        title="Customer update",
        body="newonly searchable email text",
    )

    context.ingest_source_records([first])
    context.ingest_source_records([second])

    assert [result.source_ref for result in context.search_context("newonly").results] == [
        "gmail:new-message-ref"
    ]
    assert context.search_context("oldonly").results == []


def test_source_change_import_removes_old_raw_ref_when_source_ref_changes(tmp_path) -> None:
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")
    first = SourceRecord(
        source_ref="docs:old-ref",
        source_system="google_drive",
        source_id="doc-1",
        record_type="document",
        title="Old document ref",
        body="old raw source body",
    )
    second = SourceRecord(
        source_ref="docs:new-ref",
        source_system="google_drive",
        source_id="doc-1",
        record_type="document",
        title="New document ref",
        body="new raw source body",
    )

    context.ingest_source_records([first])
    context.ingest_source_records([second])

    assert context.raw_source_refs() == ["docs:new-ref"]


def test_source_change_import_uses_configured_retrieval_chunk_policy(tmp_path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(
        state_path,
        retrieval_config=RetrievalConfig(max_words=6, overlap_words=2),
    )
    record = SourceRecord(
        source_ref="docs:policy:configured",
        source_system="google_drive",
        source_id="configured",
        record_type="document",
        title="Policy",
        body=" ".join(f"word{index}" for index in range(12)),
    )

    context.ingest_source_records([record])

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    rows = retrieval_record_rows(state.engine, state.retrieval_records)
    assert [row["unit_index"] for row in rows] == [0, 1, 2]
    assert [row["prepared_text"] for row in rows] == [
        "Policy word0 word1 word2 word3 word4",
        "word3 word4 word5 word6 word7 word8",
        "word7 word8 word9 word10 word11",
    ]
