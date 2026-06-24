from datetime import UTC, datetime

import pytest
from sqlalchemy import MetaData, create_engine

from fourok.governance.audit import (
    audit_events,
    audit_summary,
    purge_expired_audit_events,
    record_audit_event,
)
from fourok.governance.policy import PrincipalContext
from fourok.storage.models import AuditEventRow, table_for_model


def build_audit_store():
    engine = create_engine("sqlite:///:memory:")
    metadata = MetaData()
    table = table_for_model(metadata, AuditEventRow.__table__)
    metadata.create_all(engine)
    return engine, table


def test_record_audit_event_uses_principal_and_source_refs() -> None:
    engine, table = build_audit_store()

    record_audit_event(
        engine,
        table,
        "search",
        {
            "query": "refund",
            "principal": PrincipalContext(
                human_id="human:finance-1",
                agent_id="agent:context-helper",
            ),
            "result_count": 2,
            "source_refs": ["source:1", "source:2"],
        },
    )

    events = audit_events(engine, table)
    assert len(events) == 1
    assert events[0] == {
        "event_type": "search",
        "query": "refund",
        "token": "",
        "purpose": "",
        "human_id": "human:finance-1",
        "agent_id": "agent:context-helper",
        "decision": "",
        "reason": "",
        "policy_id": "",
        "policy_version": "",
        "result_count": 2,
        "source_refs": "source:1,source:2",
        "recorded_at": events[0]["recorded_at"],
    }
    assert events[0]["recorded_at"]


def test_audit_events_filters_by_event_token_source_and_human() -> None:
    engine, table = build_audit_store()
    principal = PrincipalContext(human_id="human:finance-1", agent_id="agent:context-helper")
    record_audit_event(
        engine,
        table,
        "search",
        {"principal": principal, "source_refs": ["source:1"], "result_count": 1},
    )
    record_audit_event(
        engine,
        table,
        "reveal",
        {
            "principal": principal,
            "token": "BANK_ACCOUNT_ABC",
            "purpose": "payment_processing",
            "decision": "allowed",
        },
    )

    assert [event["event_type"] for event in audit_events(engine, table, event_type="reveal")] == [
        "reveal"
    ]
    assert [event["token"] for event in audit_events(engine, table, token="BANK_ACCOUNT_ABC")] == [
        "BANK_ACCOUNT_ABC"
    ]
    assert [
        event["event_type"] for event in audit_events(engine, table, source_ref="source:1")
    ] == ["search"]
    assert {
        event["human_id"] for event in audit_events(engine, table, human_id="human:finance-1")
    } == {"human:finance-1"}


def test_audit_summary_counts_events_decisions_and_humans() -> None:
    engine, table = build_audit_store()
    finance = PrincipalContext(human_id="human:finance-1", agent_id="agent:context-helper")
    support = PrincipalContext(human_id="human:support-1", agent_id="agent:context-helper")
    record_audit_event(
        engine,
        table,
        "search",
        {"principal": finance, "source_refs": ["source:1"], "result_count": 1},
    )
    record_audit_event(
        engine,
        table,
        "source_access",
        {"principal": finance, "source_refs": ["source:1"], "decision": "allowed"},
    )
    record_audit_event(
        engine,
        table,
        "reveal",
        {"principal": support, "token": "BANK_ACCOUNT_ABC", "decision": "denied"},
    )

    assert audit_summary(engine, table) == {
        "total_events": 3,
        "event_types": {"reveal": 1, "search": 1, "source_access": 1},
        "decisions": {"allowed": 1, "denied": 1},
        "humans": {"human:finance-1": 2, "human:support-1": 1},
    }


def test_purge_expired_audit_events_removes_events_older_than_retention() -> None:
    engine, table = build_audit_store()
    principal = PrincipalContext(human_id="human:finance-1", agent_id="agent:context-helper")
    record_audit_event(
        engine,
        table,
        "search",
        {
            "principal": principal,
            "query": "old",
            "recorded_at": "2026-05-01T00:00:00+00:00",
        },
    )
    record_audit_event(
        engine,
        table,
        "reveal",
        {
            "principal": principal,
            "token": "BANK_ACCOUNT_ABC",
            "recorded_at": "2026-05-23T00:00:00+00:00",
        },
    )

    purged_count = purge_expired_audit_events(
        engine,
        table,
        retention_days=7,
        now=datetime(2026, 5, 24, tzinfo=UTC),
    )

    assert purged_count == 1
    assert [event["event_type"] for event in audit_events(engine, table)] == ["reveal"]


def test_record_audit_event_rejects_invalid_principal() -> None:
    engine, table = build_audit_store()

    with pytest.raises(TypeError, match="principal must be a PrincipalContext"):
        record_audit_event(engine, table, "search", {"principal": object()})
