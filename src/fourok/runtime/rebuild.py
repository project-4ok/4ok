from __future__ import annotations

import json
from typing import Any, Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.etl.load.context_objects import (
    canonical_objects_from_source_records,
    entity_links_from_source_records,
    store_canonical_objects,
    store_entity_links,
)
from fourok.etl.load.retrieval_records import (
    prepare_retrieval_records,
    replace_vector_index_for_retrieval_records,
    store_retrieval_records,
)
from fourok.etl.load.source_metadata import source_identity_rows
from fourok.governance.permissions import decode_json_string_list
from fourok.observability import critical_span, set_safe_span_attributes
from fourok.storage.config import RetrievalConfig


class RebuildState(Protocol):
    @property
    def engine(self) -> Engine: ...

    @property
    def source_records(self) -> Table: ...

    @property
    def source_identities(self) -> Table: ...

    @property
    def canonical_objects(self) -> Table: ...

    @property
    def entity_links(self) -> Table: ...

    @property
    def retrieval_records(self) -> Table: ...


def rebuild_context_objects(state: RebuildState) -> dict[str, int | str]:
    records = _source_records_from_state(state)
    canonical_objects = canonical_objects_from_source_records(records)
    entity_links = entity_links_from_source_records(records)
    deleted_canonical_objects = _delete_all_rows(state, state.canonical_objects)
    deleted_entity_links = _delete_all_rows(state, state.entity_links)
    store_canonical_objects(
        state.engine,
        state.canonical_objects,
        objects=canonical_objects,
    )
    store_entity_links(
        state.engine,
        state.entity_links,
        links=entity_links,
    )
    return {
        "status": "completed",
        "source_records": len(records),
        "canonical_objects_deleted": deleted_canonical_objects,
        "canonical_objects_created": len(canonical_objects),
        "entity_links_deleted": deleted_entity_links,
        "entity_links_created": len(entity_links),
    }


def rebuild_retrieval_units(
    state: RebuildState,
    *,
    retrieval_config: RetrievalConfig,
) -> dict[str, int | str]:
    with critical_span(
        "fourok.retrieval.rebuild",
        status_attribute="fourok.retrieval.status",
    ) as span:
        records = _source_records_from_state(state)
        retrieval_units = prepare_retrieval_records(
            records,
            max_words=retrieval_config.max_words,
            overlap_words=retrieval_config.overlap_words,
        )
        deleted_count = _delete_all_rows(state, state.retrieval_records)
        store_retrieval_records(
            state.engine,
            state.retrieval_records,
            records=retrieval_units,
        )
        source_refs = [record.source_ref for record in records]
        replace_vector_index_for_retrieval_records(
            state.engine,
            source_refs=source_refs,
            records=retrieval_units,
        )
        embeddings_indexed = sum(1 for record in retrieval_units if record.status == "current")
        report = {
            "status": "completed",
            "source_records": len(records),
            "retrieval_units_deleted": deleted_count,
            "retrieval_units_created": len(retrieval_units),
            "embeddings_indexed": embeddings_indexed,
        }
        set_safe_span_attributes(
            span,
            {
                "fourok.retrieval.status": "succeeded",
                "fourok.source_record.count": len(records),
                "fourok.retrieval.unit_count": len(retrieval_units),
                "fourok.retrieval.deleted_count": deleted_count,
                "fourok.embedding.indexed_count": embeddings_indexed,
            },
        )
        return report


def _source_records_from_state(state: RebuildState) -> list[SourceRecord]:
    statement = select(state.source_records).order_by(state.source_records.c.source_ref)
    with state.engine.connect() as connection:
        rows = [dict(row) for row in connection.execute(statement).mappings()]
    identities_by_source_ref = _source_identities_by_source_ref(state)
    return [
        _source_record_from_row(
            row,
            source_identities=tuple(identities_by_source_ref.get(str(row["source_ref"]), ())),
        )
        for row in rows
    ]


def _source_record_from_row(
    row: dict[str, Any],
    *,
    source_identities: tuple[SourceIdentity, ...] = (),
) -> SourceRecord:
    return SourceRecord(
        source_ref=str(row["source_ref"]),
        source_system=str(row["source_system"]),
        source_id=str(row["source_id"]),
        record_type=str(row["record_type"]),
        title=str(row["title"]),
        body=str(row["retrieval_text"]),
        occurred_at=str(row["occurred_at"]),
        updated_at=str(row["updated_at"]),
        author_ref=str(row["author_ref"]),
        source_url=str(row["source_url"]),
        thread_ref=str(row["thread_ref"]),
        permission_refs=tuple(decode_json_string_list(row["permission_refs"])),
        permission_snapshot_status=str(row["permission_snapshot_status"]),
        attachment_refs=tuple(decode_json_string_list(row["attachment_refs"])),
        identity_refs=tuple(decode_json_string_list(row["identity_refs"])),
        lifecycle_state=str(row["lifecycle_state"]),
        checksum=str(row["checksum"]),
        version=str(row["version"]),
        metadata=_json_object(row["metadata_json"]),
        raw_ref=str(row["raw_ref"]),
        source_identities=source_identities,
    )


def _source_identities_by_source_ref(
    state: RebuildState,
) -> dict[str, list[SourceIdentity]]:
    identities: dict[str, list[SourceIdentity]] = {}
    for row in source_identity_rows(state.engine, state.source_identities):
        source_ref = str(row["source_ref"])
        identities.setdefault(source_ref, []).append(
            SourceIdentity(
                source_system=str(row["source_system"]),
                identity_ref=str(row["identity_ref"]),
                identity_type=str(row["identity_type"]),
                value=str(row["value"]),
                display_name=str(row["display_name"]),
            )
        )
    return identities


def _delete_all_rows(state: RebuildState, table: Table) -> int:
    count_statement = select(func.count()).select_from(table)
    with state.engine.begin() as connection:
        count = int(connection.execute(count_statement).scalar_one())
        connection.execute(delete(table))
    return count


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    return {}
