from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.load.context_objects import (
    canonical_objects_from_source_records,
    entity_links_from_source_records,
    store_canonical_objects,
    store_entity_links,
)
from fourok.etl.load.retrieval_records import (
    DEFAULT_RETRIEVAL_MAX_WORDS,
    DEFAULT_RETRIEVAL_OVERLAP_WORDS,
    prepare_retrieval_records,
    replace_retrieval_records_for_sources,
    replace_vector_index_for_retrieval_records,
)
from fourok.etl.load.source_metadata import latest_source_records, store_source_records
from fourok.governance.indexing import IndexingTables, delete_legacy_email_index_rows
from fourok.governance.lifecycle import (
    RawSourceStore,
    inactive_source_refs,
    remove_source_from_retrieval,
)
from fourok.governance.policy import PrincipalContext

SourceChangeOperation = Literal[
    "upsert",
    "delete",
    "restrict",
    "restore",
    "supersede",
    "duplicate",
]


@dataclass(frozen=True)
class SourceChange:
    operation: SourceChangeOperation
    record: SourceRecord | None = None
    source_ref: str = ""
    reason: str = ""
    replacement_ref: str = ""
    duplicate_group_ref: str = ""

    @property
    def target_source_ref(self) -> str:
        if self.source_ref:
            return self.source_ref
        if self.record is not None:
            return self.record.source_ref
        raise ValueError(f"{self.operation} source change requires source_ref or record")


@dataclass(frozen=True)
class SourceChangeTables:
    source_records: Table
    source_identities: Table
    canonical_objects: Table
    entity_links: Table
    retrieval_records: Table
    source_lifecycle: Table
    audit_events: Table
    indexing: IndexingTables


def upsert_source_records(records: list[SourceRecord]) -> list[SourceChange]:
    return [SourceChange(operation="upsert", record=record) for record in records]


def apply_source_changes(
    engine: Engine,
    tables: SourceChangeTables,
    *,
    changes: list[SourceChange],
    raw_store: RawSourceStore | None,
    principal: PrincipalContext,
    retrieval_max_words: int = DEFAULT_RETRIEVAL_MAX_WORDS,
    retrieval_overlap_words: int = DEFAULT_RETRIEVAL_OVERLAP_WORDS,
) -> None:
    if not changes:
        return

    active_records: list[SourceRecord] = []
    lifecycle_state_by_ref = _source_lifecycle_state_by_ref(engine, tables.source_lifecycle)
    for change in changes:
        if change.operation == "upsert":
            if change.record is None:
                raise ValueError("upsert source change requires record")
            lifecycle_entry = lifecycle_state_by_ref.get(change.record.source_ref)
            if _should_restore_from_active_import(change.record, lifecycle_entry):
                _restore_source(engine, tables, change.record.source_ref)
                lifecycle_state_by_ref.pop(change.record.source_ref, None)
                active_records.append(change.record)
                continue
            record = _record_with_existing_lifecycle(change.record, lifecycle_state_by_ref)
            if (
                record.effective_lifecycle_state != "active"
                and record.source_ref not in lifecycle_state_by_ref
            ):
                _apply_inactive_change(
                    engine,
                    tables,
                    raw_store=raw_store,
                    source_ref=record.source_ref,
                    state=record.effective_lifecycle_state,
                    reason=record.lifecycle_reason,
                    replacement_ref="",
                    duplicate_group_ref="",
                    principal=principal,
                )
            active_records.append(record)
            continue
        if change.operation == "restore":
            if change.record is None:
                raise ValueError("restore source change requires record")
            _restore_source(engine, tables, change.target_source_ref)
            lifecycle_state_by_ref.pop(change.target_source_ref, None)
            active_records.append(replace(change.record, lifecycle_state="active"))
            continue

        inactive_state = _inactive_state_for(change.operation)
        _apply_inactive_change(
            engine,
            tables,
            raw_store=raw_store,
            source_ref=change.target_source_ref,
            state=inactive_state,
            reason=change.reason or change.operation,
            replacement_ref=change.replacement_ref,
            duplicate_group_ref=change.duplicate_group_ref,
            principal=principal,
        )
        lifecycle_state_by_ref[change.target_source_ref] = {
            "state": inactive_state,
            "reason": change.reason or change.operation,
        }

    if active_records:
        _store_active_records(
            engine,
            tables,
            records=active_records,
            raw_store=raw_store,
            retrieval_max_words=retrieval_max_words,
            retrieval_overlap_words=retrieval_overlap_words,
        )


