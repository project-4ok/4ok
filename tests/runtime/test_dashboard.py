from datetime import UTC, datetime

from gcb.etl.extract.source_records import SourceIdentity, SourceRecord
from gcb.etl.extract.sync_jobs import (
    complete_connector_job,
    fail_connector_job,
    mark_connector_job_invalid,
    start_connector_job,
)
from gcb.governance import GovernedContext, SourceChange
from gcb.governance.state import create_governed_context_state
from gcb.runtime.dashboard import operator_dashboard
from gcb.runtime.webhooks import WebhookEventInput, enqueue_webhook_event


def test_operator_dashboard_reports_import_link_lifecycle_and_audit_stats(tmp_path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    person = SourceRecord(
        source_ref="linear:user:olivia",
        source_system="linear",
        source_id="user-olivia",
        record_type="person",
        title="Olivia Example",
        body="Olivia Example employee",
        source_identities=(
            SourceIdentity(
                source_system="linear",
                identity_ref="linear:email:olivia@example.com",
                identity_type="email",
                value="olivia@example.com",
                display_name="Olivia Example",
            ),
        ),
    )
    issue = SourceRecord(
        source_ref="linear:issue:OPS-1",
        source_system="linear",
        source_id="OPS-1",
        record_type="work_item",
        title="Move customer meeting",
        body="Olivia needs to move the customer meeting.",
        author_ref="user-olivia",
    )
    doc = SourceRecord(
        source_ref="docs:runbook:1",
        source_system="google_drive",
        source_id="runbook-1",
        record_type="document",
        title="Customer runbook",
        body="Customer runbook text",
    )
    context.ingest_source_records([person, issue, doc])
    context.apply_source_changes(
        [SourceChange(operation="restrict", source_ref=doc.source_ref, reason="acl_revoked")]
    )
    context.search_context("customer meeting")
    first_job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="linear",
        job_id="job-1",
        now=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=first_job.job_id,
        connector_name="linear",
        output_state={"cursor": "2"},
        now=datetime(2026, 6, 1, 10, 1, tzinfo=UTC),
    )
    failed_job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail",
        job_id="job-2",
        now=datetime(2026, 6, 1, 11, 0, tzinfo=UTC),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=failed_job.job_id,
        error="tap failed",
        now=datetime(2026, 6, 1, 11, 2, tzinfo=UTC),
    )
    invalid_job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail",
        job_id="job-3",
        now=datetime(2026, 6, 1, 11, 5, tzinfo=UTC),
    )
    mark_connector_job_invalid(
        state.engine,
        state.connector_job_runs,
        job_id=invalid_job.job_id,
        error="malformed payload",
        raw_output_ref=".local/bad-gmail.jsonl",
        now=datetime(2026, 6, 1, 11, 6, tzinfo=UTC),
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-linear-1",
            source_system="linear",
            source_object_id="OPS-1",
            event_type="issue.updated",
            operation="upsert",
            payload={"source_ref": "linear:issue:OPS-1"},
        ),
        now=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )

    report = operator_dashboard(state)

    assert report["source_records"] == {
        "total": 3,
        "by_source_system": {"google_drive": 1, "linear": 2},
        "by_record_type": {"document": 1, "person": 1, "work_item": 1},
        "by_source_system_record_type": {
            "google_drive": {"document": 1},
            "linear": {"person": 1, "work_item": 1},
        },
        "by_lifecycle_state": {"active": 2, "restricted": 1},
    }
    assert report["canonical_objects"]["by_object_type"] == {
        "Document": 1,
        "Person": 1,
        "WorkItem": 1,
    }
    assert report["entity_links"]["total"] == 1
    assert report["entity_links"]["by_status"] == {"linked": 1}
    assert report["entity_links"]["linked_source_count"] == 1
    assert report["entity_links"]["link_coverage"] == 0.3333
    assert report["source_lifecycle"] == {
        "total": 1,
        "by_state": {"restricted": 1},
    }
    assert report["connectors"] == {
        "state_count": 1,
        "latest_checkpoint_at": "2026-06-01T10:01:00+00:00",
        "jobs": {
            "total": 3,
            "by_status": {"failed": 1, "invalid": 1, "succeeded": 1},
            "latest_started_at": "2026-06-01T11:05:00+00:00",
            "latest_finished_at": "2026-06-01T11:06:00+00:00",
            "recent_failure_count": 1,
            "recent_invalid_count": 1,
            "latest_failed_connector": "gmail",
            "next_retry_attempt": 0,
            "earliest_retry_at": "",
            "retry_exhausted": False,
            "recent_import_rate": {"unit": "succeeded_connector_jobs", "count": 1},
        },
    }
    assert report["webhooks"] == {
        "total": 1,
        "by_status": {"pending": 1},
        "by_source_system": {"linear": 1},
        "latest_received_at": "2026-06-01T12:00:00+00:00",
        "latest_processed_at": "",
    }
    assert report["audit"]["event_types"] == {
        "search": 1,
        "source_access": 1,
        "source_lifecycle": 1,
    }
    assert report["alerts"] == {
        "status": "needs_attention",
        "items": [
            {
                "code": "connector_failed",
                "severity": "warning",
                "count": 1,
                "threshold": "count > 0",
                "message": "Connector jobs failed recently.",
                "next_step": (
                    "Run `gcb connector-jobs` and retry due jobs with "
                    "`gcb run-imports --retry-failed` after the configured backoff."
                ),
            },
            {
                "code": "connector_invalid",
                "severity": "warning",
                "count": 1,
                "threshold": "count > 0",
                "message": "Connector jobs were rejected as malformed or unsupported.",
                "next_step": (
                    "Run `gcb connector-jobs`, inspect the raw_output_ref, then fix or "
                    "skip the malformed source payload."
                ),
            },
            {
                "code": "webhook_pending",
                "severity": "warning",
                "count": 1,
                "threshold": "count > 0",
                "message": "Webhook events are waiting to be processed.",
                "next_step": (
                    "Run `gcb webhook-events --status pending`, then process due "
                    "events with `gcb webhook-process`."
                ),
            },
        ],
    }


