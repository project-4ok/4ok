from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, insert, select
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.governance.policy import PrincipalContext


def record_audit_event(
    engine: Engine,
    audit_events: Table,
    event_type: str,
    values: dict[str, object],
) -> str:
    principal = values.get("principal") or PrincipalContext.local_default()
    if not isinstance(principal, PrincipalContext):
        raise TypeError("principal must be a PrincipalContext")

    with engine.begin() as connection:
        result = connection.execute(
            insert(audit_events).values(
                event_type=event_type,
                query=values.get("query", ""),
                token=values.get("token", ""),
                purpose=values.get("purpose", ""),
                human_id=principal.human_id,
                agent_id=principal.agent_id,
                decision=values.get("decision", ""),
                reason=values.get("reason", ""),
                policy_id=values.get("policy_id", ""),
                policy_version=values.get("policy_version", ""),
                result_count=values.get("result_count", 0),
                source_refs=",".join(values.get("source_refs", [])),
                recorded_at=values.get("recorded_at", _now_iso()),
            )
        )
    audit_id = result.inserted_primary_key[0]
    return f"audit:{event_type}:{audit_id}"


def audit_events(
    engine: Engine,
    audit_events_table: Table,
    *,
    event_type: str | None = None,
    source_ref: str | None = None,
    token: str | None = None,
    human_id: str | None = None,
) -> list[dict[str, object]]:
    statement = select(
        audit_events_table.c.event_type,
        audit_events_table.c.query,
        audit_events_table.c.token,
        audit_events_table.c.purpose,
        audit_events_table.c.human_id,
        audit_events_table.c.agent_id,
        audit_events_table.c.decision,
        audit_events_table.c.reason,
        audit_events_table.c.policy_id,
        audit_events_table.c.policy_version,
        audit_events_table.c.result_count,
        audit_events_table.c.source_refs,
        audit_events_table.c.recorded_at,
    )
    if event_type:
        statement = statement.where(audit_events_table.c.event_type == event_type)
    if source_ref:
        statement = statement.where(audit_events_table.c.source_refs.contains(source_ref))
    if token:
        statement = statement.where(audit_events_table.c.token == token)
    if human_id:
        statement = statement.where(audit_events_table.c.human_id == human_id)
    statement = statement.order_by(audit_events_table.c.id)
    with engine.connect() as connection:
        return [dict(row) for row in connection.execute(statement).mappings()]


def audit_summary(engine: Engine, audit_events_table: Table) -> dict[str, Any]:
    events = audit_events(engine, audit_events_table)
    return {
        "total_events": len(events),
        "event_types": _counts(event["event_type"] for event in events),
        "decisions": _counts(event["decision"] for event in events if event["decision"]),
        "humans": _counts(event["human_id"] for event in events if event["human_id"]),
    }


def purge_expired_audit_events(
    engine: Engine,
    audit_events_table: Table,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> int:
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    with engine.begin() as connection:
        result = connection.execute(
            delete(audit_events_table).where(
                audit_events_table.c.recorded_at != "",
                audit_events_table.c.recorded_at < cutoff.isoformat(),
            )
        )
    return result.rowcount or 0


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
