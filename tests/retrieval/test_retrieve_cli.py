from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from fourok.cli import main
from fourok.etl.extract.source_records import SourceIdentity, SourceRecord
from fourok.etl.load.context_objects import store_entity_links
from fourok.governance import GovernedContext
from fourok.retrieval.augmentation import _source_date_label


class _FakeRetrievalSpan:
    def __init__(self, name: str, spans: list[dict[str, object]]) -> None:
        self._name = name
        self._spans = spans
        self._attributes: dict[str, object] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._spans.append({"name": self._name, "attributes": self._attributes})

    def set_attribute(self, key: str, value: object) -> None:
        self._attributes[key] = value


class _FakeRetrievalTracer:
    def __init__(self, spans: list[dict[str, object]]) -> None:
        self._spans = spans

    def start_as_current_span(self, name: str) -> _FakeRetrievalSpan:
        return _FakeRetrievalSpan(name, self._spans)


def _seed_state(state: Path) -> None:
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:cancellation",
                source_system="slack-live",
                source_id="cancellation",
                record_type="message",
                title="#customer-success",
                body=(
                    "Customer asked whether the cancellation invoice was final "
                    "and who owns follow-up."
                ),
                occurred_at="2026-06-10T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:onboarding",
                source_system="linear-live",
                source_id="onboarding",
                record_type="issue",
                title="Improve onboarding checklist",
                body="Internal task about onboarding documents and setup flow.",
                occurred_at="2026-06-09T09:00:00+00:00",
            ),
        ]
    )
    context.build_vector_index()


def test_retrieve_rejects_limit_option(monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "retrieve", "query", "--limit", "2"],
    )

    with pytest.raises(SystemExit):
        main()


def test_retrieve_loads_embedding_env_from_dotenv_before_retrieval(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("OPENAI_API_KEY=test-key\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("FOUROK_EMBEDDING_PROVIDER", raising=False)
    monkeypatch.delenv("FOUROK_EMBEDDING_DIMENSIONS", raising=False)
    observed = {}

    def fake_retrieve_augmentation(*_args, **_kwargs):
        from fourok.retrieval.embeddings import embedding_dimensions, embedding_provider

        observed["provider"] = embedding_provider()
        observed["dimensions"] = embedding_dimensions()
        return {"status": "ok", "results": [], "limitations": []}

    monkeypatch.setattr(
        "fourok.retrieval.cli.retrieval_client.retrieve_augmentation",
        fake_retrieve_augmentation,
    )
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "retrieve", "olivia", "--json"],
    )

    main()

    output = capsys.readouterr().out
    for key in (
        "OPENAI_API_KEY",
        "FOUROK_EMBEDDING_PROVIDER",
        "FOUROK_EMBEDDING_DIMENSIONS",
    ):
        os.environ.pop(key, None)

    assert json.loads(output)["status"] == "ok"
    assert observed == {"provider": "openai", "dimensions": 256}


def test_retrieve_emits_stage_spans_for_tempo(monkeypatch, tmp_path: Path) -> None:
    spans: list[dict[str, object]] = []
    context = GovernedContext(tmp_path / "state.sqlite")
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:olivia",
                source_system="linear-live",
                source_id="olivia",
                record_type="issue",
                title="Olivia rollout owner",
                body="Olivia owns the rollout follow-up and launch checklist.",
                occurred_at="2026-06-10T12:00:00+00:00",
            )
        ]
    )
    monkeypatch.setattr(
        "fourok.retrieval.augmentation.trace.get_tracer",
        lambda _name: _FakeRetrievalTracer(spans),
    )

    response = context.retrieve_augmentation(
        "olivia rollout", candidate_limit=5, retrievers=("keyword",)
    )

    span_by_name = {str(span["name"]): span["attributes"] for span in spans}
    assert response.results
    assert {
        "fourok.retrieve",
        "fourok.retrieve.keyword",
        "fourok.retrieve.graph_link_metrics",
        "fourok.retrieve.rerank",
        "fourok.retrieve.token_pack",
    }.issubset(span_by_name)
    assert "fourok.retrieve.direct_link_expand" not in span_by_name
    assert span_by_name["fourok.retrieve.keyword"]["fourok.retrieve.query_length"] == len(
        "olivia rollout"
    )
    assert span_by_name["fourok.retrieve.keyword"]["fourok.retrieve.keyword_candidates"] == 1
    assert span_by_name["fourok.retrieve.token_pack"]["fourok.retrieve.returned_results"] == len(
        response.results
    )


