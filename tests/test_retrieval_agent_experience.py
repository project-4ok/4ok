from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.extract.sync_jobs import complete_connector_job, start_connector_job
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.retrieval.augmentation import (
    RetrievalAugmentationResponse,
    RetrievalCandidate,
    render_augmentation_block,
)
from fourok.retrieval.reranker import RetrievalReranker, default_rerank_rules


def test_default_retrieval_block_is_agent_facing_and_citation_ready() -> None:
    response = RetrievalAugmentationResponse(
        status="ok",
        results=[
            RetrievalCandidate(
                source_ref="slack:message:C0ASNARACMT:1781089083.931829",
                source_system="slack",
                record_type="message",
                title="Dev Jules auth E2E marker",
                occurred_at="2026-06-10T10:58:03Z",
                snippet="dev-jules-codex-auth-e2e-20260610-1059 evidence from agent-test channel",
                score=0.42,
                retrievers=("keyword", "vector"),
                permission_refs=("slack:channel:C0ASNARACMT",),
                rerank_reasons=("specific source excerpt",),
            )
        ],
        limitations=["Searched keyword and vector candidates."],
    )

    block = render_augmentation_block(response)

    assert block.startswith("fourok RETRIEVAL FOR AGENTS\n")
    assert "How to use this:" in block
    assert "Answer from these evidence cards only when relevant" in block
    assert "[1] Slack message — Dev Jules auth E2E marker" in block
    assert "source_ref: slack:message:C0ASNARACMT:1781089083.931829" in block
    assert "permission_refs:" not in block
    assert "why_relevant: specific source excerpt" in block
    assert "evidence: dev-jules-codex-auth-e2e-20260610-1059" in block


def test_empty_retrieval_block_guides_user_to_onboard_and_status() -> None:
    response = RetrievalAugmentationResponse(
        status="ok",
        results=[],
        limitations=[
            "Searched keyword and vector candidates.",
            "No relevant source excerpts found for the selected retrievers.",
            "Results are source excerpts, not a final answer.",
        ],
    )

    block = render_augmentation_block(response)

    assert "No relevant source excerpts found." in block
    assert "This usually means fourok has no imported context yet" in block
    assert "fourok status" in block
    assert "fourok onboard" in block
    assert "fourok onboard connectors" not in block


def test_retrieval_notes_summarize_successful_connector_import_age(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "fourok.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:1",
                source_system="slack",
                source_id="1",
                record_type="message",
                title="Slack renewal",
                body="Alpha renewal needs follow-up.",
            )
        ]
    )
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    started = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="slack-live",
        job_id="job-slack-1",
        now=datetime(2026, 6, 24, 10, 0, tzinfo=UTC),
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=started.job_id,
        connector_name="slack-live",
        output_state={"freshness_status": "fresh"},
        raw_output_ref=".local/recurring-live-ingestion/slack",
        now=datetime.now(UTC),
    )

    block = context.retrieve_augmentation("Alpha renewal").context_block

    assert "Connector imports:" in block
    assert "slack succeeded just now" in block


def test_default_reranker_boosts_current_work_items() -> None:
    rows = [
        {
            "source_ref": "linear:issue:fourok-84",
            "source_system": "linear",
            "record_type": "work_item",
            "title": "Align with Simon on priorities — what's really important right now",
            "snippet": (
                "Sit down with Simon and get aligned on the single most important "
                "thing for fourok right now."
            ),
            "occurred_at": "2026-04-13T07:42:10Z",
            "score": 0.03,
            "retrievers": {"keyword"},
            "unit_index": 0,
            "permission_refs": (),
        },
        {
            "source_ref": "slack:message:priorities:1",
            "source_system": "slack",
            "record_type": "message",
            "title": "General current-priority chatter",
            "snippet": "A generic mention of current priorities without a concrete work item.",
            "occurred_at": "2026-06-15T12:00:00Z",
            "score": 0.05,
            "retrievers": {"keyword"},
            "unit_index": 0,
            "permission_refs": (),
        },
    ]

    ranked = RetrievalReranker(default_rerank_rules()).rerank(
        rows, query="What are current fourok priorities?"
    )

    assert ranked[0]["source_ref"] == "linear:issue:fourok-84"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]
    assert "boost_linear_work_item_for_current_priority_query" in ranked[0]["rerank_reasons"]


def test_reranker_boosts_person_title_token_match_over_loose_work_item_match() -> None:
    rows = [
        {
            "source_ref": "linear:issue:yc-video",
            "source_system": "linear",
            "record_type": "work_item",
            "title": "Y Combinator team video",
            "snippet": "Olivia should review the team video before the deadline.",
            "occurred_at": "2026-04-13T07:42:10Z",
            "score": 0.033,
            "retrievers": {"keyword"},
            "unit_index": 0,
            "permission_refs": (),
            "rerank_reasons": (),
        },
        {
            "source_ref": "linear:user:simon",
            "source_system": "linear",
            "record_type": "person",
            "title": "Simon van Laak",
            "snippet": "employee",
            "occurred_at": "2026-04-14T07:42:10Z",
            "score": 0.053,
            "retrievers": {"vector"},
            "unit_index": 0,
            "permission_refs": (),
            "rerank_reasons": (),
        },
        {
            "source_ref": "twenty:person:olivia",
            "source_system": "twenty",
            "record_type": "person",
            "title": "Olivia Allen",
            "snippet": "olivia.allen@example.test",
            "occurred_at": "2026-04-12T07:42:10Z",
            "score": 0.029,
            "retrievers": {"keyword", "vector"},
            "unit_index": 0,
            "permission_refs": (),
            "rerank_reasons": (),
        },
    ]

    ranked = RetrievalReranker(default_rerank_rules()).rerank(rows, query="oliva")

    assert ranked[0]["source_ref"] == "twenty:person:olivia"
    assert "boost_person_title_token_match" in ranked[0]["rerank_reasons"]
