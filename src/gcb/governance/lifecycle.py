from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, insert, inspect, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from gcb.governance.audit import record_audit_event
from gcb.governance.policy import PrincipalContext


class RawSourceStore(Protocol):
    def delete(self, source_ref: str) -> None: ...


def source_lifecycle_rows(engine: Engine, source_lifecycle: Table) -> list[dict[str, object]]:
    statement = select(
        source_lifecycle.c.source_ref,
        source_lifecycle.c.state,
        source_lifecycle.c.reason,
        source_lifecycle.c.replacement_ref,
        source_lifecycle.c.duplicate_group_ref,
    ).order_by(source_lifecycle.c.source_ref)
    with engine.connect() as connection:
        return [
            _serialize_source_lifecycle_row(dict(row))
            for row in connection.execute(statement).mappings()
        ]


def inactive_source_refs(engine: Engine, source_lifecycle: Table) -> set[str]:
    statement = select(source_lifecycle.c.source_ref).where(source_lifecycle.c.state != "active")
    with engine.connect() as connection:
        return {row[0] for row in connection.execute(statement)}


def purge_expired_raw_sources(
    engine: Engine,
    source_lifecycle: Table,
    raw_store: RawSourceStore | None,
    *,
    retention_days: int,
    now: datetime | None = None,
) -> list[str]:
    if raw_store is None:
        return []
    cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
    statement = select(
        source_lifecycle.c.source_ref,
        source_lifecycle.c.recorded_at,
    ).where(source_lifecycle.c.state == "restricted")
    purged = []
    with engine.connect() as connection:
        rows = connection.execute(statement).mappings()
        for row in rows:
            recorded_at = parse_iso_datetime(row["recorded_at"])
            if recorded_at is not None and recorded_at <= cutoff:
                raw_store.delete(row["source_ref"])
                purged.append(row["source_ref"])
    return sorted(purged)


def remove_source_from_retrieval(
    engine: Engine,
    *,
    emails: Table,
    chunks: Table,
    audit_events: Table,
    source_lifecycle: Table,
    raw_store: RawSourceStore | None,
    source_ref: str,
    state: str,
    reason: str,
    principal: PrincipalContext,
    replacement_ref: str = "",
    duplicate_group_ref: str = "",
) -> None:
    has_chunk_embeddings = inspect(engine).has_table("chunk_embeddings")
    with engine.begin() as connection:
        connection.execute(delete(emails).where(emails.c.source_ref == source_ref))
        connection.execute(delete(chunks).where(chunks.c.source_ref == source_ref))
        existing = connection.execute(
            select(source_lifecycle.c.source_ref).where(source_lifecycle.c.source_ref == source_ref)
        ).first()
        if existing:
            connection.execute(
                source_lifecycle.update()
                .where(source_lifecycle.c.source_ref == source_ref)
                .values(
                    state=state,
                    reason=reason,
                    replacement_ref=replacement_ref,
                    duplicate_group_ref=duplicate_group_ref,
                    recorded_at=now_iso(),
                )
            )
        else:
            connection.execute(
                insert(source_lifecycle).values(
                    source_ref=source_ref,
                    state=state,
                    reason=reason,
                    replacement_ref=replacement_ref,
                    duplicate_group_ref=duplicate_group_ref,
                    recorded_at=now_iso(),
                )
            )

        if has_chunk_embeddings:
            connection.execute(
                text("DELETE FROM chunk_embeddings WHERE source_ref = :source_ref"),
                {"source_ref": source_ref},
            )

    if state == "deleted" and raw_store is not None:
        raw_store.delete(source_ref)

    record_audit_event(
        engine,
        audit_events,
        "source_lifecycle",
        {
            "principal": principal,
            "decision": state,
            "reason": reason,
            "source_refs": [source_ref],
        },
    )


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _serialize_source_lifecycle_row(row: dict[str, object]) -> dict[str, object]:
    if not row.get("replacement_ref"):
        row.pop("replacement_ref", None)
    if not row.get("duplicate_group_ref"):
        row.pop("duplicate_group_ref", None)
    return row


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
