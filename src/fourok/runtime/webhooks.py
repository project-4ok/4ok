from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.schema import Table

from fourok.etl.extract.source_records import SourceAttachment, SourceIdentity, SourceRecord
from fourok.governance import GovernedContext, SourceChange
from fourok.storage.raw_store import FileRawSourceStore


class WebhookState(Protocol):
    @property
    def engine(self) -> Engine: ...

    @property
    def webhook_events(self) -> Table: ...

    @property
    def raw_store(self) -> FileRawSourceStore | None: ...


class WebhookPayloadError(ValueError):
    """Permanent source payload error that should not be retried."""


@dataclass(frozen=True)
class WebhookEventInput:
    event_id: str
    source_system: str
    event_type: str
    operation: str
    payload: dict[str, Any]
    source_object_id: str = ""
    idempotency_key: str = ""
    occurred_at: str = ""
    actor_ref: str = ""


def enqueue_webhook_event(
    state: WebhookState,
    event: WebhookEventInput,
    *,
    now: datetime | None = None,
) -> dict[str, object]:
    _validate_event(event)
    raw_payload_ref = f"webhook:{event.source_system}:{event.event_id}:raw"
    if state.raw_store is not None:
        state.raw_store.put(
            raw_payload_ref,
            {
                "source_ref": raw_payload_ref,
                "event_id": event.event_id,
                "source_system": event.source_system,
                "payload": event.payload,
            },
        )
    row = {
        "event_id": event.event_id,
        "source_system": event.source_system,
        "source_object_id": event.source_object_id,
        "event_type": event.event_type,
        "operation": event.operation,
        "idempotency_key": event.idempotency_key or event.event_id,
        "occurred_at": event.occurred_at,
        "received_at": _timestamp(now),
        "actor_ref": event.actor_ref,
        "raw_payload_ref": raw_payload_ref,
        "payload_json": event.payload,
        "status": "pending",
        "attempt_count": 0,
        "next_retry_at": "",
        "error_class": "",
        "error": "",
        "processed_at": "",
    }
    try:
        with state.engine.begin() as connection:
            connection.execute(insert(state.webhook_events).values(row))
    except IntegrityError:
        return _webhook_event_row(state, event.event_id) or _webhook_event_by_idempotency(
            state,
            event.idempotency_key or event.event_id,
        )
    return _serialize_event_row(row)


def webhook_event_rows(
    state: WebhookState,
    *,
    status: str | None = None,
) -> list[dict[str, object]]:
    statement = select(state.webhook_events).order_by(
        state.webhook_events.c.received_at,
        state.webhook_events.c.event_id,
    )
    if status:
        statement = statement.where(state.webhook_events.c.status == status)
    with state.engine.connect() as connection:
        return [_serialize_event_row(dict(row)) for row in connection.execute(statement).mappings()]