def _store_active_records(
    engine: Engine,
    tables: SourceChangeTables,
    *,
    records: list[SourceRecord],
    raw_store: RawSourceStore | None,
    retrieval_max_words: int,
    retrieval_overlap_words: int,
) -> None:
    records = latest_source_records(records)
    records = _records_with_raw_refs(records, raw_store=raw_store)
    replaced_source_refs = _replaced_source_refs_for_records(engine, tables.source_records, records)
    touched_source_refs = sorted({record.source_ref for record in records} | replaced_source_refs)
    store_source_records(
        engine,
        source_records_table=tables.source_records,
        source_identities_table=tables.source_identities,
        retrieval_records_table=tables.retrieval_records,
        records=records,
    )
    store_canonical_objects(
        engine,
        tables.canonical_objects,
        objects=canonical_objects_from_source_records(records),
    )
    store_entity_links(
        engine,
        tables.entity_links,
        links=entity_links_from_source_records(records),
    )
    retrieval_records = prepare_retrieval_records(
        records,
        max_words=retrieval_max_words,
        overlap_words=retrieval_overlap_words,
    )
    replace_retrieval_records_for_sources(
        engine,
        tables.retrieval_records,
        source_refs=touched_source_refs,
        records=retrieval_records,
    )
    replace_vector_index_for_retrieval_records(
        engine,
        source_refs=touched_source_refs,
        records=retrieval_records,
    )
    _store_raw_source_records(
        engine,
        tables.source_lifecycle,
        raw_store,
        records,
        delete_source_refs=replaced_source_refs,
    )
    delete_legacy_email_index_rows(
        engine,
        tables.indexing,
        source_refs=set(touched_source_refs),
    )


def _records_with_raw_refs(
    records: list[SourceRecord],
    *,
    raw_store: RawSourceStore | None,
) -> list[SourceRecord]:
    if raw_store is None:
        return records
    return [
        record if record.raw_ref else replace(record, raw_ref=record.source_ref)
        for record in records
    ]


def _apply_inactive_change(
    engine: Engine,
    tables: SourceChangeTables,
    *,
    raw_store: RawSourceStore | None,
    source_ref: str,
    state: str,
    reason: str,
    replacement_ref: str,
    duplicate_group_ref: str,
    principal: PrincipalContext,
) -> None:
    remove_source_from_retrieval(
        engine,
        emails=tables.indexing.emails,
        chunks=tables.indexing.chunks,
        audit_events=tables.audit_events,
        source_lifecycle=tables.source_lifecycle,
        raw_store=raw_store,
        source_ref=source_ref,
        state=state,
        reason=reason,
        replacement_ref=replacement_ref,
        duplicate_group_ref=duplicate_group_ref,
        principal=principal,
    )
    with engine.begin() as connection:
        connection.execute(
            update(tables.source_records)
            .where(tables.source_records.c.source_ref == source_ref)
            .values(lifecycle_state=state)
        )
        connection.execute(
            delete(tables.source_identities).where(
                tables.source_identities.c.source_ref == source_ref
            )
        )
        connection.execute(
            update(tables.canonical_objects)
            .where(tables.canonical_objects.c.object_ref == source_ref)
            .values(lifecycle_state=state)
        )
        connection.execute(
            delete(tables.entity_links).where(
                (tables.entity_links.c.source_ref == source_ref)
                | (tables.entity_links.c.object_ref == source_ref)
            )
        )
        connection.execute(
            update(tables.retrieval_records)
            .where(tables.retrieval_records.c.source_ref == source_ref)
            .values(status="inactive")
        )


