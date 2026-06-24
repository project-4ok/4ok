import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select

import fourok.governance
from fourok.etl.extract.email_parser import load_email_dir
from fourok.etl.extract.gmail_singer import gmail_message_to_source_record
from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext

FIXTURES = Path(__file__).parents[2] / "fixtures" / "emails"
RAW_IBAN = "DE89370400440532013000"
RAW_EMAIL = "anna.refunds@example.com"
RAW_PHONE = "+49 30 12345678"
RAW_TRICKY_EMAIL = "finance+refunds@example.com"
RAW_TRICKY_PHONE = "+1 (415) 555-0134"
RAW_PAYMENT_REF = "PMT-20260421"
RAW_SPACED_IBAN = "DE89 3704 0044 0532 0130 00"
RAW_GMAIL_PERSON = "Alicia Example"
RAW_GMAIL_EMAIL = "alicia.audit@example.com"
RAW_GMAIL_PHONE = "+1 (415) 555-0199"
RAW_GMAIL_IBAN = "DE44500105175407324931"


def build_context() -> GovernedContext:
    context = GovernedContext()
    context.ingest(load_email_dir(FIXTURES))
    return context


def adapted_gmail_record():
    return gmail_message_to_source_record(
        {
            "id": "msg-pii-pilot",
            "threadId": "thread-pii-pilot",
            "internalDate": "1716998096000",
            "snippet": "Synthetic pilot summary for Falcon refund review",
            "permissionSnapshotStatus": "current",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": f"Falcon review for {RAW_GMAIL_EMAIL}"},
                    {
                        "name": "From",
                        "value": f"{RAW_GMAIL_PERSON} <{RAW_GMAIL_EMAIL}>",
                    },
                    {"name": "To", "value": "ops@example.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {
                            "data": (
                                "Q2FsbCArMSAoNDE1KSA1NTUtMDE5OSBhYm91dCBGYWxjb24gcmVmdW5kIGFuZCB1"
                                "c2UgSUJBTiBERTQ0NTAwMTA1MTc1NDA3MzI0OTMxLg=="
                            )
                        },
                    }
                ],
            },
        }
    )


def test_search_indexes_raw_text_and_returns_no_tokens() -> None:
    context = build_context()

    response = context.search_context("refund iban canceled account", limit=3)

    serialized = str(response)
    assert "BANK_ACCOUNT_" not in serialized
    assert not hasattr(response, "sensitive_tokens")
    assert any(result.source_ref == "local_email:0013-refund-iban" for result in response.results)
    raw_response = context.search_context(RAW_IBAN, limit=3)
    assert [result.source_ref for result in raw_response.results] == [
        "local_email:0013-refund-iban"
    ]


def test_email_ingest_populates_source_records_and_retrieval_units() -> None:
    context = build_context()

    source_refs = {row["source_ref"] for row in context.source_records()}
    retrieval_source_refs = {row["source_ref"] for row in context.retrieval_units()}

    assert "local_email:0013-refund-iban" in source_refs
    assert "local_email:0013-refund-iban" in retrieval_source_refs
    assert all(row["record_type"] == "email" for row in context.source_records())
    assert "BANK_ACCOUNT_" not in str(context.retrieval_units())


def test_search_uses_retrieval_units_without_legacy_email_chunks() -> None:
    context = build_context()

    with context._engine.begin() as connection:
        connection.execute(delete(context._chunks))

    assert not hasattr(context, "email_compatibility_chunks")
    assert [result.source_ref for result in context.search_context(RAW_IBAN, limit=3).results] == [
        "local_email:0013-refund-iban"
    ]


def test_search_context_does_not_return_legacy_token_metadata() -> None:
    context = GovernedContext()
    legacy_token = "IBAN_DEFERRED_TOKEN"
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:TOKEN-1",
                source_system="linear",
                source_id="TOKEN-1",
                record_type="work_item",
                title="Legacy token reference",
                body=f"A legacy note mentions {legacy_token} as plain internal text.",
            )
        ]
    )

    legacy_token_response = context.search_context("legacy token reference", limit=3)
    assert not hasattr(legacy_token_response, "sensitive_tokens")
    assert legacy_token_response.results[0].source_ref == "linear:issue:TOKEN-1"


def test_governed_context_active_api_does_not_expose_reveal() -> None:
    context = GovernedContext()

    assert not hasattr(context, "request_reveal")


def test_governed_context_active_api_does_not_accept_pii_detector() -> None:
    assert "pii_detector" not in inspect.signature(GovernedContext).parameters


