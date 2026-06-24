from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from gcb.cli import main
from gcb.etl.extract.source_records import SourceRecord
from gcb.governance import GovernedContext


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
        ["gcb", "retrieve", "query", "--limit", "2"],
    )

    with pytest.raises(SystemExit):
        main()


def test_retrieve_defaults_to_five_results(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref=f"slack:message:default-limit:{index}",
                source_system="slack-live",
                source_id=f"default-limit-{index}",
                record_type="message",
                title=f"Default limit result {index}",
                body=f"default limit sentinel answer evidence {index}",
                occurred_at="2026-06-10T12:00:00+00:00",
            )
            for index in range(6)
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        ["gcb", "retrieve", "default limit sentinel answer", "--state", str(state)],
    )

    main()

    output = capsys.readouterr().out
    assert output.count("source_ref: slack:message:default-limit:") == 5


def test_retrieve_prints_llm_ready_augmentation_block(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "retrieve",
            "cancellation invoice follow-up",
            "--state",
            str(state),
        ],
    )

    main()

    output = capsys.readouterr().out
    assert output.startswith("4OK RETRIEVAL FOR AGENTS\n")
    assert "How to use this: Answer from these evidence cards only when relevant." in output
    assert "cancellation invoice follow-up" not in output
    assert "[1] Slack-Live message — #customer-success" in output
    assert "source_ref: slack:message:cancellation" in output
    assert "permission_refs: none recorded" in output
    assert "evidence: Customer asked whether the cancellation invoice was final" in output
    assert "Retrieval notes:" in output
    assert "Results are source excerpts, not a final answer." in output


def test_retrieve_json_returns_stable_machine_shape_without_echoing_query(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
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
    assert output["context_block"].startswith("4OK RETRIEVAL FOR AGENTS\n")
    assert output["results"][0] == {
        "source_ref": "slack:message:cancellation",
        "source_system": "slack-live",
        "record_type": "message",
        "title": "#customer-success",
        "occurred_at": "2026-06-10T12:00:00+00:00",
        "snippet": (
            "Customer asked whether the cancellation invoice was final and who owns follow-up."
        ),
        "score": output["results"][0]["score"],
        "retrievers": output["results"][0]["retrievers"],
        "permission_refs": [],
        "rerank_reasons": ["specific source excerpt"],
    }
    assert set(output["results"][0]["retrievers"]) >= {"keyword"}
    assert output["limitations"]


def test_retrieve_records_privacy_safe_request_observability(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
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
    assert row is not None
    assert row["status"] == "succeeded"
    assert row["retriever_set"] == "keyword,vector"
    assert row["requested_limit"] == 5
    assert row["candidate_limit"] == 10
    assert row["pre_rerank_candidates"] >= row["returned_results"] >= 1
    assert row["distinct_sources"] >= 1
    assert row["duration_ms"] >= 0
    assert "query" not in row.keys()


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
                    "linkedin outreach 10 inmail exact icp 4OK-385 "
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
            "gcb",
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
    assert "evidence: 4OK-385 Jespers booking link" in output


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
                    "belongs with the GCB OpenClaw rollout notes."
                ),
                occurred_at="2026-06-15T12:00:00+00:00",
            )
        ]
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
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
    assert "runtime deployment decision belongs with the GCB OpenClaw rollout notes" in output


def test_retrieve_no_results_is_successful_augmentation_block(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    _seed_state(state)
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
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
