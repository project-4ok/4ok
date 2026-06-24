from datetime import UTC, datetime

from gcb.governance import GovernedContext
from gcb.governance.state import create_governed_context_state
from gcb.runtime.webhooks import (
    WebhookEventInput,
    enqueue_webhook_event,
    process_pending_webhook_events,
    webhook_event_rows,
)


def test_webhook_event_is_landed_idempotently_and_processed_through_source_changes(
    tmp_path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store_path = tmp_path / "raw-source-objects"
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=raw_store_path,
    )
    context = GovernedContext(state_path, raw_store_path=raw_store_path)
    event = WebhookEventInput(
        event_id="evt-linear-1",
        source_system="linear",
        source_object_id="OPS-1",
        event_type="issue.updated",
        operation="upsert",
        idempotency_key="linear:OPS-1:updated:1",
        occurred_at="2026-06-01T10:00:00+00:00",
        actor_ref="linear:user:olivia",
        payload={
            "source_record": {
                "source_ref": "linear:issue:OPS-1",
                "source_system": "linear",
                "source_id": "OPS-1",
                "record_type": "work_item",
                "title": "Move customer meeting",
                "body": "Olivia moved the customer meeting.",
                "author_ref": "linear:user:olivia",
                "metadata": {"state": "triage"},
            }
        },
    )

    first = enqueue_webhook_event(
        state,
        event,
        now=datetime(2026, 6, 1, 10, 1, tzinfo=UTC),
    )
    second = enqueue_webhook_event(
        state,
        event,
        now=datetime(2026, 6, 1, 10, 2, tzinfo=UTC),
    )
    report = process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 6, 1, 10, 3, tzinfo=UTC),
    )

    assert first == second
    assert state.raw_store is not None
    assert state.raw_store.exists("webhook:linear:evt-linear-1:raw")
    assert report == {"claimed": 1, "succeeded": 1, "failed": 0, "invalid": 0}
    assert context.source_records()[0]["source_ref"] == "linear:issue:OPS-1"
    assert context.source_records()[0]["metadata_json"] == '{"state": "triage"}'
    assert webhook_event_rows(state) == [
        {
            "event_id": "evt-linear-1",
            "source_system": "linear",
            "source_object_id": "OPS-1",
            "event_type": "issue.updated",
            "operation": "upsert",
            "idempotency_key": "linear:OPS-1:updated:1",
            "occurred_at": "2026-06-01T10:00:00+00:00",
            "received_at": "2026-06-01T10:01:00+00:00",
            "actor_ref": "linear:user:olivia",
            "raw_payload_ref": "webhook:linear:evt-linear-1:raw",
            "payload": event.payload,
            "status": "succeeded",
            "attempt_count": 1,
            "next_retry_at": "",
            "error_class": "",
            "error": "",
            "processed_at": "2026-06-01T10:03:00+00:00",
        }
    ]


def test_webhook_delete_event_uses_same_source_change_lifecycle_path(tmp_path) -> None:
    state_path = tmp_path / "state.sqlite"
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    context = GovernedContext(state_path)
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-upsert",
            source_system="linear",
            source_object_id="OPS-2",
            event_type="issue.created",
            operation="upsert",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:OPS-2",
                    "source_system": "linear",
                    "source_id": "OPS-2",
                    "record_type": "work_item",
                    "title": "Delete customer meeting",
                    "body": "Delete customer meeting marker.",
                }
            },
        ),
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-delete",
            source_system="linear",
            source_object_id="OPS-2",
            event_type="issue.deleted",
            operation="delete",
            payload={"source_ref": "linear:issue:OPS-2", "reason": "source_deleted"},
        ),
    )

    report = process_pending_webhook_events(state, context)

    assert report == {"claimed": 2, "succeeded": 2, "failed": 0, "invalid": 0}
    assert context.search_context("delete customer meeting marker").results == []
    assert context.source_records()[0]["lifecycle_state"] == "deleted"
    assert context.source_lifecycle() == [
        {
            "source_ref": "linear:issue:OPS-2",
            "state": "deleted",
            "reason": "source_deleted",
        }
    ]


def test_webhook_processing_quarantines_invalid_payloads(tmp_path) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        raw_store_path=None,
    )
    context = GovernedContext(tmp_path / "state.sqlite")
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-invalid",
            source_system="linear",
            source_object_id="OPS-3",
            event_type="issue.updated",
            operation="upsert",
            payload={"source_record": {"source_ref": "linear:issue:OPS-3"}},
        ),
    )

    report = process_pending_webhook_events(state, context)
    invalid = webhook_event_rows(state)[0]

    assert report == {"claimed": 1, "succeeded": 0, "failed": 0, "invalid": 1}
    assert invalid["status"] == "invalid"
    assert invalid["attempt_count"] == 1
    assert invalid["next_retry_at"] == ""
    assert invalid["error_class"] == "WebhookPayloadError"
    assert invalid["error"] == "source_record requires source_system"


def test_webhook_processing_retries_failed_events_after_backoff(tmp_path) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        raw_store_path=None,
    )

    class FailingContext:
        def apply_source_changes(self, changes):
            raise RuntimeError("database unavailable")

    context = FailingContext()
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-retry",
            source_system="linear",
            source_object_id="OPS-4",
            event_type="issue.updated",
            operation="upsert",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:OPS-4",
                    "source_system": "linear",
                    "source_id": "OPS-4",
                    "record_type": "work_item",
                }
            },
        ),
    )

    first_report = process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
        retry_delay_seconds=120,
    )
    too_early_report = process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 6, 1, 10, 1, tzinfo=UTC),
        retry_delay_seconds=120,
    )
    retryable = webhook_event_rows(state)[0]
    second_report = process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 6, 1, 10, 2, tzinfo=UTC),
        retry_delay_seconds=120,
    )
    retried = webhook_event_rows(state)[0]

    assert first_report == {"claimed": 1, "succeeded": 0, "failed": 1, "invalid": 0}
    assert too_early_report == {"claimed": 0, "succeeded": 0, "failed": 0, "invalid": 0}
    assert retryable["status"] == "pending"
    assert retryable["attempt_count"] == 1
    assert retryable["next_retry_at"] == "2026-06-01T10:02:00+00:00"
    assert retryable["error_class"] == "RuntimeError"
    assert retryable["error"] == "database unavailable"
    assert retryable["processed_at"] == ""
    assert second_report == {"claimed": 1, "succeeded": 0, "failed": 1, "invalid": 0}
    assert retried["attempt_count"] == 2
    assert retried["next_retry_at"] == "2026-06-01T10:04:00+00:00"