def test_governed_context_active_api_does_not_expose_token_sources() -> None:
    context = GovernedContext()

    assert not hasattr(context, "token_sources")
    assert not hasattr(context, "_token_store")
    assert not hasattr(context, "_token_sources")
    assert not hasattr(context, "sanitized_chunks")
    assert not hasattr(context, "email_compatibility_chunks")


def test_governance_package_exports_only_active_runtime_surface() -> None:
    assert "GovernedContext" in fourok.governance.__all__
    assert "SourceChange" in fourok.governance.__all__
    assert "StaticRevealPolicy" not in fourok.governance.__all__
    assert "CerbosRevealPolicy" not in fourok.governance.__all__
    assert "RevealPolicy" not in fourok.governance.__all__
    assert "RevealPolicyDecision" not in fourok.governance.__all__


def test_active_policy_module_only_exposes_principal_context() -> None:
    import fourok.governance.policy as active_policy

    assert hasattr(active_policy, "PrincipalContext")
    assert not hasattr(active_policy, "StaticRevealPolicy")
    assert not hasattr(active_policy, "CerbosRevealPolicy")
    assert not hasattr(active_policy, "RevealPolicy")
    assert not hasattr(active_policy, "RevealPolicyDecision")


def test_audit_records_search_events() -> None:
    context = build_context()
    principal = PrincipalContext(
        human_id="human:finance-1",
        agent_id="agent:context-helper",
        roles=("operator",),
    )

    context.search_context("refund iban canceled account", limit=3, principal=principal)

    events = context.audit_events()
    assert [event["event_type"] for event in events] == ["search", "source_access"]
    assert events[0]["query"] == "refund iban canceled account"
    assert events[0]["human_id"] == "human:finance-1"
    assert events[0]["agent_id"] == "agent:context-helper"
    assert events[1]["query"] == "refund iban canceled account"
    assert events[1]["human_id"] == "human:finance-1"
    assert events[1]["agent_id"] == "agent:context-helper"
    assert events[1]["decision"] == "allowed"
    assert events[1]["source_refs"] == events[0]["source_refs"]


def test_governed_context_active_api_does_not_expose_source_metadata() -> None:
    context = GovernedContext()

    assert not hasattr(context, "source_metadata")


def test_audit_events_can_be_filtered_for_human_review() -> None:
    context = build_context()
    principal = PrincipalContext(
        human_id="human:finance-1",
        agent_id="agent:context-helper",
        roles=("operator",),
    )
    other_principal = PrincipalContext(
        human_id="human:support-1",
        agent_id="agent:context-helper",
        roles=("operator",),
    )

    context.search_context("refund iban canceled account", principal=principal)
    context.search_context("payment failed", principal=other_principal)

    assert context.audit_events(event_type="reveal") == []
    assert {
        event["event_type"]
        for event in context.audit_events(source_ref="local_email:0013-refund-iban")
    } == {"search", "source_access"}
    assert {event["human_id"] for event in context.audit_events(human_id="human:finance-1")} == {
        "human:finance-1"
    }


def test_golden_queries_still_pass_after_sanitization() -> None:
    context = build_context()
    golden_queries = {
        "refund cancellation payment": "local_email:0002-refund-bank-transfer",
        "account termination final invoice": "local_email:0011-termination-confirmed",
        "payment failed March invoice": "local_email:0004-payment-failed",
        "data export workspace archive": "local_email:0009-data-export",
        "upgrade additional seats priority support": "local_email:0010-upgrade-plan",
    }

    for query, expected_source_ref in golden_queries.items():
        response = context.search_context(query, limit=3)
        assert expected_source_ref in [result.source_ref for result in response.results]


def test_tricky_identifiers_are_raw_and_searchable() -> None:
    response = build_context().search_context("payment reference refund status", limit=3)
    raw_response = build_context().search_context(RAW_SPACED_IBAN, limit=3)

    serialized = f"{response} {raw_response}"
    assert "PAYMENT_ID_" not in serialized
    assert "BANK_ACCOUNT_" not in serialized
    assert RAW_TRICKY_EMAIL in serialized
    assert RAW_SPACED_IBAN in serialized
    stored = " ".join(
        str(row)
        for row in build_context().retrieval_units()
        if row["source_ref"] == "local_email:0014-tricky-pii"
    )
    assert RAW_PAYMENT_REF in stored
    assert any(result.source_ref == "local_email:0014-tricky-pii" for result in response.results)