def process_pending_webhook_events(
    state: WebhookState,
    context: GovernedContext,
    *,
    limit: int = 10,
    now: datetime | None = None,
    max_attempts: int = 3,
    retry_delay_seconds: int = 60,
) -> dict[str, object]:
    claimed = _claim_pending_events(state, limit=limit, now=now)
    succeeded = 0
    failed = 0
    invalid = 0
    for event in claimed:
        try:
            context.apply_source_changes([_source_change_from_event(event)])
        except WebhookPayloadError as error:
            invalid += 1
            _mark_invalid(state, event, error=error, now=now)
        except Exception as error:
            failed += 1
            _mark_failed(
                state,
                event,
                error=error,
                now=now,
                max_attempts=max_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
        else:
            succeeded += 1
            _mark_succeeded(state, event["event_id"], now=now)
    return {
        "claimed": len(claimed),
        "succeeded": succeeded,
        "failed": failed,
        "invalid": invalid,
    }


def _claim_pending_events(
    state: WebhookState,
    *,
    limit: int,
    now: datetime | None,
) -> list[dict[str, object]]:
    current_time = _timestamp(now)
    with state.engine.begin() as connection:
        rows = [
            _serialize_event_row(dict(row))
            for row in connection.execute(
                select(state.webhook_events)
                .where(state.webhook_events.c.status == "pending")
                .where(
                    (state.webhook_events.c.next_retry_at == "")
                    | (state.webhook_events.c.next_retry_at <= current_time)
                )
                .order_by(state.webhook_events.c.received_at, state.webhook_events.c.event_id)
                .limit(limit)
            ).mappings()
        ]
        for row in rows:
            row["attempt_count"] = int(cast(int | str, row["attempt_count"])) + 1
            connection.execute(
                update(state.webhook_events)
                .where(state.webhook_events.c.event_id == row["event_id"])
                .where(state.webhook_events.c.status == "pending")
                .values(
                    status="processing",
                    attempt_count=row["attempt_count"],
                    error_class="",
                    error="",
                )
            )
    return rows


def _source_change_from_event(event: dict[str, object]) -> SourceChange:
    payload = event["payload"]
    if not isinstance(payload, dict):
        raise WebhookPayloadError("webhook event payload must be an object")
    record = _source_record_from_payload(payload)
    source_ref = _string(payload.get("source_ref")) or (record.source_ref if record else "")
    if record is None and not source_ref:
        raise WebhookPayloadError("webhook lifecycle event requires source_ref or source_record")
    return SourceChange(
        operation=_operation(event["operation"]),
        record=record,
        source_ref=source_ref,
        reason=_string(payload.get("reason")) or _string(event["event_type"]),
    )


def _source_record_from_payload(payload: dict[str, Any]) -> SourceRecord | None:
    value = payload.get("source_record")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise WebhookPayloadError("source_record payload must be an object")
    return SourceRecord(
        source_ref=_required_string(value, "source_ref"),
        source_system=_required_string(value, "source_system"),
        source_id=_required_string(value, "source_id"),
        record_type=_required_string(value, "record_type"),
        title=_string(value.get("title")),
        body=_string(value.get("body")),
        occurred_at=_string(value.get("occurred_at")),
        updated_at=_string(value.get("updated_at")),
        author_ref=_string(value.get("author_ref")),
        source_url=_string(value.get("source_url")),
        thread_ref=_string(value.get("thread_ref")),
        permission_refs=tuple(_string_list(value.get("permission_refs"))),
        permission_snapshot_status=_string(value.get("permission_snapshot_status")) or "current",
        attachment_refs=tuple(_string_list(value.get("attachment_refs"))),
        identity_refs=tuple(_string_list(value.get("identity_refs"))),
        lifecycle_state=_string(value.get("lifecycle_state")) or "active",
        checksum=_string(value.get("checksum")),
        version=_string(value.get("version")),
        metadata=_dict(value.get("metadata")),
        raw=_dict(value.get("raw")),
        raw_ref=_string(value.get("raw_ref")),
        source_identities=tuple(
            SourceIdentity(
                source_system=_required_string(identity, "source_system"),
                identity_ref=_required_string(identity, "identity_ref"),
                identity_type=_required_string(identity, "identity_type"),
                value=_required_string(identity, "value"),
                display_name=_string(identity.get("display_name")),
            )
            for identity in _dict_list(value.get("source_identities"))
        ),
        attachments=tuple(
            SourceAttachment(
                attachment_ref=_required_string(attachment, "attachment_ref"),
                title=_string(attachment.get("title")),
                text=_string(attachment.get("text")),
                content_type=_string(attachment.get("content_type")) or "text/plain",
            )
            for attachment in _dict_list(value.get("attachments"))
        ),
    )


def _mark_succeeded(state: WebhookState, event_id: object, *, now: datetime | None) -> None:
    with state.engine.begin() as connection:
        connection.execute(
            update(state.webhook_events)
            .where(state.webhook_events.c.event_id == str(event_id))
            .values(status="succeeded", processed_at=_timestamp(now), next_retry_at="")
        )


def _mark_failed(
    state: WebhookState,
    event: dict[str, object],
    *,
    error: Exception,
    now: datetime | None,
    max_attempts: int,
    retry_delay_seconds: int,
) -> None:
    attempt_count = int(cast(int | str, event["attempt_count"]))
    should_retry = attempt_count < max(1, max_attempts)
    current_time = now or datetime.now(UTC)
    values = {
        "status": "pending" if should_retry else "failed",
        "error_class": error.__class__.__name__,
        "error": str(error),
    }
    if should_retry:
        values["next_retry_at"] = (
            current_time + timedelta(seconds=max(0, retry_delay_seconds))
        ).isoformat()
        values["processed_at"] = ""
    else:
        values["processed_at"] = current_time.isoformat()
        values["next_retry_at"] = ""
    with state.engine.begin() as connection:
        connection.execute(
            update(state.webhook_events)
            .where(state.webhook_events.c.event_id == str(event["event_id"]))
            .values(**values)
        )


def _mark_invalid(
    state: WebhookState,
    event: dict[str, object],
    *,
    error: WebhookPayloadError,
    now: datetime | None,
) -> None:
    current_time = now or datetime.now(UTC)
    with state.engine.begin() as connection:
        connection.execute(
            update(state.webhook_events)
            .where(state.webhook_events.c.event_id == str(event["event_id"]))
            .values(
                status="invalid",
                error_class=error.__class__.__name__,
                error=str(error),
                processed_at=current_time.isoformat(),
                next_retry_at="",
            )
        )


def _webhook_event_row(state: WebhookState, event_id: str) -> dict[str, object] | None:
    with state.engine.connect() as connection:
        row = (
            connection.execute(
                select(state.webhook_events).where(state.webhook_events.c.event_id == event_id)
            )
            .mappings()
            .first()
        )
    return _serialize_event_row(dict(row)) if row is not None else None


def _webhook_event_by_idempotency(
    state: WebhookState,
    idempotency_key: str,
) -> dict[str, object]:
    with state.engine.connect() as connection:
        row = (
            connection.execute(
                select(state.webhook_events).where(
                    state.webhook_events.c.idempotency_key == idempotency_key
                )
            )
            .mappings()
            .one()
        )
    return _serialize_event_row(dict(row))


def _serialize_event_row(row: dict[str, Any]) -> dict[str, object]:
    row["payload"] = _json_object(row.pop("payload_json"))
    return row


def _validate_event(event: WebhookEventInput) -> None:
    if not event.event_id:
        raise ValueError("webhook event requires event_id")
    if not event.source_system:
        raise ValueError("webhook event requires source_system")
    if not event.event_type:
        raise ValueError("webhook event requires event_type")
    _operation(event.operation)


def _operation(value: object):
    operation = _string(value)
    if operation not in {"upsert", "delete", "restrict", "restore", "supersede", "duplicate"}:
        raise ValueError(f"unsupported source change operation: {operation}")
    return operation


def _timestamp(value: datetime | None) -> str:
    return (value or datetime.now(UTC)).isoformat()


def _required_string(value: dict[str, Any], key: str) -> str:
    result = _string(value.get(key))
    if not result:
        raise WebhookPayloadError(f"source_record requires {key}")
    return result


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str)]
    return []


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _json_object(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        return decoded if isinstance(decoded, dict) else {}
    return {}