def test_operator_dashboard_is_empty_but_structured_for_new_state(tmp_path) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        raw_store_path=None,
    )

    report = operator_dashboard(state)

    assert report["source_records"]["total"] == 0
    assert report["entity_links"]["link_coverage"] == 0.0
    assert report["connectors"]["jobs"]["recent_import_rate"] == {
        "unit": "succeeded_connector_jobs",
        "count": 0,
    }
    assert report["connectors"]["jobs"]["latest_failed_connector"] == ""
    assert report["connectors"]["jobs"]["earliest_retry_at"] == ""
    assert report["connectors"]["jobs"]["retry_exhausted"] is False
    assert report["raw_sources"] == {
        "configured": False,
        "path": "",
        "stored_count": 0,
        "source_record_ref_count": 0,
        "source_record_refs": [],
        "unreferenced_count": 0,
    }
    assert report["webhooks"]["total"] == 0
    assert report["audit"]["total_events"] == 0
    assert report["alerts"] == {"status": "ok", "items": []}


def test_operator_dashboard_exposes_google_drive_mime_and_extraction_status(tmp_path) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="google_drive:file:image-1",
                source_system="google_drive",
                source_id="image-1",
                record_type="document",
                title="Boiler room photo",
                body="MIME type: image/png\nContent status: metadata_only",
                metadata={
                    "mime_type": "image/png",
                    "content_status": "metadata_only",
                    "export_status": "unsupported_mime_type",
                },
            ),
            SourceRecord(
                source_ref="google_drive:file:doc-1",
                source_system="google_drive",
                source_id="doc-1",
                record_type="document",
                title="Alpha notes",
                body="Alpha notes body",
                metadata={
                    "mime_type": "application/vnd.google-apps.document",
                    "content_status": "extracted",
                    "export_status": "exported_text",
                },
            ),
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )

    report = operator_dashboard(state)

    assert report["google_drive_files"] == {
        "total": 2,
        "by_mime_type": {
            "application/vnd.google-apps.document": 1,
            "image/png": 1,
        },
        "by_content_status": {
            "extracted": 1,
            "metadata_only": 1,
        },
        "by_export_status": {
            "exported_text": 1,
            "unsupported_mime_type": 1,
        },
    }