def test_sqlalchemy_database_url_can_use_sqlite_file(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'context.sqlite'}"
    first = GovernedContext(database_url=database_url)
    first.ingest(load_email_dir(FIXTURES))

    response = first.search_context("refund cancellation payment", limit=3)

    assert any(
        result.source_ref == "local_email:0002-refund-bank-transfer" for result in response.results
    )


def test_restricted_source_stops_appearing_in_search_and_keeps_audit_ref() -> None:
    context = build_context()
    messages = load_email_dir(FIXTURES)
    source_ref = "local_email:0013-refund-iban"

    assert source_ref in [
        result.source_ref
        for result in context.search_context("refund iban canceled account", limit=3).results
    ]

    context.restrict_source(source_ref, reason="source_permission_revoked")
    context.ingest(messages)

    response = context.search_context("refund iban canceled account", limit=5)
    lifecycle = context.source_lifecycle()
    lifecycle_event = next(
        event for event in context.audit_events() if event["event_type"] == "source_lifecycle"
    )

    assert source_ref not in [result.source_ref for result in response.results]
    assert lifecycle == [
        {
            "source_ref": source_ref,
            "state": "restricted",
            "reason": "source_permission_revoked",
        }
    ]
    assert lifecycle_event["event_type"] == "source_lifecycle"
    assert lifecycle_event["source_refs"] == source_ref
    assert lifecycle_event["decision"] == "restricted"


def test_deleted_source_is_removed_from_vector_index() -> None:
    context = build_context()
    vector_index = context.build_vector_index()
    messages = load_email_dir(FIXTURES)
    source_ref = "local_email:0002-refund-bank-transfer"

    assert source_ref in [
        result.source_ref for result in vector_index.search("bank transfer refund")
    ]

    context.delete_source(source_ref, reason="source_deleted")
    context.ingest(messages)

    assert source_ref not in [
        result.source_ref for result in vector_index.search("bank transfer refund")
    ]
    assert source_ref not in [
        result.source_ref
        for result in context.search_context("refund cancellation payment", limit=5).results
    ]


def test_deleted_source_removes_raw_object_but_restricted_source_keeps_it(tmp_path: Path) -> None:
    messages = load_email_dir(FIXTURES)
    deleted_ref = "local_email:0002-refund-bank-transfer"
    restricted_ref = "local_email:0013-refund-iban"
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")
    context.ingest(messages)

    assert deleted_ref in context.raw_source_refs()
    assert restricted_ref in context.raw_source_refs()

    context.delete_source(deleted_ref, reason="source_deleted")
    context.restrict_source(restricted_ref, reason="source_permission_revoked")
    context.ingest(messages)

    assert deleted_ref not in context.raw_source_refs()
    assert restricted_ref in context.raw_source_refs()
    assert deleted_ref not in [
        result.source_ref
        for result in context.search_context("refund cancellation payment", limit=5).results
    ]
    assert restricted_ref not in [
        result.source_ref
        for result in context.search_context("refund iban canceled account", limit=5).results
    ]


def test_restricted_raw_source_objects_can_be_purged_after_retention_window(
    tmp_path: Path,
) -> None:
    messages = load_email_dir(FIXTURES)
    restricted_ref = "local_email:0013-refund-iban"
    context = GovernedContext(raw_store_path=tmp_path / "raw-source-objects")
    context.ingest(messages)
    context.restrict_source(restricted_ref, reason="source_permission_revoked")

    assert restricted_ref in context.raw_source_refs()

    purged = context.purge_expired_raw_sources(
        retention_days=0,
        now=datetime.now(UTC) + timedelta(seconds=1),
    )

    assert purged == [restricted_ref]
    assert restricted_ref not in context.raw_source_refs()
    assert restricted_ref not in [
        result.source_ref
        for result in context.search_context("refund iban canceled account", limit=5).results
    ]


def test_expired_audit_events_can_be_purged_by_retention_window() -> None:
    context = GovernedContext()
    context._record_audit(
        "search",
        {
            "query": "old audit",
            "recorded_at": "2026-05-01T00:00:00+00:00",
        },
    )
    context._record_audit(
        "search",
        {
            "query": "recent audit",
            "recorded_at": "2026-05-23T00:00:00+00:00",
        },
    )

    purged_count = context.purge_expired_audit_events(
        retention_days=7,
        now=datetime(2026, 5, 24, tzinfo=UTC),
    )

    assert purged_count == 1
    assert [event["query"] for event in context.audit_events()] == ["recent audit"]


