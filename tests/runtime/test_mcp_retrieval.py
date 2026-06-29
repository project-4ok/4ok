from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext, SearchContextResponse, SourceChange
from fourok.governance.policy import PrincipalContext
from fourok.retrieval.search import SearchResult
from fourok.runtime import mcp_retrieval
from fourok.storage.config import RetrievalConfig


@dataclass
class FakeContext:
    created: ClassVar[list[FakeContext]] = []

    state_path: Path | str
    database_url: str | None = None
    raw_store_config: object | None = None
    retrieval_config: object | None = None

    def __post_init__(self) -> None:
        self.created.append(self)

    def search_context(
        self,
        query: str,
        *,
        limit: int,
        principal: PrincipalContext | None = None,
    ) -> SearchContextResponse:
        assert query == "refund escalation"
        assert limit == 5
        assert principal == PrincipalContext(
            human_id="human-1",
            agent_id="agent-1",
            roles=("support", "operator"),
        )
        return SearchContextResponse(
            query=query,
            results=[
                SearchResult(
                    source_ref="slack:message:1",
                    subject="Refund escalation",
                    date="2026-06-01T10:00:00Z",
                    snippet="Customer refund escalation requires support follow-up.",
                )
            ],
            summary="1 matching governed evidence item.",
            result_candidates=[
                {
                    "source_ref": "slack:message:1",
                    "score": 1.0,
                    "ranking_reason": "keyword match",
                }
            ],
            evidence_items=[
                {
                    "evidence_ref": "evidence:1",
                    "source_ref": "slack:message:1",
                    "snippet": "Customer refund escalation requires support follow-up.",
                }
            ],
            limitations=[],
            audit_ref="audit:search:1",
        )

    def source_records(self) -> list[dict[str, object]]:
        return [
            {
                "source_ref": "slack:message:1",
                "source_system": "slack",
                "occurred_at": "2026-06-01T10:00:00Z",
                "lifecycle_state": "active",
            },
            {
                "source_ref": "linear:issue:OPS-1",
                "source_system": "linear",
                "occurred_at": "2026-06-02T11:00:00Z",
                "lifecycle_state": "active",
            },
        ]

    def retrieval_units(self) -> list[dict[str, object]]:
        return [
            {"source_ref": "slack:message:1", "status": "current"},
            {"source_ref": "linear:issue:OPS-1", "status": "inactive"},
            {"source_ref": "linear:issue:OPS-1", "status": "current"},
        ]

    def retrieve_augmentation(self, query: str, **kwargs):
        assert query == "refund escalation"
        assert kwargs == {
            "token_budget": 2000,
            "candidate_limit": 40,
            "retrievers": ("keyword", "vector"),
        }

        class Response:
            context_block = "fourok RETRIEVAL FOR AGENTS\n"

            def to_dict(self):
                return {
                    "status": "ok",
                    "results": [{"source_ref": "slack:message:1"}],
                    "limitations": ["Results are source excerpts, not a final answer."],
                    "context_block": self.context_block,
                }

        return Response()


def test_mcp_tool_schemas_are_discoverable_without_stdio_server() -> None:
    tools = {tool["name"]: tool for tool in mcp_retrieval.tool_schemas()}

    assert set(tools) == {"fourok.retrieve", "fourok.status", "fourok.onboard"}
    assert tools["fourok.retrieve"]["input_schema"]["required"] == ["query"]
    assert set(tools["fourok.retrieve"]["input_schema"]["properties"]) == {"query"}
    assert tools["fourok.status"]["input_schema"]["properties"] == {}
    assert tools["fourok.onboard"]["input_schema"]["properties"] == {}


def test_mcp_main_can_run_streamable_http_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeServer:
        def run(self, *, transport: str, mount_path: str | None = None) -> None:
            captured["transport"] = transport
            captured["mount_path"] = mount_path

    def fake_build_mcp_server(**kwargs):
        captured.update(kwargs)
        return FakeServer()

    monkeypatch.setattr(mcp_retrieval, "build_mcp_server", fake_build_mcp_server)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok-mcp",
            "--transport",
            "streamable-http",
            "--host",
            "0.0.0.0",
            "--port",
            "8010",
            "--mount-path",
            "/mcp",
        ],
    )

    mcp_retrieval.main()

    assert captured == {
        "host": "0.0.0.0",
        "port": 8010,
        "transport": "streamable-http",
        "mount_path": "/mcp",
    }


@pytest.mark.anyio
async def test_fastmcp_server_registers_public_tool_names() -> None:
    server = mcp_retrieval.build_mcp_server()

    tools = await server.list_tools()

    assert [tool.name for tool in tools] == [
        "fourok.retrieve",
        "fourok.status",
        "fourok.onboard",
    ]