def test_retrieve_defaults_to_token_budget_not_item_limit(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=f"slack:message:token-budget:{index}",
                source_system="slack-live",
                source_id=f"token-budget-{index}",
                record_type="message",
                title=f"Token budget result {index}",
                body=f"token budget sentinel answer evidence {index}",
                occurred_at="2026-06-10T12:00:00+00:00",
            )
            for index in range(6)
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "retrieve", "token budget sentinel answer", "--state", str(state)],
    )

    main()

    output = capsys.readouterr().out
    assert output.count("source_ref: slack:message:token-budget:") == 6


def test_retrieve_respects_explicit_token_budget(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=f"slack:message:budget-stop:{index}",
                source_system="slack-live",
                source_id=f"budget-stop-{index}",
                record_type="message",
                title=f"Budget stop result {index}",
                body=(
                    "budget stop sentinel evidence "
                    + "substantial context paragraph " * 12
                    + str(index)
                ),
                occurred_at="2026-06-10T12:00:00+00:00",
            )
            for index in range(4)
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "budget stop sentinel evidence",
            "--state",
            str(state),
            "--token-budget",
            "160",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert output.count("source_ref: slack:message:budget-stop:") == 1
    assert "Budget: " in output


def test_retrieve_formats_source_dates_for_agent_time_reasoning() -> None:
    now = datetime(2026, 6, 24, 14, 10, tzinfo=UTC)

    assert _source_date_label("2026-06-01T14:08:35.162Z", now=now) == ("23 days ago (2026-06-01)")
    assert _source_date_label("2026-06-24T08:00:00+00:00", now=now) == ("today (2026-06-24)")
    assert _source_date_label("", now=now) == "unknown"