def test_gmail_source_record_update_replaces_searchable_content_for_same_source_ref() -> None:
    context = GovernedContext()
    first = gmail_message_to_source_record(
        {
            "id": "msg-123",
            "threadId": "thread-123",
            "internalDate": "1716998096000",
            "snippet": "First synthetic summary",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Quarterly plan"},
                    {"name": "From", "value": "Planner <planner@example.com>"},
                    {"name": "To", "value": "ops@example.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": "Rmlyc3Qgc3ludGhldGljIGJvZHk="},
                    }
                ],
            },
            "permissionSnapshotStatus": "current",
        }
    )
    updated = gmail_message_to_source_record(
        {
            "id": "msg-123",
            "threadId": "thread-123",
            "internalDate": "1716998096000",
            "snippet": "Updated synthetic summary",
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Quarterly plan updated"},
                    {"name": "From", "value": "Planner <planner@example.com>"},
                    {"name": "To", "value": "ops@example.com"},
                ],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": "VXBkYXRlZCBzeW50aGV0aWMgYm9keQ=="},
                    }
                ],
            },
            "permissionSnapshotStatus": "current",
        }
    )

    context.ingest_source_records([first])
    context.ingest_source_records([updated])

    rows = context.retrieval_units()
    search = context.search_context("updated synthetic", limit=5)

    assert [row["source_ref"] for row in rows] == ["gmail:message:msg-123"]
    serialized_rows = str(rows)
    assert "First synthetic body" not in serialized_rows
    assert "Updated synthetic body" in serialized_rows
    assert [result.source_ref for result in search.results] == ["gmail:message:msg-123"]
    assert "Quarterly plan updated" in search.results[0].subject


def test_source_change_ingest_does_not_populate_legacy_email_chunks() -> None:
    context = build_context()

    with context._engine.connect() as connection:
        rows = connection.execute(select(context._chunks)).all()

    assert rows == []


def test_ingest_source_records_accepts_non_email_work_items() -> None:
    context = GovernedContext()

    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Ask Robin to move meeting",
                body="Olivia asked Robin to move the customer meeting.",
                author_ref="linear:user:olivia",
                permission_refs=("linear:team:ops",),
                metadata={"state": "triage"},
            )
        ]
    )

    assert context.source_records()[0]["source_ref"] == "linear:issue:OPS-1"
    assert context.canonical_objects() == [
        {
            "object_ref": "linear:issue:OPS-1",
            "object_type": "WorkItem",
            "title": "Ask Robin to move meeting",
            "source_refs": '["linear:issue:OPS-1"]',
            "metadata_json": (
                '{"record_type": "work_item", "source_id": "OPS-1", '
                '"source_system": "linear", "state": "triage"}'
            ),
            "lifecycle_state": "active",
        }
    ]
    assert context.search_context("customer meeting").results == []


def test_restricted_linked_entity_does_not_leak_through_evidence_pack() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:user:finance-robin",
                source_system="linear",
                source_id="linear-user-finance-robin",
                record_type="person",
                title="Finance Robin",
                body="Finance Robin employee",
                permission_refs=("group:finance",),
                source_identities=(
                    SourceIdentity(
                        source_system="linear",
                        identity_ref="linear:email:finance.robin@example.com",
                        identity_type="email",
                        value="finance.robin@example.com",
                        display_name="Finance Robin",
                    ),
                ),
            ),
            SourceRecord(
                source_ref="linear:issue:PUBLIC-1",
                source_system="linear",
                source_id="PUBLIC-1",
                record_type="work_item",
                title="Public workspace migration",
                body="Public workspace migration needs review.",
                author_ref="linear-user-finance-robin",
            ),
        ]
    )

    response = context.search_context(
        "workspace migration",
        principal=PrincipalContext(
            human_id="human:support-1",
            agent_id="agent:context-helper",
            roles=("support",),
        ),
    )

    assert [result.source_ref for result in response.results] == ["linear:issue:PUBLIC-1"]
    assert response.evidence_items[0]["linked_entities"] == []
    assert response.related_objects == []
    assert response.entities == []
    assert "Finance Robin" not in str(response)
    assert "finance.robin@example.com" not in str(response)


