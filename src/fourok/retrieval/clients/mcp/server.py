from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from fourok.governance import GovernedContext
from fourok.observability import critical_span, set_safe_span_attributes
from fourok.retrieval.clients import mcp as mcp_client

ContextFactory = Callable[..., GovernedContext]


def tool_schemas() -> list[dict[str, object]]:
    return [
        {
            "name": "fourok.retrieve",
            "description": ("Search fourok and return an LLM-ready retrieval context pack."),
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Question or topic to retrieve source-backed context for.",
                    },
                },
            },
        },
        {
            "name": "fourok.open",
            "description": (
                "Open one retrieved source and log the inspection as an organic "
                "relevance signal."
            ),
            "input_schema": {
                "type": "object",
                "required": ["source_ref"],
                "properties": {
                    "source_ref": {
                        "type": "string",
                        "description": "Stable source_ref from a fourok.retrieve result.",
                    },
                    "retrieval_event_id": {
                        "type": "string",
                        "description": (
                            "Optional retrieval event id from the search that returned this source."
                        ),
                    },
                    "rank": {
                        "type": "integer",
                        "description": (
                            "Optional one-based rank of the source in the original result list."
                        ),
                    },
                },
            },
        },
        {
            "name": "fourok.status",
            "description": (
                "Return a client-facing fourok readiness and source freshness summary."
            ),
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
        {
            "name": "fourok.onboard",
            "description": "Return client-facing fourok onboarding guidance.",
            "input_schema": {
                "type": "object",
                "properties": {},
            },
        },
    ]


def search_fourok(
    query: str,
    *,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    with critical_span(
        "fourok.mcp.search",
        attributes={"fourok.mcp.tool": "fourok.retrieve"},
        status_attribute="fourok.mcp.status",
    ) as span:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query is required")
        set_safe_span_attributes(
            span,
            {
                "fourok.search.query_length": len(normalized_query),
            },
        )
        response = mcp_client.retrieve(
            normalized_query,
            state=state,
            database_url=database_url,
            config=config,
            context_factory=context_factory,
        )
        results = response.get("results", [])
        evidence_items = response.get("evidence_items", [])
        set_safe_span_attributes(
            span,
            {
                "fourok.mcp.status": "succeeded",
                "fourok.search.result_count": len(results) if isinstance(results, list) else 0,
                "fourok.search.evidence_item_count": (
                    len(evidence_items) if isinstance(evidence_items, list) else 0
                ),
            },
        )
        return response


def open(
    source_ref: str,
    *,
    retrieval_event_id: str | None = None,
    rank: int | None = None,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    with critical_span(
        "fourok.mcp.open",
        attributes={"fourok.mcp.tool": "fourok.open"},
        status_attribute="fourok.mcp.status",
    ) as span:
        normalized_ref = source_ref.strip()
        if not normalized_ref:
            raise ValueError("source_ref is required")
        set_safe_span_attributes(
            span,
            {
                "fourok.source_ref.length": len(normalized_ref),
                "fourok.search.result_rank": rank or 0,
            },
        )
        response = mcp_client.open(
            normalized_ref,
            retrieval_event_id=retrieval_event_id,
            rank=rank,
            state=state,
            database_url=database_url,
            config=config,
            context_factory=context_factory,
        )
        set_safe_span_attributes(
            span,
            {
                "fourok.mcp.status": str(response.get("status") or ""),
                "fourok.source.system": str(response.get("source_system") or ""),
                "fourok.source.record_type": str(response.get("record_type") or ""),
            },
        )
        return response


def operator_status(
    *,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    return mcp_client.operator_status(
        state=state,
        database_url=database_url,
        config=config,
        context_factory=context_factory,
    )


def status_text() -> dict[str, object]:
    from fourok.runtime.cli import _format_client_status, _safe_client_status_report

    report = _safe_client_status_report()
    return {"text": _format_client_status(report)}


def onboard_text() -> dict[str, object]:
    from fourok.runtime.cli import _onboard_message

    return {"text": _onboard_message(argparse.Namespace(demo=False))}


def build_mcp_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without optional runtime dep.
        raise RuntimeError(
            "The fourok MCP server requires the Python MCP SDK. "
            'Install project dependencies or run `uv add "mcp>=1.0"`.'
        ) from exc

    mcp = FastMCP(
        "fourok Retrieval",
        host=host,
        port=port,
        streamable_http_path="/mcp",
    )

    @mcp.tool(name="fourok.retrieve")
    def retrieve_tool(
        query: str,
    ) -> dict[str, object]:
        """Search fourok and return an LLM-ready retrieval context pack."""
        return search_fourok(query=query)

    @mcp.tool(name="fourok.open")
    def open_tool(
        source_ref: str,
        retrieval_event_id: str | None = None,
        rank: int | None = None,
    ) -> dict[str, object]:
        """Open one retrieved source and log the inspection as an organic relevance signal."""
        return open(
            source_ref=source_ref,
            retrieval_event_id=retrieval_event_id,
            rank=rank,
        )

    @mcp.tool(name="fourok.status")
    def status_tool() -> dict[str, object]:
        """Return a client-facing fourok readiness and source freshness summary."""
        return status_text()

    @mcp.tool(name="fourok.onboard")
    def onboard_tool() -> dict[str, object]:
        """Return client-facing fourok onboarding guidance."""
        return onboard_text()

    return mcp


def main() -> None:
    parser = argparse.ArgumentParser(prog="fourok-mcp")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default="stdio",
        help="MCP transport. Use streamable-http for Docker/HTTP clients.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--mount-path", default="/mcp")
    args = parser.parse_args()

    try:
        build_mcp_server(host=args.host, port=args.port).run(
            transport=args.transport,
            mount_path=args.mount_path,
        )
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
