import os
from pathlib import Path
from uuid import uuid4

import pytest

from fourok.etl.extract.email_parser import EmailMessage, load_email_dir
from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext
from fourok.retrieval.evaluation import compare_retrieval_methods, load_retrieval_eval_cases

FIXTURES = Path(__file__).parents[2] / "fixtures"
EMAILS = FIXTURES / "emails"
RETRIEVAL_EVAL = FIXTURES / "retrieval_eval" / "customer_context_queries.json"


@pytest.mark.skipif(
    not os.environ.get("FOUR_OK_TEST_DATABASE_URL"),
    reason="set FOUR_OK_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_full_text_search_matches_expected_email() -> None:
    context = GovernedContext(database_url=os.environ["FOUR_OK_TEST_DATABASE_URL"])
    context.ingest(load_email_dir(EMAILS))

    response = context.search_context("refund cancellation payment", limit=3)

    assert [result.source_ref for result in response.results][:1] == [
        "local_email:0002-refund-bank-transfer"
    ]


@pytest.mark.skipif(
    not os.environ.get("FOUR_OK_TEST_DATABASE_URL"),
    reason="set FOUR_OK_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_pgvector_retrieval_quality_loop_runs() -> None:
    context = GovernedContext(database_url=os.environ["FOUR_OK_TEST_DATABASE_URL"])
    context.ingest(load_email_dir(EMAILS))
    vector_index = context.build_vector_index()
    cases = load_retrieval_eval_cases(RETRIEVAL_EVAL)

    metrics = compare_retrieval_methods(context, vector_index, cases)

    assert {metric.method for metric in metrics} == {"full_text", "vector", "hybrid"}
    assert next(metric for metric in metrics if metric.method == "vector").top3_hits >= 3


@pytest.mark.skipif(
    not os.environ.get("FOUR_OK_TEST_DATABASE_URL"),
    reason="set FOUR_OK_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_source_lifecycle_tombstone_survives_reingestion() -> None:
    context = GovernedContext(database_url=os.environ["FOUR_OK_TEST_DATABASE_URL"])
    source_ref = f"local_email:lifecycle-{uuid4()}"
    message = EmailMessage(
        source_ref=source_ref,
        subject="Lifecycle refund marker",
        from_address="ops@example.com",
        to_addresses=["finance@example.com"],
        date="2026-05-23",
        body=(
            "Lifecycle unique refund marker for BANK transfer. "
            "Contact anna.lifecycle@example.com for details."
        ),
    )
    context.ingest([message])
    context.build_vector_index()

    assert source_ref in [
        result.source_ref for result in context.search_context("lifecycle refund marker").results
    ]

    context.delete_source(source_ref, reason="postgres_lifecycle_test")
    context.ingest([message])

    assert source_ref not in [
        result.source_ref
        for result in context.search_context("lifecycle refund marker", limit=5).results
    ]
    assert source_ref not in {
        row["source_ref"]
        for row in context.retrieval_units()
        if "lifecycle refund marker" in row["prepared_text"]
    }


@pytest.mark.skipif(
    not os.environ.get("FOUR_OK_TEST_DATABASE_URL"),
    reason="set FOUR_OK_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_source_record_metadata_round_trip() -> None:
    context = GovernedContext(database_url=os.environ["FOUR_OK_TEST_DATABASE_URL"])
    source_id = f"source-record-{uuid4()}"
    source_ref = f"singer:email_messages:{source_id}"

    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=source_ref,
                source_system="gmail",
                source_id=source_id,
                record_type="email",
                title="Postgres source record metadata",
                body="postgres source metadata marker",
                occurred_at="2026-05-23",
                source_url=f"https://mail.google.com/mail/u/0/#inbox/{source_id}",
                thread_ref="thread-postgres",
                permission_refs=("group:finance",),
                attachment_refs=("attachment:one",),
                identity_refs=("gmail:email:owner@example.com",),
                source_identities=(
                    SourceIdentity(
                        source_system="gmail",
                        identity_ref="gmail:email:owner@example.com",
                        identity_type="sender",
                        value="owner@example.com",
                        display_name="Owner Example",
                    ),
                ),
            )
        ]
    )

    stored = next(
        record for record in context.source_records() if record["source_ref"] == source_ref
    )
    assert stored["source_system"] == "gmail"
    assert stored["thread_ref"] == "thread-postgres"
    assert stored["permission_refs"] == '["group:finance"]'
    assert stored["attachment_refs"] == '["attachment:one"]'
    assert stored["identity_refs"] == '["gmail:email:owner@example.com"]'
    assert any(
        identity["source_ref"] == source_ref
        and identity["identity_ref"] == "gmail:email:owner@example.com"
        and identity["identity_type"] == "sender"
        for identity in context.source_identities()
    )
    assert source_ref in [
        result.source_ref
        for result in context.search_context(
            "postgres source metadata",
            principal=PrincipalContext(
                human_id="human:finance-1",
                agent_id="agent:context-helper",
                roles=("finance",),
            ),
        ).results
    ]


@pytest.mark.skipif(
    not os.environ.get("FOUR_OK_TEST_DATABASE_URL"),
    reason="set FOUR_OK_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_incremental_source_record_update_replaces_only_touched_record() -> None:
    context = GovernedContext(database_url=os.environ["FOUR_OK_TEST_DATABASE_URL"])
    stable_id = f"stable-{uuid4()}"
    update_id = f"update-{uuid4()}"
    stable_ref = f"singer:email_messages:{stable_id}"
    update_ref = f"singer:email_messages:{update_id}"

    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=stable_ref,
                source_system="gmail",
                source_id=stable_id,
                record_type="email",
                title="Stable postgres incremental",
                body="pgstablemarker searchable",
            ),
            SourceRecord(
                source_ref=update_ref,
                source_system="gmail",
                source_id=update_id,
                record_type="email",
                title="Update postgres incremental",
                body="pgoldmarker searchable",
            ),
        ]
    )
    vector_index = context.build_vector_index()

    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=update_ref,
                source_system="gmail",
                source_id=update_id,
                record_type="email",
                title="Update postgres incremental",
                body="pgnewmarker searchable",
            )
        ]
    )

    assert stable_ref in [
        result.source_ref for result in context.search_context("pgstablemarker").results
    ]
    assert context.search_context("pgoldmarker").results == []
    assert [result.source_ref for result in context.search_context("pgnewmarker").results] == [
        update_ref
    ]
    assert [result.source_ref for result in vector_index.search("pgnewmarker", limit=1)] == [
        update_ref
    ]