def test_retrieve_prints_llm_ready_augmentation_block(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "cancellation invoice follow-up",
            "--state",
            str(state),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert output.startswith("fourok RETRIEVAL FOR AGENTS\n")
    assert "How to use this: Answer from these evidence cards only when relevant." in output
    assert "Open decisive source_ref values with fourok.open" in output
    assert "cancellation invoice follow-up" not in output
    assert "[1] Slack-Live message — #customer-success" in output
    assert "source_ref: slack:message:cancellation" in output
    assert "permission_refs:" not in output
    assert "evidence: Customer asked whether the cancellation invoice was final" in output
    assert "Retrieval notes:" in output
    assert "Results are source excerpts, not a final answer." in output


def test_retrieve_rewrites_container_database_url_for_host_cli(capsys, monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    def fake_retrieve_block(*_args, **kwargs):
        captured["database_url"] = kwargs["database_url"]
        return "ok\n"

    monkeypatch.setenv(
        "FOUROK_DATABASE_URL",
        "postgresql+psycopg://fourok:local-check@postgres:5432/fourok",
    )
    monkeypatch.setattr("fourok.retrieval.cli._running_in_container", lambda: False)
    monkeypatch.setattr("fourok.retrieval.clients.cli.retrieve_block", fake_retrieve_block)
    monkeypatch.setattr("sys.argv", ["fourok", "retrieve", "refund"])

    main()

    assert capsys.readouterr().out == "ok\n"
    assert captured["database_url"] == (
        "postgresql+psycopg://fourok:local-check@127.0.0.1:5432/fourok"
    )


def test_retrieve_uses_same_default_runtime_database_as_status(capsys, monkeypatch) -> None:
    captured: dict[str, str | None] = {}

    def fake_retrieve_block(*_args, **kwargs):
        captured["database_url"] = kwargs["database_url"]
        return "ok\n"

    monkeypatch.delenv("FOUROK_DATABASE_URL", raising=False)
    monkeypatch.setattr(
        "fourok.retrieval.cli.health_database_url",
        lambda **_kwargs: "postgresql+psycopg://fourok:local-check@127.0.0.1:5432/fourok",
    )
    monkeypatch.setattr("fourok.retrieval.clients.cli.retrieve_block", fake_retrieve_block)
    monkeypatch.setattr("sys.argv", ["fourok", "retrieve", "refund"])

    main()

    assert capsys.readouterr().out == "ok\n"
    assert captured["database_url"] == (
        "postgresql+psycopg://fourok:local-check@127.0.0.1:5432/fourok"
    )


def test_retrieve_json_returns_stable_machine_shape_without_echoing_query(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "cancellation invoice follow-up",
            "--state",
            str(state),
            "--format",
            "json",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert "query" not in output
    assert output["status"] == "ok"
    assert output["context_block"].startswith("fourok RETRIEVAL FOR AGENTS\n")
    result = output["results"][0]
    assert result["rank"] == 1
    assert result["retrieval_event_id"].startswith("retrieval-query:")
    assert result == {
        "source_ref": "slack:message:cancellation",
        "source_system": "slack-live",
        "record_type": "message",
        "title": "#customer-success",
        "occurred_at": "2026-06-10T12:00:00+00:00",
        "snippet": (
            "Customer asked whether the cancellation invoice was final and who owns follow-up."
        ),
        "score": result["score"],
        "retrievers": result["retrievers"],
        "permission_refs": [],
        "rerank_reasons": ["specific source excerpt"],
        "rank": 1,
        "retrieval_event_id": result["retrieval_event_id"],
    }
    assert set(result["retrievers"]) >= {"keyword"}
    assert output["limitations"]


def test_retrieve_records_privacy_safe_request_observability(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "cancellation invoice follow-up",
            "--state",
            str(state),
            "--candidate-limit",
            "10",
        ],
    )

    main()
    capsys.readouterr()

    with sqlite3.connect(state) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("select * from retrieval_query_events").fetchone()
        result_rows = connection.execute(
            "select * from retrieval_result_events order by rank"
        ).fetchall()
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["retriever_set"] == "keyword,vector"
    assert row["requested_limit"] == 2000
    assert row["candidate_limit"] == 10
    assert row["pre_rerank_candidates"] >= row["returned_results"] >= 1
    assert row["distinct_sources"] >= 1
    assert row["duration_ms"] >= 0
    assert "query" not in row.keys()
    assert result_rows
    assert result_rows[0]["retrieval_query_event_id"] == row["event_id"]
    assert result_rows[0]["rank"] == 1
    assert result_rows[0]["source_ref"] == "slack:message:cancellation"
    assert result_rows[0]["source_system"] == "slack-live"
    assert result_rows[0]["record_type"] == "message"
    assert "query" not in result_rows[0].keys()


def test_open_infers_retrieval_rank_from_event_id(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "cancellation invoice follow-up",
            "--state",
            str(state),
            "--format",
            "json",
        ],
    )

    main()
    retrieve_output = json.loads(capsys.readouterr().out)
    result = retrieve_output["results"][0]
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "open",
            result["source_ref"],
            "--retrieval-event-id",
            retrieve_output["retrieval_event_id"],
            "--state",
            str(state),
        ],
    )

    main()
    open_output = json.loads(capsys.readouterr().out)

    assert open_output["status"] == "ok"
    with sqlite3.connect(state) as connection:
        connection.row_factory = sqlite3.Row
        inspection_row = connection.execute(
            "select * from retrieval_inspection_events"
        ).fetchone()
    assert inspection_row is not None
    assert inspection_row["retrieval_query_event_id"] == retrieve_output["retrieval_event_id"]
    assert inspection_row["source_ref"] == result["source_ref"]
    assert inspection_row["rank"] == result["rank"]


