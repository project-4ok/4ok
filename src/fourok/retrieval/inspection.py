from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.sql.schema import Table

from fourok.governance.policy import PrincipalContext


def inspect_source(
    engine: Engine,
    source_records: Table,
    source_ref: str,
    *,
    retrieval_event_id: str | None = None,
    rank: int | None = None,
    principal: PrincipalContext | None = None,
) -> dict[str, object]:
    normalized_ref = source_ref.strip()
    if not normalized_ref:
        raise ValueError("source_ref is required")

    statement = select(source_records).where(source_records.c.source_ref == normalized_ref)
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    if row is None:
        return {"status": "not_found", "source_ref": normalized_ref}

    record = dict(row)
    if record.get("lifecycle_state") != "active":
        return {
            "status": "inactive",
            "source_ref": normalized_ref,
            "lifecycle_state": record.get("lifecycle_state") or "",
        }

    inspection_event_id = _record_retrieval_inspection_event(
        engine,
        retrieval_event_id=retrieval_event_id or "",
        source_ref=normalized_ref,
        rank=rank,
        source_system=str(record.get("source_system") or ""),
        record_type=str(record.get("record_type") or ""),
        principal=principal or PrincipalContext.local_default(),
    )
    return {
        "status": "ok",
        "source_ref": normalized_ref,
        "source_system": record.get("source_system") or "",
        "source_id": record.get("source_id") or "",
        "record_type": record.get("record_type") or "",
        "title": record.get("title") or "",
        "occurred_at": record.get("occurred_at") or "",
        "updated_at": record.get("updated_at") or "",
        "source_url": record.get("source_url") or "",
        "thread_ref": record.get("thread_ref") or "",
        "text": record.get("retrieval_text") or "",
        "inspection_event_id": inspection_event_id,
    }


def _record_retrieval_inspection_event(
    engine: Engine,
    *,
    retrieval_event_id: str,
    source_ref: str,
    rank: int | None,
    source_system: str,
    record_type: str,
    principal: PrincipalContext,
) -> str:
    event_id = f"retrieval-inspection:{uuid.uuid4()}"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS retrieval_inspection_events (
                    event_id TEXT PRIMARY KEY,
                    occurred_at TEXT NOT NULL,
                    retrieval_query_event_id TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    rank INTEGER,
                    source_system TEXT NOT NULL,
                    record_type TEXT NOT NULL,
                    human_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO retrieval_inspection_events (
                    event_id, occurred_at, retrieval_query_event_id, source_ref, rank,
                    source_system, record_type, human_id, agent_id
                ) VALUES (
                    :event_id, :occurred_at, :retrieval_query_event_id, :source_ref, :rank,
                    :source_system, :record_type, :human_id, :agent_id
                )
                """
            ),
            {
                "event_id": event_id,
                "occurred_at": datetime.now(UTC).isoformat(),
                "retrieval_query_event_id": retrieval_event_id,
                "source_ref": source_ref,
                "rank": rank,
                "source_system": source_system,
                "record_type": record_type,
                "human_id": principal.human_id,
                "agent_id": principal.agent_id,
            },
        )
    return event_id
