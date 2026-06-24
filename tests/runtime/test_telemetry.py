from pathlib import Path

import pytest

from gcb.etl.extract.connectors import land_singer_lines
from gcb.etl.extract.document_extraction import DocumentConversionError, extract_text_layer_pdf
from gcb.etl.extract.source_records import SourceRecord
from gcb.etl.load.retrieval_records import prepare_retrieval_records
from gcb.governance import GovernedContext
from gcb.governance.state import create_governed_context_state
from gcb.retrieval.evidence_pack import build_evidence_pack
from gcb.retrieval.search import SearchResult
from gcb.runtime.dashboard import operator_dashboard
from gcb.runtime.mcp_retrieval import search_gcb
from gcb.runtime.openclaw import OpenClawMessage, openclaw_messages_to_source_records
from gcb.runtime.source_imports import import_source_records
from gcb.runtime.webhooks import WebhookEventInput, enqueue_webhook_event


class FakeSpan:
    def __init__(self, name: str, spans: list[dict[str, object]]) -> None:
        self.name = name
        self.spans = spans
        self.attributes: dict[str, object] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.spans.append({"name": self.name, "attributes": self.attributes})

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value


class FakeTracer:
    def __init__(self, spans: list[dict[str, object]]) -> None:
        self.spans = spans

    def start_as_current_span(self, name: str) -> FakeSpan:
        return FakeSpan(name, self.spans)


def test_search_context_emits_safe_search_and_evidence_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    metrics: list[tuple[str, float, dict[str, object]]] = []
    monkeypatch.setattr(
        "gcb.governance.context.record_counter",
        lambda name, value=1, attributes=None: metrics.append((name, value, attributes or {})),
    )
    monkeypatch.setattr(
        "gcb.governance.context.record_histogram",
        lambda name, value, attributes=None: metrics.append((name, value, attributes or {})),
    )
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Robin renewal",
                body="Robin renewal meeting is on Thursday.",
            )
        ]
    )
    monkeypatch.setattr("gcb.governance.context.trace.get_tracer", lambda _name: FakeTracer(spans))

    response = context.search_context("Robin renewal", limit=1)

    assert response.results
    assert spans == [
        {
            "name": "gcb.evidence_pack.build",
            "attributes": {
                "gcb.evidence_pack.result_count": 1,
                "gcb.evidence_pack.source_record_count": 1,
                "gcb.evidence_pack.canonical_object_count": 1,
                "gcb.evidence_pack.entity_link_count": 0,
                "gcb.evidence_pack.evidence_item_count": 1,
                "gcb.evidence_pack.related_object_count": 0,
                "gcb.evidence_pack.unresolved_candidate_count": 0,
                "gcb.evidence_pack.limitation_count": 1,
            },
        },
        {
            "name": "gcb.search_context",
            "attributes": {
                "gcb.search.limit": 1,
                "gcb.search.query_length": 13,
                "gcb.search.denied_source_count": 0,
                "gcb.search.result_count": 1,
                "gcb.search.evidence_item_count": 1,
                "gcb.search.audit_recorded": True,
            },
        },
    ]
    assert "Robin renewal" not in str(spans)
    assert "meeting is on Thursday" not in str(spans)
    assert ("gcb_search_requests_total", 1, {"status": "succeeded"}) in metrics
    assert ("gcb_search_results", 1, {}) in metrics
    assert any(name == "gcb_search_duration_seconds" for name, _value, _attrs in metrics)


def test_retrieval_preparation_emits_safe_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr(
        "gcb.etl.load.retrieval_records.trace.get_tracer",
        lambda _name: FakeTracer(spans),
    )

    rows = prepare_retrieval_records(
        [
            SourceRecord(
                source_ref="docs:policy:1",
                source_system="google_drive",
                source_id="policy-1",
                record_type="document",
                title="Policy",
                body=" ".join(f"word{index}" for index in range(12)),
            )
        ],
        max_words=6,
        overlap_words=2,
    )

    assert len(rows) == 3
    assert spans == [
        {
            "name": "gcb.retrieval.prepare",
            "attributes": {
                "gcb.source_record.count": 1,
                "gcb.retrieval.unit_count": 3,
                "gcb.retrieval.max_words": 6,
                "gcb.retrieval.overlap_words": 2,
            },
        }
    ]
    assert "word11" not in str(spans)


