from __future__ import annotations

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
    assert "permission_refs: slack:channel:C0ASNARACMT" in block
    assert "why_relevant: specific source excerpt" in block
    assert "evidence: dev-jules-codex-auth-e2e-20260610-1059" in block


def test_default_reranker_demotes_tool_noise_and_boosts_current_work_items() -> None:
    rows = [
        {
            "source_ref": "openviking:conversation:tool-noise:message:1",
            "source_system": "openviking",
            "record_type": "message",
            "title": "OpenViking toolResult message",
            "snippet": (
                "<skill><name>linear</name><description>installed Linear CLI</description></skill>"
            ),
            "occurred_at": "2026-06-15T12:00:00Z",
            "score": 0.05,
            "retrievers": {"keyword"},
            "unit_index": 0,
            "permission_refs": (),
        },
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
    ]

    ranked = RetrievalReranker(default_rerank_rules()).rerank(
        rows, query="What are current fourok priorities?"
    )

    assert ranked[0]["source_ref"] == "linear:issue:fourok-84"
    assert ranked[0]["rerank_score"] > ranked[1]["rerank_score"]
    assert "boost_linear_work_item_for_current_priority_query" in ranked[0]["rerank_reasons"]
    assert "penalize_openviking_tool_noise" in ranked[1]["rerank_reasons"]
