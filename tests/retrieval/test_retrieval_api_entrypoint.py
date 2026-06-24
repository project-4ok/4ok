from __future__ import annotations

import importlib.util
from pathlib import Path

from gcb.api.retrieval import RetrievalAPI
from gcb.etl.extract.source_records import SourceRecord
from gcb.governance import GovernedContext


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_retrieval_api_is_single_source_for_agent_context_blocks(tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:api-first",
                source_system="slack",
                source_id="api-first",
                record_type="message",
                title="API first retrieval",
                body="The retrieval API is the owning boundary for all agent clients.",
                occurred_at="2026-06-24T10:00:00+00:00",
                permission_refs=("slack:channel:C0API",),
            )
        ]
    )

    response = RetrievalAPI(state=state).retrieve_for_agent("owning boundary")

    assert response.status == "ok"
    assert response.context_block.startswith("4OK RETRIEVAL FOR AGENTS\n")
    assert response.results[0].source_ref == "slack:message:api-first"
    assert response.results[0].permission_refs == ("slack:channel:C0API",)


def test_retrieval_api_is_single_source_for_governed_evidence_search(tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:restricted-api",
                source_system="slack",
                source_id="restricted-api",
                record_type="message",
                title="Restricted API evidence",
                body="permissionmarker API evidence must stay behind channel permissions.",
                permission_refs=("slack:channel:C0API",),
            )
        ]
    )

    api = RetrievalAPI(state=state)
    denied = api.search_evidence("permissionmarker", roles=("operator",))
    allowed = api.search_evidence("permissionmarker", roles=("operator", "slack:channel:C0API"))

    assert denied["results"] == []
    assert [result["source_ref"] for result in allowed["results"]] == [
        "slack:message:restricted-api"
    ]


def test_retrieval_clients_are_wrappers_and_openclaw_plugin_is_removed() -> None:
    assert importlib.util.find_spec("gcb.clients.cli.retrieval") is not None
    assert importlib.util.find_spec("gcb.clients.mcp.retrieval") is not None
    assert not (PROJECT_ROOT / "plugins" / "openclaw-gcb").exists()