def test_raw_landing_emits_safe_success_span(monkeypatch, tmp_path: Path) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.observability.trace.get_tracer", lambda _name: FakeTracer(spans))

    report = land_singer_lines(
        [
            '{"type":"SCHEMA","stream":"email_messages","schema":{}}',
            (
                '{"type":"RECORD","stream":"email_messages",'
                '"record":{"id":"msg-1","body":"private body"}}'
            ),
            '{"type":"STATE","value":{"bookmark":"secret-state-value"}}',
        ],
        tmp_path / "landing",
    )

    assert report.record_count == 1
    assert spans == [
        {
            "name": "gcb.raw_landing.write",
            "attributes": {
                "gcb.raw_landing.status": "succeeded",
                "gcb.raw_landing.record_count": 1,
                "gcb.raw_landing.stream_count": 1,
                "gcb.raw_landing.schema_message_count": 1,
                "gcb.raw_landing.state_message_count": 1,
            },
        }
    ]
    assert "private body" not in str(spans)
    assert "secret-state-value" not in str(spans)
    assert str(tmp_path) not in str(spans)


def test_raw_landing_failure_span_keeps_payload_out(monkeypatch, tmp_path: Path) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.observability.trace.get_tracer", lambda _name: FakeTracer(spans))

    with pytest.raises(ValueError, match="Invalid Singer JSON"):
        land_singer_lines(['{"private_payload":'], tmp_path / "landing")

    assert spans == [
        {
            "name": "gcb.raw_landing.write",
            "attributes": {
                "gcb.raw_landing.status": "failed",
                "gcb.error.class": "ValueError",
            },
        }
    ]
    assert "private_payload" not in str(spans)
    assert str(tmp_path) not in str(spans)


def test_document_extraction_emits_safe_failure_span(monkeypatch, tmp_path: Path) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.observability.trace.get_tracer", lambda _name: FakeTracer(spans))
    document_path = tmp_path / "customer-secret.pdf"
    document_path.write_text("not a pdf", encoding="utf-8")

    with pytest.raises(DocumentConversionError):
        extract_text_layer_pdf(document_path)

    assert spans == [
        {
            "name": "gcb.document.extract",
            "attributes": {
                "gcb.document.extractor": "pypdf_text_layer",
                "gcb.document.extension": ".pdf",
                "gcb.document.status": "failed",
                "gcb.error.class": "DocumentConversionError",
            },
        }
    ]
    assert "customer-secret" not in str(spans)
    assert str(tmp_path) not in str(spans)


def test_source_record_ingest_emits_safe_import_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    context = GovernedContext()
    monkeypatch.setattr("gcb.governance.context.trace.get_tracer", lambda _name: FakeTracer(spans))

    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Sensitive renewal title",
                body="Sensitive renewal body.",
            ),
            SourceRecord(
                source_ref="gmail:message:1",
                source_system="gmail",
                source_id="message-1",
                record_type="message",
                title="Customer message",
                body="Customer message body.",
            ),
        ]
    )

    assert spans == [
        {
            "name": "gcb.retrieval.prepare",
            "attributes": {
                "gcb.source_record.count": 2,
                "gcb.retrieval.unit_count": 2,
                "gcb.retrieval.max_words": 900,
                "gcb.retrieval.overlap_words": 100,
            },
        },
        {
            "name": "gcb.source_records.ingest",
            "attributes": {
                "gcb.source_record.count": 2,
                "gcb.source_record.source_systems": "gmail,linear",
                "gcb.source_record.record_types": "message,work_item",
                "gcb.source_record.status": "succeeded",
            },
        },
    ]
    assert "Sensitive renewal" not in str(spans)
    assert "linear:issue:OPS-1" not in str(spans)


def test_source_record_import_emits_safe_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.observability.trace.get_tracer", lambda _name: FakeTracer(spans))
    importer = GovernedContext()

    report = import_source_records(
        importer,
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Sensitive title",
                body="Sensitive body.",
            )
        ],
    )

    assert report.record_count == 1
    assert spans[-1] == {
        "name": "gcb.source_records.import",
        "attributes": {
            "gcb.source_record.status": "succeeded",
            "gcb.source_record.count": 1,
            "gcb.source_record.source_systems": "linear",
            "gcb.source_record.record_types": "work_item",
            "gcb.source_record.restricted_count": 0,
            "gcb.retrieval.unit_count": 1,
        },
    }
    assert "Sensitive body" not in str(spans)
    assert "linear:issue:OPS-1" not in str(spans)


def test_mcp_search_emits_safe_success_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.observability.trace.get_tracer", lambda _name: FakeTracer(spans))
    context = GovernedContext()
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Sensitive renewal",
                body="Sensitive customer renewal body.",
            )
        ]
    )

    response = search_gcb(
        query="Sensitive renewal",
        state="private-state.sqlite",
        database_url="postgresql+psycopg://gcb:secret@localhost:5432/gcb",
        context_factory=lambda *args, **kwargs: context,
    )

    assert response["results"]
    assert spans[-1] == {
        "name": "gcb.mcp.search",
        "attributes": {
            "gcb.mcp.tool": "search_gcb",
            "gcb.mcp.status": "succeeded",
            "gcb.search.limit": 5,
            "gcb.search.query_length": 17,
            "gcb.search.result_count": 1,
            "gcb.search.evidence_item_count": 1,
        },
    }
    assert "Sensitive renewal" not in str(spans)
    assert "private-state" not in str(spans)
    assert "secret" not in str(spans)


