from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from fourok.etl.extract.source_records import SourceRecord
from fourok.observability import critical_span, set_safe_span_attributes


class SourceRecordImporter(Protocol):
    def ingest_source_records(self, records: list[SourceRecord]) -> None: ...

    def retrieval_units(self) -> list[dict[str, object]]: ...


@dataclass(frozen=True)
class SourceRecordImportReport:
    record_count: int
    source_refs: tuple[str, ...]
    source_systems: tuple[str, ...]
    record_types: tuple[str, ...]
    lifecycle_states: tuple[str, ...]
    restricted_count: int
    retrieval_unit_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "record_count": self.record_count,
            "source_refs": list(self.source_refs),
            "source_ref_count": len(self.source_refs),
            "source_systems": list(self.source_systems),
            "record_types": list(self.record_types),
            "lifecycle_states": list(self.lifecycle_states),
            "restricted_count": self.restricted_count,
            "retrieval_unit_count": self.retrieval_unit_count,
        }


def import_source_records(
    context: SourceRecordImporter,
    records: list[SourceRecord],
) -> SourceRecordImportReport:
    with critical_span(
        "fourok.source_records.import",
        status_attribute="fourok.source_record.status",
    ) as span:
        context.ingest_source_records(records)
        report = source_record_import_report(
            records,
            retrieval_unit_count=len(context.retrieval_units()),
        )
        set_safe_span_attributes(
            span,
            {
                "fourok.source_record.status": "succeeded",
                "fourok.source_record.count": report.record_count,
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
    retrieval_unit_count: int,
) -> SourceRecordImportReport:
    return SourceRecordImportReport(
        record_count=len(records),
        source_refs=tuple(record.source_ref for record in records),
        source_systems=tuple(sorted({record.source_system for record in records})),
        record_types=tuple(sorted({record.record_type for record in records})),
        lifecycle_states=tuple(sorted({record.effective_lifecycle_state for record in records})),
        restricted_count=sum(
            1 for record in records if record.effective_lifecycle_state != "active"
        ),
        retrieval_unit_count=retrieval_unit_count,
    )