def test_search_handler_returns_retrieval_augmentation_contract() -> None:
    FakeContext.created.clear()

    response = mcp_retrieval.search_fourok(
        query="refund escalation",
        state="state.sqlite",
        database_url="postgresql+psycopg://fourok:secret@localhost:5432/fourok",
        context_factory=FakeContext,
    )

    assert response == {
        "status": "ok",
        "results": [{"source_ref": "slack:message:1"}],
        "limitations": ["Results are source excerpts, not a final answer."],
        "context_block": "fourok RETRIEVAL FOR AGENTS\n",
    }


def test_search_handler_loads_optional_runtime_config(tmp_path: Path) -> None:
    FakeContext.created.clear()
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retrieval]\nmax_words = 12\noverlap_words = 3\n", encoding="utf-8")

    mcp_retrieval.search_fourok(
        query="refund escalation",
        config=str(config_path),
        context_factory=FakeContext,
    )

    assert FakeContext.created[-1].retrieval_config == RetrievalConfig(
        max_words=12,
        overlap_words=3,
    )


def test_status_handler_uses_config_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    FakeContext.created.clear()
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retrieval]\nmax_words = 20\noverlap_words = 5\n", encoding="utf-8")
    monkeypatch.setenv("FOUROK_CONFIG_PATH", str(config_path))

    mcp_retrieval.operator_status(context_factory=FakeContext)

    assert FakeContext.created[-1].retrieval_config == RetrievalConfig(
        max_words=20,
        overlap_words=5,
    )


def test_search_handler_rejects_empty_query_before_opening_state() -> None:
    with pytest.raises(ValueError, match="query is required"):
        mcp_retrieval.search_fourok(query=" ", context_factory=FakeContext)


@pytest.mark.anyio
async def test_mcp_search_tool_returns_retrieval_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_search_fourok(**kwargs):
        assert kwargs == {"query": "mcppermissionmarker"}
        return {
            "status": "ok",
            "results": [{"source_ref": "linear:issue:1"}],
            "context_block": "fourok RETRIEVAL FOR AGENTS\n",
        }

    monkeypatch.setattr(mcp_retrieval, "search_fourok", fake_search_fourok)
    server = mcp_retrieval.build_mcp_server()

    _, response = await server.call_tool(
        "fourok.retrieve",
        {"query": "mcppermissionmarker"},
    )

    assert response == {
        "status": "ok",
        "results": [{"source_ref": "linear:issue:1"}],
        "context_block": "fourok RETRIEVAL FOR AGENTS\n",
    }


@pytest.mark.anyio
async def test_mcp_status_and_onboard_tools_return_client_facing_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        mcp_retrieval,
        "status_text",
        lambda: {"text": "fourok is ready\n\nContext: 1 source records, 1 retrieval units"},
    )
    monkeypatch.setattr(
        mcp_retrieval,
        "onboard_text",
        lambda: {"text": "fourok onboarding\n\nNext:\n  fourok status"},
    )
    server = mcp_retrieval.build_mcp_server()

    _, status = await server.call_tool("fourok.status", {})
    _, onboard = await server.call_tool("fourok.onboard", {})

    assert status == {"text": "fourok is ready\n\nContext: 1 source records, 1 retrieval units"}
    assert onboard == {"text": "fourok onboarding\n\nNext:\n  fourok status"}


def test_operator_status_returns_counts_and_freshness_without_secrets() -> None:
    response = mcp_retrieval.operator_status(
        state="state.sqlite",
        database_url="postgresql+psycopg://fourok:secret@localhost:5432/fourok",
        context_factory=FakeContext,
    )

    assert response == {
        "status": "ok",
        "state_path": "state.sqlite",
        "database_url": "postgresql+psycopg://fourok:[REDACTED]@localhost:5432/fourok",
        "imported_items_by_source": {"linear": 1, "slack": 1},
        "retrieval_records": {
            "total": 3,
            "by_status": {"current": 2, "inactive": 1},
        },
        "freshness": {"latest_source_occurred_at": "2026-06-02T11:00:00Z"},
    }


def test_operator_status_tool_counts_only_active_imported_source_records(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "fourok.sqlite"
    context = GovernedContext(state_path)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="linear:issue:active",
                source_system="linear",
                source_id="active",
                record_type="work_item",
                title="Active issue",
                body="Active issue body.",
            ),
            SourceRecord(
                source_ref="linear:issue:deleted",
                source_system="linear",
                source_id="deleted",
                record_type="work_item",
                title="Deleted issue",
                body="Deleted issue body.",
            ),
            SourceRecord(
                source_ref="twenty:company:active",
                source_system="twenty",
                source_id="active",
                record_type="organization",
                title="Active company",
                body="Active company body.",
            ),
        ]
    )
    context.apply_source_changes(
        [
            SourceChange(
                operation="delete",
                source_ref="linear:issue:deleted",
                reason="missing_from_latest_snapshot",
            )
        ]
    )

    response = mcp_retrieval.operator_status(state=str(state_path))

    assert response["imported_items_by_source"] == {"linear": 1, "twenty": 1}
    assert response["imported_items_by_source_record_type"] == {
        "linear": {"work_item": 1},
        "twenty": {"organization": 1},
    }
    assert response["retrieval_records"]["total"] == 3
