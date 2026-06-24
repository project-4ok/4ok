from pathlib import Path

from gcb.etl.extract.source_records import SourceRecord
from gcb.governance import GovernedContext, SourceChange


def test_snapshot_deleted_source_is_restored_when_present_in_later_active_import(
    tmp_path: Path,
) -> None:
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")
    record = SourceRecord(
        source_ref="twenty:company:company-restored",
        source_system="twenty",
        source_id="company-restored",
        record_type="organization",
        title="Restored Twenty Company",
        body="Restored Twenty Company",
    )

    context.ingest_source_records([record])
    context.apply_source_changes(
        [
            SourceChange(
                operation="delete",
                source_ref=record.source_ref,
                reason="missing_from_latest_snapshot",
            )
        ]
    )
    assert context.source_records()[0]["lifecycle_state"] == "deleted"
    assert context.search_context("Restored Twenty Company").results == []

    context.ingest_source_records([record])

    assert context.source_lifecycle() == []
    assert context.source_records()[0]["lifecycle_state"] == "active"
    assert [
        result.source_ref for result in context.search_context("Restored Twenty Company").results
    ] == [record.source_ref]
