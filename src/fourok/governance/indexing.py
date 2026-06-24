from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.email_parser import EmailMessage
from fourok.retrieval.embeddings import chunk_text


class RawSourceStore(Protocol):
    def put(self, source_ref: str, payload: object) -> None: ...

    def refs(self) -> list[str]: ...


@dataclass(frozen=True)
class IndexingTables:
    emails: Table
    chunks: Table


def ingest_messages(
    engine: Engine,
    tables: IndexingTables,
    *,
    messages: list[EmailMessage],
    inactive_source_refs: set[str],
    raw_store: RawSourceStore | None,
) -> None:
    store_raw_messages(raw_store, messages, inactive_source_refs=inactive_source_refs)
    email_rows, chunk_rows = indexed_rows_for_messages(
        engine,
        tables,
        messages=messages,
        inactive_source_refs=inactive_source_refs,
    )

    with engine.begin() as connection:
        connection.execute(delete(tables.emails))
        connection.execute(delete(tables.chunks))
        if email_rows:
            connection.execute(insert(tables.emails), email_rows)
        if chunk_rows:
            connection.execute(insert(tables.chunks), chunk_rows)


def replace_messages(
    engine: Engine,
    tables: IndexingTables,
    *,
    messages: list[EmailMessage],
    inactive_source_refs: set[str],
    raw_store: RawSourceStore | None,
    delete_source_refs: set[str] | None = None,
) -> None:
    source_refs = sorted(
        {message.source_ref for message in messages} | (delete_source_refs or set())
    )
    if not source_refs:
        return

    store_raw_messages(raw_store, messages, inactive_source_refs=inactive_source_refs)
    email_rows, chunk_rows = indexed_rows_for_messages(
        engine,
        tables,
        messages=messages,
        inactive_source_refs=inactive_source_refs,
    )
    with engine.begin() as connection:
        connection.execute(delete(tables.emails).where(tables.emails.c.source_ref.in_(source_refs)))
        connection.execute(delete(tables.chunks).where(tables.chunks.c.source_ref.in_(source_refs)))
        if email_rows:
            connection.execute(insert(tables.emails), email_rows)
        if chunk_rows:
            connection.execute(insert(tables.chunks), chunk_rows)


def delete_legacy_email_index_rows(
    engine: Engine,
    tables: IndexingTables,
    *,
    source_refs: set[str],
) -> None:
    if not source_refs:
        return
    with engine.begin() as connection:
        connection.execute(delete(tables.emails).where(tables.emails.c.source_ref.in_(source_refs)))
        connection.execute(delete(tables.chunks).where(tables.chunks.c.source_ref.in_(source_refs)))


def email_compatibility_chunk_rows(engine: Engine, chunks: Table) -> list[dict[str, object]]:
    statement = select(chunks).order_by(chunks.c.source_ref, chunks.c.chunk_index)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def raw_source_refs(raw_store: RawSourceStore | None) -> list[str]:
    if raw_store is None:
        return []
    return raw_store.refs()


def store_raw_messages(
    raw_store: RawSourceStore | None,
    messages: list[EmailMessage],
    *,
    inactive_source_refs: set[str],
) -> None:
    if raw_store is None:
        return
    for message in messages:
        if message.source_ref not in inactive_source_refs:
            raw_store.put(message.source_ref, message)


def indexed_rows_for_messages(
    engine: Engine,
    tables: IndexingTables,
    *,
    messages: list[EmailMessage],
    inactive_source_refs: set[str],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    email_rows = []
    chunk_rows = []
    for message in messages:
        if message.source_ref in inactive_source_refs:
            continue

        sanitized_subject = message.subject
        sanitized_body = message.body
        email_rows.append(
            {
                "source_ref": message.source_ref,
                "subject": sanitized_subject,
                "body": sanitized_body,
                "date": message.date,
            }
        )
        chunks = chunk_text(sanitized_body) or chunk_text(sanitized_subject)
        chunk_rows.extend(
            {
                "source_ref": message.source_ref,
                "chunk_index": chunk.chunk_index,
                "subject": sanitized_subject,
                "body": chunk.text,
                "date": message.date,
            }
            for chunk in chunks
        )

    return email_rows, chunk_rows