def test_retrieve_vector_snippet_does_not_repeat_title(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:duplicate-title",
                source_system="linear",
                source_id="duplicate-title",
                record_type="work_item",
                title="linkedin outreach 10 inmail exact icp",
                body=(
                    "linkedin outreach 10 inmail exact icp fourok-385 "
                    "Jespers booking link and ICP outreach draft."
                ),
                occurred_at="2026-05-11T09:12:49.085Z",
            )
        ]
    )
    context.build_vector_index()
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "booking link ICP outreach",
            "--state",
            str(state),
            "--retrievers",
            "vector",
        ],
    )

    main()

    output = capsys.readouterr().out
    repeated_title = "linkedin outreach 10 inmail exact icp\nlinkedin outreach 10 inmail exact icp"
    assert repeated_title not in output
    assert "[1] Linear work item — linkedin outreach 10 inmail exact icp" in output
    assert "evidence: fourok-385 Jespers booking link" in output


def test_retrieve_removes_source_id_and_title_prefix_from_evidence(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:4OK-385",
                source_system="linear",
                source_id="4OK-385",
                record_type="work_item",
                title="LinkedIn outreach draft",
                body=(
                    "4OK-385 LinkedIn outreach draft "
                    "Jespers booking link and ICP outreach instructions."
                ),
                occurred_at="2026-05-11T09:12:49.085Z",
            )
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "booking link ICP outreach",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "evidence: Jespers booking link and ICP outreach instructions." in output
    assert "evidence: 4OK-385 LinkedIn outreach draft" not in output


def test_retrieve_collapses_evidence_paragraph_boundaries(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:paragraph-context",
                source_system="slack-live",
                source_id="paragraph-context",
                record_type="message",
                title="Launch note",
                body=(
                    "First paragraph says retrieval paragraph context is important.\n\n"
                    "Second paragraph keeps the concrete next action separate."
                ),
                occurred_at="2026-06-24T09:00:00+00:00",
            )
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "retrieval paragraph context",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "evidence: First paragraph says retrieval paragraph context is important." in output
    assert "Second paragraph keeps the concrete next action separate." in output
    assert "evidence:\nFirst paragraph" not in output
    assert "\n\nSecond paragraph" not in output


def test_retrieve_renders_escaped_newlines_as_readable_text(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:escaped-newlines",
                source_system="linear",
                source_id="escaped-newlines",
                record_type="work_item",
                title="Escaped newline note",
                body="escaped newline evidence first line\\n\\nsecond line action item",
                occurred_at="2026-06-24T09:00:00+00:00",
            )
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "escaped newline evidence",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "\\n" not in output
    assert "evidence: escaped newline evidence first line" in output
    assert "second line action item" in output
    assert "evidence:\nescaped newline evidence first line" not in output
    assert "\n\nsecond line action item" not in output


def test_retrieve_centers_evidence_snippet_on_query_terms(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="twenty:person:simon",
                source_system="twenty",
                source_id="simon",
                record_type="person",
                title="Simon Pawlitzky",
                body=(
                    "Developer Advocate. "
                    + "generic CRM metadata without task evidence. " * 18
                    + "The useful evidence says the runtime deployment decision "
                    "belongs with the fourok OpenClaw rollout notes."
                ),
                occurred_at="2026-06-15T12:00:00+00:00",
            )
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "runtime deployment decision",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "evidence: Developer Advocate." not in output
    assert "runtime deployment decision belongs with the fourok OpenClaw rollout notes" in output


def test_retrieve_keeps_keyword_thread_hits_without_graph_expansion(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:alpha-plan",
                source_system="linear",
                source_id="alpha-plan",
                record_type="work_item",
                title="Alpha launch plan",
                body="alpha launch plan zephyr decision and rollout checklist",
                occurred_at="2026-06-20T12:00:00+00:00",
                thread_ref="linear:issue:alpha-plan",
                metadata={"assignee_id": "person-1"},
            ),
            SourceRecord(
                source_ref="linear:comment:alpha-budget",
                source_system="linear",
                source_id="alpha-budget",
                record_type="message",
                title="Comment on rollout budget",
                body="Budget follow-up says the rollout needs Finance approval.",
                occurred_at="2026-06-21T12:00:00+00:00",
                thread_ref="linear:issue:alpha-plan",
            ),
            SourceRecord(
                source_ref="linear:user:person-1",
                source_system="linear",
                source_id="person-1",
                record_type="person",
                title="Casey Holder",
                body="Casey Holder is accountable for approval routing.",
                occurred_at="2026-06-19T12:00:00+00:00",
                source_identities=(
                    SourceIdentity(
                        source_system="linear",
                        identity_ref="linear:email:alex@example.com",
                        identity_type="email",
                        value="alex@example.com",
                        display_name="Casey Holder",
                    ),
                ),
            ),
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "alpha launch plan zephyr decision",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "source_ref: linear:issue:alpha-plan" in output
    assert "source_ref: linear:comment:alpha-budget" in output
    assert "Budget follow-up says the rollout needs Finance approval." in output
    assert "Linear person — Casey Holder" not in output
    assert "is accountable for approval routing." not in output