def _restore_source(engine: Engine, tables: SourceChangeTables, source_ref: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            delete(tables.source_lifecycle).where(
                tables.source_lifecycle.c.source_ref == source_ref
            )
        )
        connection.execute(
            update(tables.source_records)
            .where(tables.source_records.c.source_ref == source_ref)
            .values(lifecycle_state="active")
        )
        connection.execute(
            update(tables.canonical_objects)
            .where(tables.canonical_objects.c.object_ref == source_ref)
            .values(lifecycle_state="active")
        )
        connection.execute(
            update(tables.retrieval_records)
            .where(tables.retrieval_records.c.source_ref == source_ref)
            .values(status="stale")
        )


def _source_lifecycle_state_by_ref(
    engine: Engine, source_lifecycle: Table
) -> dict[str, dict[str, str]]:
    statement = select(
        source_lifecycle.c.source_ref,
        source_lifecycle.c.state,
        source_lifecycle.c.reason,
    )
    with engine.connect() as connection:
        return {
            row["source_ref"]: {"state": row["state"], "reason": row["reason"]}
            for row in connection.execute(statement).mappings()
        }


def _record_with_existing_lifecycle(
    record: SourceRecord,
    lifecycle_state_by_ref: dict[str, dict[str, str]],
) -> SourceRecord:
    existing = lifecycle_state_by_ref.get(record.source_ref)
    if existing is None:
        return record
    return replace(record, lifecycle_state=existing["state"])


def _should_restore_from_active_import(
    record: SourceRecord,
    lifecycle_entry: dict[str, str] | None,
) -> bool:
    if lifecycle_entry is None or record.effective_lifecycle_state != "active":
        return False
    if (
        lifecycle_entry.get("state") == "restricted"
        and lifecycle_entry.get("reason") == "permission_snapshot_missing"
    ):
        return True
    return (
        lifecycle_entry.get("state") == "deleted"
        and lifecycle_entry.get("reason") == "missing_from_latest_snapshot"
    )


def _replaced_source_refs_for_records(
    engine: Engine,
    source_records: Table,
    records: list[SourceRecord],
) -> set[str]:
    source_identities = [(record.source_system, record.source_id) for record in records]
    if not source_identities:
        return set()

    new_source_refs = {record.source_ref for record in records}
    statement = select(
        source_records.c.source_ref,
        source_records.c.source_system,
        source_records.c.source_id,
    )
    with engine.connect() as connection:
        rows = [dict(row) for row in connection.execute(statement).mappings()]

    source_identity_set = set(source_identities)
    return {
        str(row["source_ref"])
        for row in rows
        if (str(row["source_system"]), str(row["source_id"])) in source_identity_set
        and row["source_ref"] not in new_source_refs
    }


def _store_raw_source_records(
    engine: Engine,
    source_lifecycle: Table,
    raw_store: RawSourceStore | None,
    records: list[SourceRecord],
    *,
    delete_source_refs: set[str],
) -> None:
    if raw_store is None:
        return
    for source_ref in delete_source_refs:
        raw_store.delete(source_ref)
    inactive_refs = inactive_source_refs(engine, source_lifecycle)
    for record in records:
        if record.source_ref not in inactive_refs and record.effective_lifecycle_state == "active":
            raw_store.put(record.source_ref, record)


def _inactive_state_for(operation: SourceChangeOperation) -> str:
    if operation == "restrict":
        return "restricted"
    if operation in {"delete", "supersede", "duplicate"}:
        return operation if operation != "delete" else "deleted"
    raise ValueError(f"{operation} is not an inactive source change")