def test_operator_dashboard_exposes_slack_messages_separately_from_metadata(
    tmp_path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:user:U1",
                source_system="slack",
                source_id="U1",
                record_type="person",
                title="Olivia Example",
                body="Slack profile metadata.",
            ),
            SourceRecord(
                source_ref="slack:channel:C1",
                source_system="slack",
                source_id="C1",
                record_type="workspace_channel",
                title="#ops",
                body="Slack channel metadata.",
            ),
            SourceRecord(
                source_ref="slack:channel_member:C1:U1",
                source_system="slack",
                source_id="C1:U1",
                record_type="relationship",
                title="Channel membership",
                body="Slack membership metadata.",
            ),
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Linear issue",
                body="Work-item metadata mentioning Slack.",
            ),
            SourceRecord(
                source_ref="slack:message:C1:1717236000.000000",
                source_system="slack",
                source_id="C1:1717236000.000000",
                record_type="message",
                title="#ops",
                body="Customer Alpha asked about rollout timing.",
            ),
            SourceRecord(
                source_ref="slack:message:C1:1717236060.000000",
                source_system="slack",
                source_id="C1:1717236060.000000",
                record_type="message",
                title="#ops",
                body="Customer Beta asked about access.",
            ),
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )

    report = operator_dashboard(state)

    assert report["source_records"]["by_source_system"] == {"linear": 1, "slack": 5}
    assert report["slack_messages"] == {"active_total": 2}


def test_operator_dashboard_exposes_raw_store_location_and_source_record_refs(
    tmp_path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store_path = tmp_path / "raw-source-objects"
    context = GovernedContext(state_path, raw_store_path=raw_store_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:C123456:1717236000.000000",
                source_system="slack",
                source_id="C123456:1717236000.000000",
                record_type="message",
                title="#customer-success",
                body="Customer Alpha asked about the invoice.",
                raw={"channel_id": "C123456", "ts": "1717236000.000000"},
            )
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=raw_store_path,
    )

    report = operator_dashboard(state)

    assert report["raw_sources"] == {
        "configured": True,
        "path": str(raw_store_path),
        "stored_count": 1,
        "source_record_ref_count": 1,
        "source_record_refs": ["slack:message:C123456:1717236000.000000"],
        "unreferenced_count": 0,
    }
    assert context.source_records()[0]["raw_ref"] == ("slack:message:C123456:1717236000.000000")


def test_operator_dashboard_uses_configured_scheduler_retry_visibility(tmp_path) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail",
        job_id="failed-job",
        attempt=1,
        now=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=job.job_id,
        error="source unavailable",
        now=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )

    report = operator_dashboard(
        state,
        retry_delay_seconds=120,
        max_retry_attempts=3,
    )

    assert report["connectors"]["jobs"]["latest_failed_connector"] == "gmail"
    assert report["connectors"]["jobs"]["next_retry_attempt"] == 2
    assert report["connectors"]["jobs"]["earliest_retry_at"] == "2026-06-01T10:02:00+00:00"
    assert report["connectors"]["jobs"]["retry_exhausted"] is False


def test_operator_dashboard_marks_exhausted_connector_retries(tmp_path) -> None:
    state = create_governed_context_state(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="gmail",
        job_id="failed-job",
        attempt=3,
        now=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )
    fail_connector_job(
        state.engine,
        state.connector_job_runs,
        job_id=job.job_id,
        error="source unavailable",
        now=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
    )

    report = operator_dashboard(
        state,
        retry_delay_seconds=120,
        max_retry_attempts=3,
    )

    assert report["connectors"]["jobs"]["latest_failed_connector"] == "gmail"
    assert report["connectors"]["jobs"]["next_retry_attempt"] == 4
    assert report["connectors"]["jobs"]["earliest_retry_at"] == ""
    assert report["connectors"]["jobs"]["retry_exhausted"] is True
