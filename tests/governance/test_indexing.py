import inspect

from fourok.etl.extract.email_parser import EmailMessage
from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.indexing import (
    IndexingTables,
    email_compatibility_chunk_rows,
    ingest_messages,
    raw_source_refs,
    replace_messages,
)
from fourok.governance.state import create_governed_context_state


def indexing_tables(state) -> IndexingTables:
    return IndexingTables(
        emails=state.emails,
        chunks=state.chunks,
    )


def test_ingest_messages_indexes_raw_text_without_token_sources_and_raw_refs(tmp_path) -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=tmp_path / "raw",
    )
    message = EmailMessage(
        source_ref="local_email:active",
        subject="Refund for customer@example.com",
        from_address="ops@example.com",
        to_addresses=["finance@example.com"],
        date="2001-01-01",
        body="Send refund to DE89370400440532013000.",
    )
    inactive = EmailMessage(
        source_ref="local_email:restricted",
        subject="Restricted customer@example.com",
        from_address="ops@example.com",
        to_addresses=[],
        date="2001-01-02",
        body="This should not be indexed.",
    )

    ingest_messages(
        state.engine,
        indexing_tables(state),
        messages=[message, inactive],
        inactive_source_refs={"local_email:restricted"},
        raw_store=state.raw_store,
    )

    chunks = email_compatibility_chunk_rows(state.engine, state.chunks)
    serialized_chunks = " ".join(str(chunk) for chunk in chunks)
    assert "customer@example.com" in serialized_chunks
    assert "DE89370400440532013000" in serialized_chunks
    assert "EMAIL_" not in serialized_chunks
    assert "BANK_ACCOUNT_" not in serialized_chunks
    assert {row["source_ref"] for row in chunks} == {"local_email:active"}
    assert raw_source_refs(state.raw_store) == ["local_email:active"]


def test_replace_messages_replaces_touched_sources_without_tokenizing() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    tables = indexing_tables(state)
    first = EmailMessage(
        source_ref="local_email:replace",
        subject="Old refund",
        from_address="ops@example.com",
        to_addresses=[],
        date="2001-01-01",
        body="Old IBAN DE89370400440532013000 should disappear.",
    )
    retained = EmailMessage(
        source_ref="local_email:retained",
        subject="Retained refund",
        from_address="ops@example.com",
        to_addresses=[],
        date="2001-01-02",
        body="Retain contact retained@example.com.",
    )
    replacement = EmailMessage(
        source_ref="local_email:replace",
        subject="New refund",
        from_address="ops@example.com",
        to_addresses=[],
        date="2001-01-03",
        body="New contact replacement@example.com.",
    )

    ingest_messages(
        state.engine,
        tables,
        messages=[first, retained],
        inactive_source_refs=set(),
        raw_store=None,
    )
    replace_messages(
        state.engine,
        tables,
        messages=[replacement],
        inactive_source_refs=set(),
        raw_store=None,
    )

    chunks = email_compatibility_chunk_rows(state.engine, state.chunks)
    assert {row["source_ref"] for row in chunks} == {
        "local_email:replace",
        "local_email:retained",
    }
    serialized_chunks = " ".join(str(chunk) for chunk in chunks)
    assert "Old IBAN" not in serialized_chunks
    assert "New contact" in serialized_chunks
    assert "replacement@example.com" in serialized_chunks
    assert "retained@example.com" in serialized_chunks


def test_legacy_message_indexing_does_not_mutate_retrieval_vector_index() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:vector",
                source_system="linear",
                source_id="vector",
                record_type="work_item",
                title="Vector owner",
                body="Retrieval vector ownership marker.",
            )
        ]
    )
    vector_index = context.build_vector_index()
    legacy_tables = IndexingTables(emails=context._emails, chunks=context._chunks)

    ingest_messages(
        context._engine,
        legacy_tables,
        messages=[
            EmailMessage(
                source_ref="local_email:legacy",
                subject="Legacy",
                from_address="ops@example.com",
                to_addresses=[],
                date="2001-01-01",
                body="legacy email marker",
            )
        ],
        inactive_source_refs=set(),
        raw_store=None,
    )

    assert [
        result.source_ref for result in vector_index.search("retrieval ownership marker", limit=1)
    ] == ["linear:issue:vector"]


def test_active_indexing_api_does_not_accept_pii_detector() -> None:
    assert "pii_detector" not in inspect.signature(ingest_messages).parameters
    assert "pii_detector" not in inspect.signature(replace_messages).parameters


def test_active_indexing_tables_do_not_require_token_tables() -> None:
    fields = set(IndexingTables.__dataclass_fields__)

    assert fields == {"emails", "chunks"}
