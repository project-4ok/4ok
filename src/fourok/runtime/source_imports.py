from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import SourceChange
from fourok.observability import critical_span, set_safe_span_attributes


class SourceRecordImporter(Protocol):
    def ingest_source_records(self, records: list[SourceRecord]) -> None: ...

    def retrieval_units(self) -> list[dict[str, object]]: ...


class SnapshotSourceRecordImporter(SourceRecordImporter, Protocol):
    def apply_source_changes(self, changes: list[SourceChange]) -> None: ...

    def source_records(self) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class SourceRecordImportReport:
    record_count: int
    source_refs: tuple[str, ...]
    source_systems: tuple[str, ...]
    record_types: tuple[str, ...]
    lifecycle_states: tuple[str, ...]
    restricted_count: int
    retrieval_unit_count: int
    deleted_source_refs: tuple[str, ...] = ()
    deleted_record_count: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "source_refs": list(self.source_refs),
            "source_ref_count": len(self.source_refs),
            "deleted_source_refs": list(self.deleted_source_refs),
            "source_systems": list(self.source_systems),
            "record_types": list(self.record_types),
            "lifecycle_states": list(self.lifecycle_states),
            "restricted_count": self.restricted_count,
            "deleted_record_count": self.deleted_record_count,
            "retrieval_unit_count": self.retrieval_unit_count,
        }


def import_source_records(
    context: SourceRecordImporter,
    records: list[SourceRecord],
    *,
    snapshot_deletes: bool = False,
    snapshot_scopes: set[tuple[str, str]] | None = None,
) -> SourceRecordImportReport:
    with critical_span(
        "fourok.source_records.import",
        status_attribute="fourok.source_record.status",
    ) as span:
        deleted_changes: list[SourceChange] = []
        if snapshot_deletes:
            snapshot_context = _snapshot_context(context)
            deleted_changes = _deleted_snapshot_changes(
                snapshot_context.source_records(),
                records,
                snapshot_scopes=snapshot_scopes,
            )
            snapshot_context.apply_source_changes(
                [
                    *(SourceChange(operation="upsert", record=record) for record in records),
                    *deleted_changes,
                ]
            )
        else:
            context.ingest_source_records(records)
        report = source_record_import_report(
            records,
            deleted_source_refs=tuple(change.source_ref or "" for change in deleted_changes),
            retrieval_unit_count=len(context.retrieval_units()),
        )
        set_safe_span_attributes(
            span,
            {
                "fourok.source_record.status": "succeeded",
                "fourok.source_record.count": report.record_count,
                "fourok.source_record.deleted_count": report.deleted_record_count,
                "fourok.source_record.source_systems": ",".join(report.source_systems),
                "fourok.source_record.record_types": ",".join(report.record_types),
                "fourok.source_record.restricted_count": report.restricted_count,
                "fourok.retrieval.unit_count": report.retrieval_unit_count,
            },
        )
        return report


def source_record_import_report(
    records: list[SourceRecord],
    *,
    deleted_source_refs: tuple[str, ...] = (),
    retrieval_unit_count: int,
) -> SourceRecordImportReport:
    return SourceRecordImportReport(
        record_count=len(records),
        source_refs=tuple(record.source_ref for record in records),
        deleted_source_refs=tuple(ref for ref in deleted_source_refs if ref),
        source_systems=tuple(sorted({record.source_system for record in records})),
        record_types=tuple(sorted({record.record_type for record in records})),
        lifecycle_states=tuple(sorted({record.effective_lifecycle_state for record in records})),
        restricted_count=sum(
            1 for record in records if record.effective_lifecycle_state != "active"
        ),
        deleted_record_count=len([ref for ref in deleted_source_refs if ref]),
        retrieval_unit_count=retrieval_unit_count,
    )


def _snapshot_context(context: SourceRecordImporter) -> SnapshotSourceRecordImporter:
    if not hasattr(context, "apply_source_changes") or not hasattr(context, "source_records"):
        raise TypeError("snapshot_deletes requires a governed context with source_records")
    return context  # type: ignore[return-value]


def _deleted_snapshot_changes(
    existing_rows: list[dict[str, object]],
    incoming_records: list[SourceRecord],
    *,
    snapshot_scopes: set[tuple[str, str]] | None = None,
) -> list[SourceChange]:
    incoming_scopes = snapshot_scopes or {
        (record.source_system, record.record_type) for record in incoming_records
    }
    if not incoming_scopes:
        return []
    incoming_source_refs = {record.source_ref for record in incoming_records}
    return [
        SourceChange(
            operation="delete",
            source_ref=str(row["source_ref"]),
            reason="missing_from_latest_snapshot",
        )
        for row in existing_rows
        if (str(row["source_system"]), str(row["record_type"])) in incoming_scopes
        and str(row["source_ref"]) not in incoming_source_refs
        and row["lifecycle_state"] != "deleted"
    ]
