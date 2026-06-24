from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from sqlalchemy import delete, insert, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.source_records import SourceRecord

if TYPE_CHECKING:
    from fourok.governance.policy import PrincipalContext


def source_record_rows(engine: Engine, source_records: Table) -> list[dict[str, object]]:
    statement = select(source_records).order_by(source_records.c.source_ref)
    with engine.connect() as connection:
        return [
            _serialize_source_record_row(dict(row))
            for row in connection.execute(statement).mappings()
        ]


def source_identity_rows(engine: Engine, source_identities: Table) -> list[dict[str, object]]:
    statement = select(source_identities).order_by(
        source_identities.c.source_ref,
        source_identities.c.identity_ref,
        source_identities.c.identity_type,
    )
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def source_metadata(
    engine: Engine,
    source_records: Table,
    *,
    source_ref: str,
    principal: PrincipalContext,
    group_inheritance: dict[str, tuple[str, ...]],
) -> dict[str, object]:
    from fourok.governance.permissions import (
        decode_json_string_list,
        decode_permission_refs,
        principal_permission_refs,
    )

    statement = select(source_records).where(source_records.c.source_ref == source_ref)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()

    if row is None:
        return {"status": "not_found", "source_ref": source_ref}

    record = dict(row)
    permission_refs = decode_permission_refs(record["permission_refs"])
    if permission_refs and permission_refs.isdisjoint(
        principal_permission_refs(principal, group_inheritance)
    ):
        return {
            "status": "denied",
            "source_ref": source_ref,
            "reason": "source_permission_denied",
        }

    return {
        "status": "allowed",
        "source_ref": record["source_ref"],
        "source_system": record["source_system"],
        "source_id": record["source_id"],
        "record_type": record["record_type"],
        "source_url": record["source_url"],
        "thread_ref": record["thread_ref"],
        "attachment_refs": sorted(decode_json_string_list(record["attachment_refs"])),
        "lifecycle_state": record["lifecycle_state"],
    }


def store_source_records(
    engine: Engine,
    *,
    source_records_table: Table,
    source_identities_table: Table,
    retrieval_records_table: Table | None = None,
    records: list[SourceRecord],
) -> None:
    if not records:
        return
    records = latest_source_records(records)

    rows = []
    for record in records:
        checksum = source_record_checksum(record)
        rows.append(
            {
                "source_ref": record.source_ref,
                "source_system": record.source_system,
                "source_id": record.source_id,
                "record_type": record.record_type,
                "title": record.title,
                "retrieval_text": record.body,
                "author_ref": record.author_ref,
                "occurred_at": record.occurred_at,
                "updated_at": record.updated_at,
                "source_url": record.source_url,
                "thread_ref": record.thread_ref,
                "permission_refs": json.dumps(list(record.permission_refs)),
                "permission_snapshot_status": record.permission_snapshot_status,
                "attachment_refs": json.dumps(list(record.attachment_refs)),
                "identity_refs": json.dumps(list(record.identity_refs)),
                "lifecycle_state": record.effective_lifecycle_state,
                "checksum": checksum,
                "version": record.version or checksum,
                "metadata_json": record.metadata,
                "raw_ref": record.raw_ref,
            }
        )
    identity_rows = [
        {
            "source_ref": record.source_ref,
            "source_system": identity.source_system,
            "identity_ref": identity.identity_ref,
            "identity_type": identity.identity_type,
            "value": identity.value,
            "display_name": identity.display_name,
        }
        for record in records
        for identity in record.source_identities
    ]
    source_refs = [record.source_ref for record in records]
    source_identities = [(record.source_system, record.source_id) for record in records]
    with engine.begin() as connection:
        previous_rows = [
            dict(row)
            for row in connection.execute(
                select(
                    source_records_table.c.source_ref,
                    source_records_table.c.source_system,
                    source_records_table.c.source_id,
                    source_records_table.c.checksum,
                ).where(
                    tuple_(
                        source_records_table.c.source_system,
                        source_records_table.c.source_id,
                    ).in_(source_identities)
                )
            ).mappings()
        ]
        previous_checksums_by_ref = {row["source_ref"]: row["checksum"] for row in previous_rows}
        previous_by_source_identity = {
            (row["source_system"], row["source_id"]): row for row in previous_rows
        }
        replaced_source_refs = {
            str(row["source_ref"]) for row in previous_rows if row["source_ref"] not in source_refs
        }
        delete_source_refs = sorted({*source_refs, *replaced_source_refs})
        connection.execute(
            delete(source_records_table).where(
                source_records_table.c.source_ref.in_(delete_source_refs)
            )
        )
        connection.execute(
            delete(source_identities_table).where(
                source_identities_table.c.source_ref.in_(delete_source_refs)
            )
        )
        _upsert_rows(
            connection,
            source_records_table,
            rows,
            index_elements=["source_ref"],
        )
        if identity_rows:
            _upsert_rows(
                connection,
                source_identities_table,
                identity_rows,
                index_elements=["source_ref", "identity_ref", "identity_type"],
            )
        if retrieval_records_table is not None:
            changed_source_refs = [
                row["source_ref"]
                for row in rows
                if _source_record_row_changed(
                    row,
                    previous_checksums_by_ref=previous_checksums_by_ref,
                    previous_by_source_identity=previous_by_source_identity,
                )
            ]
            changed_source_refs.extend(replaced_source_refs)
            if changed_source_refs:
                connection.execute(
                    update(retrieval_records_table)
                    .where(retrieval_records_table.c.source_ref.in_(changed_source_refs))
                    .values(status="stale")
                )