def test_mcp_search_failure_span_keeps_query_and_state_out(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.observability.trace.get_tracer", lambda _name: FakeTracer(spans))

    with pytest.raises(ValueError, match="query is required"):
        search_gcb(query="   ", state="private-state.sqlite")

    assert spans == [
        {
            "name": "gcb.mcp.search",
            "attributes": {
                "gcb.mcp.tool": "search_gcb",
                "gcb.mcp.status": "failed",
                "gcb.error.class": "ValueError",
            },
        }
    ]
    assert "private-state" not in str(spans)


def test_dashboard_emits_safe_status_span(monkeypatch, tmp_path: Path) -> None:
    spans: list[dict[str, object]] = []
    state_path = tmp_path / "state.sqlite"
    GovernedContext(state_path).ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:OPS-1",
                source_system="linear",
                source_id="OPS-1",
                record_type="work_item",
                title="Dashboard issue",
                body="Dashboard issue.",
            )
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-dashboard-1",
            source_system="linear",
            event_type="issue.updated",
            operation="upsert",
            payload={"source_ref": "linear:issue:OPS-1"},
        ),
    )
    monkeypatch.setattr("gcb.runtime.dashboard.trace.get_tracer", lambda _name: FakeTracer(spans))

    report = operator_dashboard(state)

    assert report["source_records"]["total"] == 1
    assert report["webhooks"]["by_status"] == {"pending": 1}
    assert spans == [
        {
            "name": "gcb.dashboard",
            "attributes": {
                "gcb.dashboard.source_record_count": 1,
                "gcb.dashboard.connector_job_count": 0,
                "gcb.dashboard.webhook_backlog_count": 1,
                "gcb.dashboard.slack_message_count": 0,
                "gcb.dashboard.audit_event_count": 0,
                "gcb.dashboard.alert_count": 1,
                "gcb.dashboard.alert_status": "needs_attention",
            },
        }
    ]


def test_evidence_pack_build_emits_safe_assembly_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr(
        "gcb.retrieval.evidence_pack.trace.get_tracer",
        lambda _name: FakeTracer(spans),
    )

    pack = build_evidence_pack(
        query="Robin sensitive meeting",
        results=[
            SearchResult(
                source_ref="linear:issue:OPS-1",
                subject="Sensitive title",
                date="2026-06-01T12:00:00+00:00",
                snippet="Sensitive snippet",
            )
        ],
        source_records=[
            {
                "source_ref": "linear:issue:OPS-1",
                "source_system": "linear",
                "source_id": "OPS-1",
                "record_type": "work_item",
                "source_url": "https://linear.example/OPS-1",
                "updated_at": "2026-06-01T12:00:00+00:00",
                "permission_refs": "[]",
                "thread_ref": "linear:thread:OPS-1",
            }
        ],
        canonical_objects=[
            {
                "object_ref": "linear:issue:OPS-1",
                "object_type": "WorkItem",
                "title": "Sensitive title",
                "source_refs": '["linear:issue:OPS-1"]',
            }
        ],
        entity_links=[],
    )

    assert len(pack["evidence_items"]) == 1
    assert spans == [
        {
            "name": "gcb.evidence_pack.build",
            "attributes": {
                "gcb.evidence_pack.result_count": 1,
                "gcb.evidence_pack.source_record_count": 1,
                "gcb.evidence_pack.canonical_object_count": 1,
                "gcb.evidence_pack.entity_link_count": 0,
                "gcb.evidence_pack.evidence_item_count": 1,
                "gcb.evidence_pack.related_object_count": 0,
                "gcb.evidence_pack.unresolved_candidate_count": 0,
                "gcb.evidence_pack.limitation_count": 1,
            },
        }
    ]
    assert "Robin sensitive" not in str(spans)
    assert "Sensitive snippet" not in str(spans)


def test_openclaw_capture_emits_safe_span(monkeypatch) -> None:
    spans: list[dict[str, object]] = []
    monkeypatch.setattr("gcb.runtime.openclaw.trace.get_tracer", lambda _name: FakeTracer(spans))

    records = openclaw_messages_to_source_records(
        [
            OpenClawMessage(
                session_id="session-1",
                agent_id="agent:claw",
                sender_id="user:olivia",
                role="user",
                content="Please remember the Robin Scharf renewal meeting.",
                timestamp="2026-06-01T12:00:00+00:00",
                provider="openai",
                message_index=1,
            )
        ]
    )

    assert len(records) == 1
    assert spans == [
        {
            "name": "gcb.openclaw.capture",
            "attributes": {
                "gcb.openclaw.message_count": 1,
                "gcb.openclaw.record_count": 1,
                "gcb.openclaw.session_count": 1,
            },
        }
    ]
    assert "Robin Scharf" not in str(spans)
