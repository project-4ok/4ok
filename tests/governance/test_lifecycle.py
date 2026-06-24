import inspect
from datetime import UTC, datetime, timedelta

from sqlalchemy import insert, select

from gcb.governance.lifecycle import (
    inactive_source_refs,
    purge_expired_raw_sources,
    remove_source_from_retrieval,
    source_lifecycle_rows,
)
from gcb.governance.policy import PrincipalContext
from gcb.governance.state import create_governed_context_state


class FakeRawStore:
    def __init__(self) -> None:
        self.deleted: list[str] = []

    def delete(self, source_ref: str) -> None:
        self.deleted.append(source_ref)


def test_remove_source_from_retrieval_tombstones_rows_and_records_audit() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    source_ref = "local_email:source-1"
    raw_store = FakeRawStore()

    with state.engine.begin() as connection:
        connection.execute(
            insert(state.emails).values(
                source_ref=source_ref,
                subject="Refund",
                body="Contact person@example.com",
                date="2001-01-01",
            )
        )
        connection.execute(
            insert(state.chunks).values(
                source_ref=source_ref,
                chunk_index=0,
                subject="Refund",
                body="Contact person@example.com",
                date="2001-01-01",
            )
        )

    remove_source_from_retrieval(
        state.engine,
        emails=state.emails,
        chunks=state.chunks,
        audit_events=state.audit_events,
        source_lifecycle=state.source_lifecycle,
        raw_store=raw_store,
        source_ref=source_ref,
        state="deleted",
        reason="source_deleted",
        principal=PrincipalContext(human_id="human:admin", agent_id="agent:context"),
    )

    with state.engine.connect() as connection:
        assert connection.execute(select(state.emails)).all() == []
        assert connection.execute(select(state.chunks)).all() == []
        audit_event = connection.execute(select(state.audit_events)).mappings().one()

    assert raw_store.deleted == [source_ref]
    assert source_lifecycle_rows(state.engine, state.source_lifecycle) == [
        {"source_ref": source_ref, "state": "deleted", "reason": "source_deleted"}
    ]
    assert inactive_source_refs(state.engine, state.source_lifecycle) == {source_ref}
    assert audit_event["event_type"] == "source_lifecycle"
    assert audit_event["human_id"] == "human:admin"
    assert audit_event["agent_id"] == "agent:context"
    assert audit_event["decision"] == "deleted"
    assert audit_event["source_refs"] == source_ref


def test_active_lifecycle_api_does_not_require_token_tables() -> None:
    signature = inspect.signature(remove_source_from_retrieval)

    assert "token_store" not in signature.parameters
    assert "token_sources" not in signature.parameters


def test_purge_expired_raw_sources_only_deletes_expired_restricted_refs() -> None:
    state = create_governed_context_state(
        state_path=":memory:",
        database_url=None,
        raw_store_path=None,
    )
    raw_store = FakeRawStore()
    now = datetime(2026, 5, 24, tzinfo=UTC)

    with state.engine.begin() as connection:
        connection.execute(
            insert(state.source_lifecycle),
            [
                {
                    "source_ref": "local_email:old-restricted",
                    "state": "restricted",
                    "reason": "retention",
                    "recorded_at": (now - timedelta(days=10)).isoformat(),
                },
                {
                    "source_ref": "local_email:fresh-restricted",
                    "state": "restricted",
                    "reason": "retention",
                    "recorded_at": (now - timedelta(days=1)).isoformat(),
                },
                {
                    "source_ref": "local_email:deleted",
                    "state": "deleted",
                    "reason": "source_deleted",
                    "recorded_at": (now - timedelta(days=10)).isoformat(),
                },
            ],
        )

    purged = purge_expired_raw_sources(
        state.engine,
        state.source_lifecycle,
        raw_store,
        retention_days=7,
        now=now,
    )

    assert purged == ["local_email:old-restricted"]
    assert raw_store.deleted == ["local_email:old-restricted"]
