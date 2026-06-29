from pathlib import Path

from sqlalchemy import MetaData
from sqlalchemy.dialects import postgresql

from fourok.etl.extract.email_parser import load_email_dir
from fourok.governance import GovernedContext
from fourok.retrieval.search import postgres_source_record_search_statement
from fourok.storage.models import RetrievalRecordRow, SourceRecordRow, table_for_model

FIXTURES = Path(__file__).parents[1] / "fixtures" / "emails"


def build_context() -> GovernedContext:
    context = GovernedContext()
    context.ingest(load_email_dir(FIXTURES))
    return context


def test_loads_all_synthetic_email_fixtures() -> None:
    messages = load_email_dir(FIXTURES)

    assert len(messages) == 14
    assert {message.source_ref for message in messages} >= {
        "local_email:0001-cancellation-final-invoice",
        "local_email:0011-termination-confirmed",
    }


def test_keyword_search_returns_required_result_fields() -> None:
    result = build_context().search_context("refund cancellation payment", limit=1).results[0]

    assert result.source_ref
    assert result.subject
    assert result.date
    assert result.snippet


def test_golden_keyword_queries_return_expected_sources() -> None:
    context = build_context()

    golden_queries = {
        "refund cancellation payment": "local_email:0002-refund-bank-transfer",
        "account termination final invoice": "local_email:0011-termination-confirmed",
        "payment failed March invoice": "local_email:0004-payment-failed",
        "data export workspace archive": "local_email:0009-data-export",
        "upgrade additional seats priority support": "local_email:0010-upgrade-plan",
    }

    for query, expected_source_ref in golden_queries.items():
        results = context.search_context(query, limit=3).results
        assert [result.source_ref for result in results]
        assert expected_source_ref in [result.source_ref for result in results]


def test_postgres_source_record_search_statement_uses_ranked_retrieval_unit_match() -> None:
    metadata = MetaData()
    source_records = table_for_model(metadata, SourceRecordRow.__table__)
    retrieval_records = table_for_model(metadata, RetrievalRecordRow.__table__)

    statement = postgres_source_record_search_statement(
        source_records,
        retrieval_records,
        "refund cancellation payment",
        limit=3,
    )
    compiled = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "to_tsvector" in compiled
    assert "plainto_tsquery" in compiled
    assert "@@" in compiled
    assert "ts_rank" in compiled
    assert "ORDER BY ts_rank" in compiled
    assert "JOIN source_records" in compiled
    assert "retrieval_records.status = 'current'" in compiled
    assert "source_records.lifecycle_state = 'active'" in compiled
    assert "DESC, source_records.occurred_at, source_records.source_ref" in compiled
    assert "LIMIT 3" in compiled
