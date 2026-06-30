from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from fourok.governance import SearchContextResponse
from fourok.governance.policy import PrincipalContext
from fourok.retrieval.api import RetrievalAPI
from fourok.retrieval.clients import cli as cli_client
from fourok.retrieval.clients import mcp as mcp_client
from fourok.retrieval.search import SearchResult
from fourok.storage.config import RetrievalConfig

ROOT = Path(__file__).resolve().parents[2]


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
            summary=f"search:{principal.human_id if principal else 'none'}",
            evidence_items=[{"source_ref": "slack:message:1"}],
            limitations=[],
            audit_ref="audit:search:1",
        )

    def retrieve_augmentation(self, query: str, **kwargs):
        class Response:
            context_block = "fourok RETRIEVAL FOR AGENTS\n"

            def to_dict(self):
                return {"status": "ok", "context_block": self.context_block, "results": []}

        return Response()

    def source_records(self) -> list[dict[str, object]]:
        return [
            {
                "source_system": "slack",
                "occurred_at": "2026-06-01T10:00:00Z",
                "lifecycle_state": "active",
            }
        ]

    def retrieval_units(self) -> list[dict[str, object]]:
        return [{"status": "current"}]


def test_retrieval_api_is_public_domain_boundary_for_search_retrieve_and_status() -> None:
    FakeContext.created.clear()
    api = RetrievalAPI(state="state.sqlite", context_factory=FakeContext)

    search = api.search_evidence(
        "refund escalation",
        limit=2,
        roles=["support"],
        human_id="human-1",
        agent_id="agent-1",
    )
    retrieve = api.retrieve_augmentation("refund escalation")
    status = api.operator_status()

    assert search["results"][0]["source_ref"] == "slack:message:1"
    assert search["summary"] == "search:human-1"
    assert retrieve["status"] == "ok"
    assert status["imported_items_by_source"] == {"slack": 1}
    assert FakeContext.created[-1].retrieval_config == RetrievalConfig()


def test_cli_and_mcp_clients_are_thin_wrappers_over_retrieval_api(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    class FakeAPI:
        def __init__(self, **kwargs) -> None:
            calls.append(("init", str(kwargs.get("state"))))

        def search_evidence(self, query: str, **kwargs):
            calls.append(("search", query))
            return {"query": query, "results": []}

        def retrieve_augmentation(self, query: str, **kwargs):
            calls.append(("retrieve", query))
            return {"status": "ok", "results": []}

        def operator_status(self):
            calls.append(("status", ""))
            return {"status": "ok"}

    monkeypatch.setattr(cli_client, "RetrievalAPI", FakeAPI)
    monkeypatch.setattr(mcp_client, "RetrievalAPI", FakeAPI)

    assert cli_client.retrieve_augmentation("cli query", state="state.sqlite") == {
        "status": "ok",
        "results": [],
    }
    assert mcp_client.retrieve("mcp query", state="state.sqlite") == {
        "status": "ok",
        "results": [],
    }
    assert mcp_client.operator_status(state="state.sqlite") == {"status": "ok"}
    assert calls == [
        ("init", "state.sqlite"),
        ("retrieve", "cli query"),
        ("init", "state.sqlite"),
        ("retrieve", "mcp query"),
        ("init", "state.sqlite"),
        ("status", ""),
    ]


def test_cli_and_mcp_surfaces_do_not_instantiate_governed_context_directly() -> None:
    checked = [
        ROOT / "src/fourok/retrieval/cli.py",
        ROOT / "src/fourok/retrieval/clients/mcp/server.py",
        ROOT / "src/fourok/retrieval/clients/cli.py",
        ROOT / "src/fourok/retrieval/clients/mcp/__init__.py",
    ]
    offenders: list[str] = []
    for path in checked:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "GovernedContext":
                    offenders.append(str(path.relative_to(ROOT)))
    assert offenders == []


def test_retrieval_cli_adapter_is_domain_owned() -> None:
    assert (ROOT / "src/fourok/retrieval/cli.py").exists()
    assert (ROOT / "src/fourok/retrieval/clients/mcp/server.py").exists()
    assert not (ROOT / "src/fourok/runtime/mcp_retrieval.py").exists()
    assert not (ROOT / "src/fourok/cli_parts/parser_search.py").exists()
    assert not (ROOT / "src/fourok/cli_parts/commands_search.py").exists()

    root_parser = (ROOT / "src/fourok/cli_parts/parser.py").read_text(encoding="utf-8")
    root_dispatch = (ROOT / "src/fourok/cli_parts/core_commands.py").read_text(encoding="utf-8")
    assert "from fourok.retrieval.cli import add_search_commands" in root_parser
    assert "from fourok.retrieval.cli import dispatch_search_commands" in root_dispatch