def test_search_context_expands_visible_project_related_object() -> None:
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:project:project-meetings",
                source_system="linear",
                source_id="project-meetings",
                record_type="project",
                title="Meeting Operations",
                body="Meeting Operations project",
                permission_refs=("linear:team:sales",),
            ),
            SourceRecord(
                source_ref="linear:project:project-finance",
                source_system="linear",
                source_id="project-finance",
                record_type="project",
                title="Finance Operations",
                body="Finance Operations project",
                permission_refs=("linear:team:finance",),
            ),
            SourceRecord(
                source_ref="linear:issue:ABC-123",
                source_system="linear",
                source_id="ABC-123",
                record_type="work_item",
                title="Move renewal meeting",
                body="Move renewal meeting with Robin.",
                metadata={"project_id": "project-meetings"},
                permission_refs=("linear:team:sales",),
            ),
        ]
    )

    response = context.search_context(
        "renewal meeting Robin",
        limit=1,
        principal=PrincipalContext(
            human_id="human:sales-1",
            agent_id="agent:context-helper",
            roles=("linear:team:sales",),
        ),
    )

    assert [result.source_ref for result in response.results] == ["linear:issue:ABC-123"]
    assert response.related_object_groups["work_items"] == [
        {
            "object_ref": "linear:project:project-meetings",
            "object_type": "WorkItem",
            "title": "Meeting Operations",
            "relationship_to_primary": "same project",
            "relationship_source_refs": [
                "linear:issue:ABC-123",
                "linear:project:project-meetings",
            ],
            "confidence": 0.85,
            "follow_up_hint": "Ask about Meeting Operations",
        }
    ]
    assert "Finance Operations" not in str(response)


def test_adapted_gmail_record_search_returns_raw_internal_fields_without_tokens() -> None:
    context = GovernedContext()
    context.ingest_source_records([adapted_gmail_record()])

    response = context.search_context("Falcon refund review", limit=3)
    serialized = str(response)

    assert [result.source_ref for result in response.results] == ["gmail:message:msg-pii-pilot"]
    assert "EMAIL_" not in response.results[0].subject
    assert "PHONE_" not in response.results[0].snippet
    assert "BANK_ACCOUNT_" not in response.results[0].snippet
    assert not hasattr(response, "sensitive_tokens")
    assert RAW_GMAIL_EMAIL in serialized
    assert context.source_records()[0]["retrieval_text"].endswith(f"use IBAN {RAW_GMAIL_IBAN}.")
    assert response.summary == "1 evidence item"
    assert response.query == "Falcon refund review"
    assert response.result_candidates == [
        {
            "source_ref": "gmail:message:msg-pii-pilot",
            "title": response.results[0].subject,
            "snippet": response.results[0].snippet,
            "timestamp": "2024-05-29T15:54:56+00:00",
            "source_url": "https://mail.google.com/mail/u/0/#all/thread-pii-pilot/msg-pii-pilot",
            "record_type": "email",
            "source_system": "gmail",
            "source_id": "msg-pii-pilot",
            "ranking_reason": "keyword match in permission-filtered retrieval unit",
            "score": None,
        }
    ]
    assert response.evidence_items == [
        {
            "source_ref": "gmail:message:msg-pii-pilot",
            "source_url": "https://mail.google.com/mail/u/0/#all/thread-pii-pilot/msg-pii-pilot",
            "source_type": "Message",
            "record_type": "email",
            "source_system": "gmail",
            "source_id": "msg-pii-pilot",
            "canonical_object_type": "Message",
            "title": response.results[0].subject,
            "snippet": response.results[0].snippet,
            "timestamp": "2024-05-29T15:54:56+00:00",
            "updated_timestamp": "",
            "linked_entities": [],
            "permission_refs": [],
            "score": None,
            "why_included": "matched permission-filtered retrieval text",
        }
    ]
    assert response.primary_objects == [
        {
            "object_ref": "gmail:message:msg-pii-pilot",
            "object_type": "Message",
            "title": response.results[0].subject,
            "source_refs": ["gmail:message:msg-pii-pilot"],
            "why_primary": "matched evidence source",
            "confidence": 1.0,
        }
    ]
    assert response.related_objects == []
    assert response.entities == []
    assert response.unresolved_candidates == []
    assert response.limitations == [
        "related object expansion is limited to source-backed entity links and threads"
    ]
    assert response.audit_ref.startswith("audit:search:")


def test_adapted_gmail_record_is_searchable_by_raw_internal_values() -> None:
    context = GovernedContext()
    context.ingest_source_records([adapted_gmail_record()])

    direct = context.search_context(RAW_GMAIL_IBAN, limit=3)

    assert [result.source_ref for result in direct.results] == ["gmail:message:msg-pii-pilot"]
    assert not hasattr(direct, "sensitive_tokens")