def test_retrieve_does_not_fan_out_from_weak_identity_seed(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    monkeypatch.setattr(
        "fourok.etl.load.source_changes.entity_links_from_source_records", lambda _records: []
    )
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:user:olivia",
                source_system="linear-live",
                source_id="olivia",
                record_type="person",
                title="olivia.allen@4ok.tech",
                body="olivia.allen@4ok.tech employee",
                occurred_at="2026-06-10T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:unrelated",
                source_system="linear-live",
                source_id="unrelated",
                record_type="work_item",
                title="Internal storage cleanup",
                body="Unrelated work linked only through the employee identity node.",
                occurred_at="2026-06-10T12:00:00+00:00",
            ),
        ]
    )
    store_entity_links(
        context._engine,
        context._entity_links,
        links=[
            {
                "link_ref": "linear:issue:unrelated->linear:user:olivia",
                "source_ref": "linear:issue:unrelated",
                "object_ref": "linear:user:olivia",
                "relationship_type": "assignee",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            }
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "olivia",
            "--state",
            str(state),
            "--json",
            "--retrievers",
            "keyword",
            "--token-budget",
            "4000",
        ],
    )

    main()

    response = json.loads(capsys.readouterr().out)
    source_refs = {result["source_ref"] for result in response["results"]}
    assert "linear:user:olivia" in source_refs
    assert "linear:issue:unrelated" not in source_refs


