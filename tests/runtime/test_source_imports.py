from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.runtime.rebuild import rebuild_context_objects
from fourok.runtime.source_imports import import_source_records, source_record_import_report


class RecordingImporter:
    def __init__(self) -> None:
        self.ingested: list[SourceRecord] = []

    def ingest_source_records(self, records: list[SourceRecord]) -> None:
        self.ingested.extend(records)

    def retrieval_units(self) -> list[dict[str, object]]:
        return [{"source_ref": record.source_ref} for record in self.ingested]


def test_import_source_records_ingests_and_reports_observable_counts() -> None:
    records = [
        SourceRecord(
            source_ref="linear:issue:OPS-1",
            source_system="linear",
            source_id="OPS-1",
            record_type="work_item",
            title="Operational follow-up",
            body="Track production readiness.",
        ),
        SourceRecord(
            source_ref="drive:file:doc-1",
            source_system="google_drive",
            source_id="doc-1",
            record_type="document",
            title="Restricted source",
            body="Source content requires restricted lifecycle.",
            lifecycle_state="restricted",
        ),
    ]
    importer = RecordingImporter()

    report = import_source_records(importer, records)

    assert importer.ingested == records
    assert report.to_dict() == {
        "record_count": 2,
        "source_refs": ["linear:issue:OPS-1", "drive:file:doc-1"],
        "source_ref_count": 2,
        "source_systems": ["google_drive", "linear"],
        "record_types": ["document", "work_item"],
        "lifecycle_states": ["active", "restricted"],
        "restricted_count": 1,
        "deleted_record_count": 0,
        "deleted_source_refs": [],
        "retrieval_unit_count": 2,
    }


def test_snapshot_import_marks_missing_records_deleted_without_touching_other_scopes(
    tmp_path,
) -> None:
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")
    stale_issue = SourceRecord(
        source_ref="linear:issue:stale",
        source_system="linear",
        source_id="stale",
        record_type="work_item",
        title="Stale issue",
        body="This issue disappeared from the latest Linear snapshot.",
    )
    current_issue = SourceRecord(
        source_ref="linear:issue:current",
        source_system="linear",
        source_id="current",
        record_type="work_item",
        title="Current issue",
        body="This issue remains in the latest Linear snapshot.",
    )
    current_user = SourceRecord(
        source_ref="linear:user:current",
        source_system="linear",
        source_id="current-user",
        record_type="person",
        title="Current user",
        body="This person stream is outside the issue snapshot scope.",
    )
    twenty_company = SourceRecord(
        source_ref="twenty:company:1",
        source_system="twenty",
        source_id="1",
        record_type="organization",
        title="Twenty Company",
        body="This other source system must not be touched.",
    )
    context.ingest_source_records([stale_issue, current_issue, current_user, twenty_company])

    report = import_source_records(
        context,
        [current_issue],
        snapshot_deletes=True,
    )

    rows = {row["source_ref"]: row for row in context.source_records()}
    assert rows["linear:issue:stale"]["lifecycle_state"] == "deleted"
    assert rows["linear:issue:current"]["lifecycle_state"] == "active"
    assert rows["linear:user:current"]["lifecycle_state"] == "active"
    assert rows["twenty:company:1"]["lifecycle_state"] == "active"
    assert context.search_context("disappeared").results == []
    assert report.deleted_record_count == 1
    assert report.to_dict()["deleted_source_refs"] == ["linear:issue:stale"]


def test_snapshot_import_can_delete_an_empty_stream_when_scope_is_explicit(tmp_path) -> None:
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")
    stale_company = SourceRecord(
        source_ref="twenty:company:gone",
        source_system="twenty",
        source_id="gone",
        record_type="organization",
        title="Gone Company",
        body="This company disappeared from a complete companies snapshot.",
    )
    remaining_person = SourceRecord(
        source_ref="twenty:person:kept",
        source_system="twenty",
        source_id="kept",
        record_type="person",
        title="Kept Person",
        body="This person stream is not in scope.",
    )
    context.ingest_source_records([stale_company, remaining_person])

    report = import_source_records(
        context,
        [],
        snapshot_deletes=True,
        snapshot_scopes={("twenty", "organization")},
    )

    rows = {row["source_ref"]: row for row in context.source_records()}
    assert rows["twenty:company:gone"]["lifecycle_state"] == "deleted"
    assert rows["twenty:person:kept"]["lifecycle_state"] == "active"
    assert report.deleted_source_refs == ("twenty:company:gone",)


def test_source_record_import_report_can_be_used_without_mutating_context() -> None:
    record = SourceRecord(
        source_ref="slack:user:U1",
        source_system="slack",
        source_id="U1",
        record_type="person",
        title="Slack user",
        body="Slack user profile",
    )

    report = source_record_import_report([record], retrieval_unit_count=3)

    assert report.record_count == 1
    assert report.retrieval_unit_count == 3
    assert report.source_refs == ("slack:user:U1",)


def test_rebuild_context_objects_recreates_derived_rows_from_source_records(tmp_path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:user:olivia",
                source_system="linear",
                source_id="linear-user-olivia",
                record_type="person",
                title="Olivia",
                body="Olivia user profile",
                source_identities=(
                    SourceIdentity(
                        source_system="linear",
                        identity_ref="linear:email:olivia@example.com",
                        identity_type="email",
                        value="olivia@example.com",
                    ),
                ),
            ),
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Operational follow-up",
                body="Track production readiness.",
                author_ref="linear-user-olivia",
            ),
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    deleted = rebuild_context_objects(state)

    assert deleted == {
        "status": "completed",
        "source_records": 2,
        "canonical_objects_deleted": 2,
        "canonical_objects_created": 2,
        "entity_links_deleted": 1,
        "entity_links_created": 1,
    }
    refreshed = GovernedContext(state_path)
    assert {row["object_ref"] for row in refreshed.canonical_objects()} == {
        "linear:user:olivia",
        "linear:issue:OPS-1",
    }
    assert refreshed.entity_links()[0]["object_ref"] == "linear:user:olivia"