def latest_source_records(records: list[SourceRecord]) -> list[SourceRecord]:
    selected: list[SourceRecord] = []
    seen_source_refs: set[str] = set()
    seen_source_identities: set[tuple[str, str]] = set()
    for record in reversed(records):
        source_identity = (record.source_system, record.source_id)
        if record.source_ref in seen_source_refs or source_identity in seen_source_identities:
            continue
        seen_source_refs.add(record.source_ref)
        seen_source_identities.add(source_identity)
        selected.append(record)
    return list(reversed(selected))


def _upsert_rows(
    connection,
    table: Table,
    rows: Sequence[Mapping[str, object]],
    *,
    index_elements: list[str],
) -> None:
    if not rows:
        return
    dialect_name = connection.dialect.name
    if dialect_name == "postgresql":
        statement = postgresql_insert(table).values(rows)
    elif dialect_name == "sqlite":
        statement = sqlite_insert(table).values(rows)
    else:
        connection.execute(insert(table), rows)
        return

    excluded = statement.excluded
    update_columns = {
        column.name: getattr(excluded, column.name)
        for column in table.columns
        if column.name not in index_elements
    }
    connection.execute(
        statement.on_conflict_do_update(
            index_elements=[table.c[name] for name in index_elements],
            set_=update_columns,
        )
    )


def _record_checksum(record: SourceRecord) -> str:
    return source_record_checksum(record)


def _serialize_source_record_row(row: dict[str, object]) -> dict[str, object]:
    row["metadata_json"] = _json_object_string(row["metadata_json"])
    return row


def _json_object_string(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return "{}"


def _source_record_row_changed(
    row: dict[str, object],
    *,
    previous_checksums_by_ref: dict[str, str],
    previous_by_source_identity: dict[tuple[str, str], dict[str, object]],
) -> bool:
    source_ref = str(row["source_ref"])
    if source_ref in previous_checksums_by_ref:
        return previous_checksums_by_ref[source_ref] != row["checksum"]

    previous = previous_by_source_identity.get((str(row["source_system"]), str(row["source_id"])))
    return previous is not None and previous["checksum"] != row["checksum"]


def source_record_checksum(record: SourceRecord) -> str:
    if record.checksum:
        return record.checksum

    payload = {
        "source_system": record.source_system,
        "source_id": record.source_id,
        "record_type": record.record_type,
        "title": record.title,
        "body": record.body,
        "occurred_at": record.occurred_at,
        "updated_at": record.updated_at,
        "author_ref": record.author_ref,
        "source_url": record.source_url,
        "thread_ref": record.thread_ref,
        "permission_refs": list(record.permission_refs),
        "permission_snapshot_status": record.permission_snapshot_status,
        "attachment_refs": list(record.attachment_refs),
        "identity_refs": list(record.identity_refs),
        "lifecycle_state": record.lifecycle_state,
        "metadata": record.metadata,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def denied_source_refs(
    engine: Engine,
    source_records: Table,
    *,
    principal: PrincipalContext,
    group_inheritance: dict[str, tuple[str, ...]],
) -> set[str]:
    from fourok.governance.permissions import decode_permission_refs, principal_permission_refs

    statement = select(
        source_records.c.source_ref,
        source_records.c.permission_refs,
    )
    denied_refs = set()
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings()
        for row in rows:
            permission_refs = decode_permission_refs(row["permission_refs"])
            if permission_refs and permission_refs.isdisjoint(
                principal_permission_refs(principal, group_inheritance)
            ):
                denied_refs.add(row["source_ref"])
    return denied_refs