def test_retrieve_json_includes_people_buckets_for_direct_and_related_people(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:user:olivia",
                source_system="linear",
                source_id="olivia",
                record_type="person",
                title="Olivia Allen",
                body="olivia.allen@example.invalid employee",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:user:olivia-ops",
                source_system="linear",
                source_id="olivia-ops",
                record_type="person",
                title="Olivia Ops",
                body="olivia.ops@example.invalid employee",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:user:lukas",
                source_system="linear",
                source_id="lukas",
                record_type="person",
                title="Lukas Meyer",
                body="lukas.meyer@example.invalid employee",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:olivia-launch",
                source_system="linear",
                source_id="olivia-launch",
                record_type="work_item",
                title="Olivia launch checklist",
                body="Olivia launch owner evidence for the rollout.",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
        ]
    )
    store_entity_links(
        context._engine,
        context._entity_links,
        links=[
            {
                "link_ref": "issue->lukas",
                "source_ref": "linear:issue:olivia-launch",
                "object_ref": "linear:user:lukas",
                "relationship_type": "commenter",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            }
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "olivia",
            "--state",
            str(state),
            "--format",
            "json",
            "--retrievers",
            "keyword",
            "--token-budget",
            "4000",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    people = output["people"]
    possible_refs = {person["source_ref"] for person in people["possible_query_matches"]}
    related_refs = {person["source_ref"] for person in people["related_people"]}
    assert possible_refs == {"linear:user:olivia", "linear:user:olivia-ops"}
    assert all(person["reason"] == "matched_name" for person in people["possible_query_matches"])
    assert "linear:user:lukas" in related_refs
    assert "linear:user:lukas" not in possible_refs
    related = next(
        person for person in people["related_people"] if person["source_ref"] == "linear:user:lukas"
    )
    assert related == {
        "source_ref": "linear:user:lukas",
        "name": "Lukas Meyer",
        "source_system": "linear",
        "reason": "commented_on_same_thread",
        "related_to": "linear:issue:olivia-launch",
    }


def test_retrieve_block_renders_people_buckets_as_compact_hints(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:user:olivia",
                source_system="linear",
                source_id="olivia",
                record_type="person",
                title="Olivia Allen",
                body="olivia.allen@example.invalid employee",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:user:lukas",
                source_system="linear",
                source_id="lukas",
                record_type="person",
                title="Lukas Meyer",
                body="lukas.meyer@example.invalid employee",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:olivia-launch",
                source_system="linear",
                source_id="olivia-launch",
                record_type="work_item",
                title="Olivia launch checklist",
                body="Olivia launch owner evidence for the rollout.",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
        ]
    )
    store_entity_links(
        context._engine,
        context._entity_links,
        links=[
            {
                "link_ref": "issue->lukas",
                "source_ref": "linear:issue:olivia-launch",
                "object_ref": "linear:user:lukas",
                "relationship_type": "commenter",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            }
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "olivia",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
            "--token-budget",
            "4000",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "People:" in output
    assert output.index("People:") < output.index("[1]")
    assert "Possible query matches:" in output
    assert "- Olivia Allen (matched_name) source_ref: linear:user:olivia" in output
    assert "Related people hints:" in output
    assert (
        "- Lukas Meyer (commented_on_same_thread; related_to: linear:issue:olivia-launch) "
        "source_ref: linear:user:lukas"
    ) in output


def test_retrieve_json_includes_bounded_related_follow_up_hints(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:apollo-plan",
                source_system="linear",
                source_id="apollo-plan",
                record_type="work_item",
                title="Apollo rollout plan",
                body="apollo rollout zephyr evidence for the launch owner decision.",
                occurred_at="2026-06-20T12:00:00+00:00",
                thread_ref="linear:issue:apollo-plan",
            ),
            SourceRecord(
                source_ref="linear:comment:apollo-budget",
                source_system="linear",
                source_id="apollo-budget",
                record_type="message",
                title="Budget approval comment",
                body="Budget approval follow-up should be checked after launch owner evidence.",
                occurred_at="2026-06-21T12:00:00+00:00",
                thread_ref="linear:issue:apollo-plan",
            ),
            SourceRecord(
                source_ref="linear:comment:apollo-budget-checklist",
                source_system="linear",
                source_id="apollo-budget-checklist",
                record_type="message",
                title="Budget approval checklist",
                body="Budget approval checklist is in the same thread cluster.",
                occurred_at="2026-06-21T11:00:00+00:00",
                thread_ref="linear:issue:apollo-plan",
            ),
            SourceRecord(
                source_ref="linear:issue:apollo-legal",
                source_system="linear",
                source_id="apollo-legal",
                record_type="work_item",
                title="Apollo legal review",
                body="Legal review follow-up for the apollo rollout zephyr launch.",
                occurred_at="2026-06-21T10:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:generic-unrelated-hub",
                source_system="linear",
                source_id="generic-unrelated-hub",
                record_type="work_item",
                title="Generic unrelated hub",
                body="generic hub with many unrelated links.",
                occurred_at="2026-06-19T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:other-1",
                source_system="linear",
                source_id="other-1",
                record_type="work_item",
                title="Other linked one",
                body="Other linked work.",
                occurred_at="2026-06-18T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:other-2",
                source_system="linear",
                source_id="other-2",
                record_type="work_item",
                title="Other linked two",
                body="Other linked work.",
                occurred_at="2026-06-17T12:00:00+00:00",
            ),
        ]
    )
    store_entity_links(
        context._engine,
        context._entity_links,
        links=[
            {
                "link_ref": "plan->legal",
                "source_ref": "linear:issue:apollo-plan",
                "object_ref": "linear:issue:apollo-legal",
                "relationship_type": "relates_to",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            },
            {
                "link_ref": "hub->one",
                "source_ref": "linear:issue:generic-unrelated-hub",
                "object_ref": "linear:issue:other-1",
                "relationship_type": "relates_to",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            },
            {
                "link_ref": "hub->two",
                "source_ref": "linear:issue:generic-unrelated-hub",
                "object_ref": "linear:issue:other-2",
                "relationship_type": "relates_to",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            },
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "apollo rollout zephyr",
            "--state",
            str(state),
            "--format",
            "json",
            "--retrievers",
            "keyword",
            "--token-budget",
            "80",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    selected_refs = {result["source_ref"] for result in output["results"]}
    hints = output["you_could_also_be_interested_in"]
    hint_refs = {hint["source_ref"] for hint in hints}
    assert "linear:issue:apollo-plan" in selected_refs
    thread_hint_refs = {
        "linear:comment:apollo-budget",
        "linear:comment:apollo-budget-checklist",
    }
    assert "linear:comment:apollo-budget" not in selected_refs
    assert "linear:comment:apollo-budget-checklist" not in selected_refs
    assert len(hint_refs & thread_hint_refs) == 1
    assert "linear:issue:apollo-legal" in hint_refs
    assert selected_refs.isdisjoint(hint_refs)
    assert "linear:issue:generic-unrelated-hub" not in hint_refs
    hint = next(hint for hint in hints if hint["source_ref"] in thread_hint_refs)
    assert hint["reason"] == "related by thread to selected evidence linear:issue:apollo-plan"
    assert hint["related_source_ref"] == "linear:issue:apollo-plan"
    assert hint["source_system"] == "linear"
    assert hint["record_type"] == "message"
    assert 0 < hint["strength"] <= 1


def test_retrieve_block_renders_related_follow_up_hints(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:atlas-plan",
                source_system="linear",
                source_id="atlas-plan",
                record_type="work_item",
                title="Atlas rollout plan",
                body="atlas rollout zephyr evidence for the launch owner decision.",
                occurred_at="2026-06-20T12:00:00+00:00",
                thread_ref="linear:issue:atlas-plan",
            ),
            SourceRecord(
                source_ref="linear:comment:atlas-budget",
                source_system="linear",
                source_id="atlas-budget",
                record_type="message",
                title="Budget approval comment",
                body="Budget approval follow-up should be checked after launch owner evidence.",
                occurred_at="2026-06-21T12:00:00+00:00",
                thread_ref="linear:issue:atlas-plan",
            ),
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "atlas rollout zephyr",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
            "--token-budget",
            "80",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "You could also be interested in:" in output
    assert "Budget approval comment" in output
    assert "source_ref: linear:comment:atlas-budget" in output
    assert "related lead, not evidence" not in output
    assert "related_source_ref:" not in output
    assert "reason:" not in output
    assert "source_type:" not in output
    assert "follow_up_query:" not in output
    assert "strength:" not in output


def test_retrieve_uses_graph_link_count_as_general_rerank_signal(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:a-leaf",
                source_system="linear",
                source_id="a-leaf",
                record_type="work_item",
                title="Apollo decision leaf",
                body="apollo decision evidence",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
            SourceRecord(
                source_ref="linear:issue:z-hub",
                source_system="linear",
                source_id="z-hub",
                record_type="work_item",
                title="Apollo decision hub",
                body="apollo decision evidence",
                occurred_at="2026-06-20T12:00:00+00:00",
            ),
        ]
    )
    store_entity_links(
        context._engine,
        context._entity_links,
        links=[
            {
                "link_ref": f"linear:issue:ref-{index}->linear:issue:z-hub",
                "source_ref": f"linear:issue:ref-{index}",
                "object_ref": "linear:issue:z-hub",
                "relationship_type": "mentions",
                "confidence": 1.0,
                "evidence": {},
                "reason": "fixture",
                "status": "linked",
            }
            for index in range(8)
        ],
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "apollo decision",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert output.index("source_ref: linear:issue:z-hub") < output.index(
        "source_ref: linear:issue:a-leaf"
    )
    assert "graph_link_count=8" in output


def test_retrieve_no_results_is_successful_augmentation_block(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "retrieve",
            "quantum bananas unrelated",
            "--state",
            str(state),
            "--retrievers",
            "keyword",
        ],
    )

    main()

    output = capsys.readouterr().out
    assert "No relevant source excerpts found." in output
    assert "Searched keyword candidates." in output