@pytest.mark.skipif(
    not os.environ.get("FOUR_OK_TEST_DATABASE_URL"),
    reason="set FOUR_OK_TEST_DATABASE_URL to run PostgreSQL integration tests",
)
def test_postgres_source_permission_refs_filter_search() -> None:
    context = GovernedContext(database_url=os.environ["FOUR_OK_TEST_DATABASE_URL"])
    suffix = str(uuid4())
    finance_ref = f"singer:email_messages:finance-{suffix}"
    support_ref = f"singer:email_messages:support-{suffix}"
    marker = f"pgpermission{suffix.replace('-', '')}"
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=finance_ref,
                source_system="gmail",
                source_id=f"finance-{suffix}",
                record_type="email",
                title="Finance permission",
                body=f"{marker} finance access",
                permission_refs=("group:finance",),
            ),
            SourceRecord(
                source_ref=support_ref,
                source_system="gmail",
                source_id=f"support-{suffix}",
                record_type="email",
                title="Support permission",
                body=f"{marker} support access",
                permission_refs=("group:support",),
            ),
        ]
    )

    finance_response = context.search_context(
        marker,
        principal=PrincipalContext(
            human_id="human:finance-1",
            agent_id="agent:context-helper",
            roles=("finance",),
        ),
        limit=5,
    )

    assert [result.source_ref for result in finance_response.results] == [finance_ref]
