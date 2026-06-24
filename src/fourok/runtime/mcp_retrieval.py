from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from fourok.governance import GovernedContext
from fourok.observability import critical_span, set_safe_span_attributes
from fourok.retrieval.clients import mcp as mcp_client

ContextFactory = Callable[..., GovernedContext]


def tool_schemas() -> list[dict[str, object]]:
    return [
        {
            "name": "search_fourok",
            "description": (
                "Search governed fourok state and return evidence-pack fields for agents."
            ),
            "input_schema": {
                "type": "object",
                "required": ["query"],
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query to run against governed retrieval units.",
                    },
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "default": 5,
                        "description": "Maximum number of retrieval results.",
                    },
                    "roles": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": "Optional principal roles for permission filtering.",
                    },
                    "human_id": {
                        "type": "string",
                        "default": "local-human",
                        "description": "Human principal identifier for audit and policy.",
                    },
                    "agent_id": {
                        "type": "string",
                        "default": "local-agent",
                        "description": "Agent principal identifier for audit and policy.",
                    },
                    "state": {
                        "type": ["string", "null"],
                        "description": (
                            "SQLite state path. Ignored when database_url points to PostgreSQL."
                        ),
                    },
                    "database_url": {
                        "type": ["string", "null"],
                        "description": (
                            "SQLAlchemy database URL. Defaults to FOUROK_DATABASE_URL "
                            "or SQLite state."
                        ),
                    },
                    "config": {
                        "type": ["string", "null"],
                        "description": "Optional fourok runtime TOML config path.",
                    },
                },
            },
        },
        {
            "name": "operator_status",
            "description": (
                "Return local fourok source/retrieval counts and simple freshness metadata."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": ["string", "null"],
                        "description": (
                            "SQLite state path. Ignored when database_url points to PostgreSQL."
                        ),
                    },
                    "database_url": {
                        "type": ["string", "null"],
                        "description": (
                            "SQLAlchemy database URL. Defaults to FOUROK_DATABASE_URL "
                            "or SQLite state."
                        ),
                    },
                    "config": {
                        "type": ["string", "null"],
                        "description": "Optional fourok runtime TOML config path.",
                    },
                },
            },
        },
    ]


def search_fourok(
    query: str,
    *,
    limit: int = 5,
    roles: Sequence[str] | None = None,
    human_id: str = "local-human",
    agent_id: str = "local-agent",
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    with critical_span(
        "fourok.mcp.search",
        attributes={"fourok.mcp.tool": "search_fourok"},
        status_attribute="fourok.mcp.status",
    ) as span:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query is required")
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        set_safe_span_attributes(
            span,
            {
                "fourok.search.limit": limit,
                "fourok.search.query_length": len(normalized_query),
            },
        )
        response = mcp_client.search_fourok(
            normalized_query,
            limit=limit,
            roles=roles,
            human_id=human_id,
            agent_id=agent_id,
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

    @mcp.tool(name="search_fourok")
    def search_fourok_tool(
        query: str,
        limit: int = 5,
        roles: list[str] | None = None,
        human_id: str = "local-human",
        agent_id: str = "local-agent",
        state: str | None = None,
        database_url: str | None = None,
        config: str | None = None,
    ) -> dict[str, object]:
        """Search governed fourok state and return evidence-pack fields for agents."""
        return search_fourok(
            query=query,
            limit=limit,
            roles=roles,
            human_id=human_id,
            agent_id=agent_id,
            state=state,
            database_url=database_url,
            config=config,
        )

    @mcp.tool(name="operator_status")
    def operator_status_tool(
        state: str | None = None,
        database_url: str | None = None,
        config: str | None = None,
    ) -> dict[str, object]:
        """Return local fourok source/retrieval counts and simple freshness metadata."""
        return operator_status(state=state, database_url=database_url, config=config)

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
