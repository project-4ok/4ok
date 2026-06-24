from __future__ import annotations

from dataclasses import dataclass

from opentelemetry import trace
from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from gcb.etl.extract.source_records import SourceRecord
from gcb.etl.load.source_metadata import source_record_checksum
from gcb.observability import record_counter, record_histogram
from gcb.retrieval.embeddings import chunk_text
from gcb.retrieval.vector_search import ChunkVectorIndex

DEFAULT_RETRIEVAL_MAX_WORDS = 900
DEFAULT_RETRIEVAL_OVERLAP_WORDS = 100


@dataclass(frozen=True)
class RetrievalRecord:
    retrieval_ref: str
    source_ref: str
    unit_index: int
    start_offset: int
    end_offset: int
    index_kind: str
    status: str
    source_checksum: str
    prepared_text: str
    updated_at: str = ""


def retrieval_record_rows(engine: Engine, retrieval_records: Table) -> list[dict[str, object]]:
    statement = select(retrieval_records).order_by(retrieval_records.c.retrieval_ref)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def store_retrieval_records(
    engine: Engine,
    retrieval_records: Table,
    *,
    records: list[RetrievalRecord],
) -> None:
    if not records:
        return

    retrieval_refs = [record.retrieval_ref for record in records]
    rows = [
        {
            "retrieval_ref": record.retrieval_ref,
            "source_ref": record.source_ref,
            "unit_index": record.unit_index,
            "start_offset": record.start_offset,
            "end_offset": record.end_offset,
            "index_kind": record.index_kind,
            "status": record.status,
            "source_checksum": record.source_checksum,
            "prepared_text": record.prepared_text,
            "updated_at": record.updated_at,
        }
        for record in records
    ]
    with engine.begin() as connection:
        connection.execute(
            delete(retrieval_records).where(retrieval_records.c.retrieval_ref.in_(retrieval_refs))
        )
        connection.execute(insert(retrieval_records), rows)


def prepare_retrieval_records(
    records: list[SourceRecord],
    *,
    max_words: int = DEFAULT_RETRIEVAL_MAX_WORDS,
    overlap_words: int = DEFAULT_RETRIEVAL_OVERLAP_WORDS,
) -> list[RetrievalRecord]:
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("gcb.retrieval.prepare") as span:
        retrieval_records = _prepare_retrieval_records(
            records,
            max_words=max_words,
            overlap_words=overlap_words,
        )
        span.set_attribute("gcb.source_record.count", len(records))
        span.set_attribute("gcb.retrieval.unit_count", len(retrieval_records))
        span.set_attribute("gcb.retrieval.max_words", max_words)
        span.set_attribute("gcb.retrieval.overlap_words", overlap_words)
        record_counter("gcb_retrieval_prepare_total")
        record_histogram("gcb_source_records_prepared", len(records))
        record_histogram("gcb_retrieval_units", len(retrieval_records))
        return retrieval_records


def _prepare_retrieval_records(
    records: list[SourceRecord],
    *,
    max_words: int,
    overlap_words: int,
) -> list[RetrievalRecord]:
    retrieval_records: list[RetrievalRecord] = []
    for source_record in records:
        if source_record.effective_lifecycle_state != "active":
            continue
        checksum = source_record_checksum(source_record)
        text = _retrieval_text(source_record)
        chunks = chunk_text(text, max_words=max_words, overlap_words=overlap_words)
        for chunk in chunks:
            start_offset, end_offset = _chunk_offsets(text, chunk.text)
            retrieval_records.append(
                RetrievalRecord(
                    retrieval_ref=(
                        f"retrieval:{source_record.source_ref}:{chunk.chunk_index:04d}:full_text"
                    ),
                    source_ref=source_record.source_ref,
                    unit_index=chunk.chunk_index,
                    start_offset=start_offset,
                    end_offset=end_offset,
                    index_kind="full_text",
                    status="current",
                    source_checksum=checksum,
                    prepared_text=chunk.text,
                )
            )
    return retrieval_records


def replace_retrieval_records_for_sources(
    engine: Engine,
    retrieval_records: Table,
    *,
    source_refs: list[str],
    records: list[RetrievalRecord],
) -> None:
    if not source_refs:
        return
    rows = [
        {
            "retrieval_ref": record.retrieval_ref,
            "source_ref": record.source_ref,
            "unit_index": record.unit_index,
            "start_offset": record.start_offset,
            "end_offset": record.end_offset,
            "index_kind": record.index_kind,
            "status": record.status,
            "source_checksum": record.source_checksum,
            "prepared_text": record.prepared_text,
            "updated_at": record.updated_at,
        }
        for record in records
    ]
    with engine.begin() as connection:
        connection.execute(
            delete(retrieval_records).where(retrieval_records.c.source_ref.in_(source_refs))
        )
        if rows:
            connection.execute(insert(retrieval_records), rows)


def replace_vector_index_for_retrieval_records(
    engine: Engine,
    *,
    source_refs: list[str],
    records: list[RetrievalRecord],
) -> None:
    if not source_refs:
        return
    chunks = [
        {
            "source_ref": record.source_ref,
            "chunk_index": record.unit_index,
            "body": record.prepared_text,
        }
        for record in records
        if record.status == "current"
    ]
    ChunkVectorIndex(engine).replace(source_refs, chunks)


def _retrieval_text(record: SourceRecord) -> str:
    attachment_text = "\n\n".join(
        "\n".join(part for part in [attachment.title, attachment.text] if part)
        for attachment in record.attachments
        if attachment.text
    )
    parts = [record.title.strip(), record.body.strip(), attachment_text.strip()]
    return "\n\n".join(part for part in parts if part)


def _chunk_offsets(text: str, chunk: str) -> tuple[int, int]:
    start = text.find(chunk)
    if start < 0:
        return 0, len(chunk)
    return start, start + len(chunk)
