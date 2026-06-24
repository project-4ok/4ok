from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path

from gcb.cli_parts.shared import DEFAULT_STATE
from gcb.governance import GovernedContext
from gcb.governance.policy import PrincipalContext
from gcb.governance.state import create_governed_context_state
from gcb.observability import critical_span, set_safe_span_attributes
from gcb.runtime.dashboard import operator_status as runtime_operator_status
from gcb.runtime.operator_live import redacted_database_url
from gcb.storage.config import RuntimeConfig, load_runtime_config

ContextFactory = Callable[..., GovernedContext]


def tool_schemas() -> list[dict[str, object]]:
    return [
        {
            "name": "search_gcb",
            "description": "Search governed GCB state and return evidence-pack fields for agents.",
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
                            "SQLAlchemy database URL. Defaults to GCB_DATABASE_URL or SQLite state."
                        ),
                    },
                    "config": {
                        "type": ["string", "null"],
                        "description": "Optional GCB runtime TOML config path.",
                    },
                },
            },
        },
        {
            "name": "operator_status",
            "description": (
                "Return local GCB source/retrieval counts and simple freshness metadata."
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
                            "SQLAlchemy database URL. Defaults to GCB_DATABASE_URL or SQLite state."
                        ),
                    },
                    "config": {
                        "type": ["string", "null"],
                        "description": "Optional GCB runtime TOML config path.",
                    },
                },
            },
        },
    ]


def search_gcb(
    query: str,
    *,
    limit: int = 5,
    roles: Sequence[str] | None = None,
    human_id: str = "local-human",
    agent_id: str = "local-agent",
    state: str | None = None,
    database_url: str | None = None,
    config: str | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    with critical_span(
        "gcb.mcp.search",
        attributes={"gcb.mcp.tool": "search_gcb"},
        status_attribute="gcb.mcp.status",
    ) as span:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query is required")
        if limit < 1:
            raise ValueError("limit must be greater than zero")

        set_safe_span_attributes(
            span,
            {
                "gcb.search.limit": limit,
                "gcb.search.query_length": len(normalized_query),
            },
        )
        context = _context(
            state=state,
            database_url=database_url,
            config=config,
            context_factory=context_factory,
        )
        response = context.search_context(
            normalized_query,
            limit=limit,
            principal=PrincipalContext(
                human_id=human_id,
                agent_id=agent_id,
                roles=tuple(roles or ("operator",)),
            ),
        )
        set_safe_span_attributes(
            span,
            {
                "gcb.mcp.status": "succeeded",
                "gcb.search.result_count": len(response.results),
                "gcb.search.evidence_item_count": len(response.evidence_items or []),
            },
        )
        return {
            "query": response.query or normalized_query,
            "results": [asdict(result) for result in response.results],
            "summary": response.summary,
            "result_candidates": response.result_candidates or [],
            "evidence_items": response.evidence_items or [],
            "primary_objects": response.primary_objects or [],
            "related_objects": response.related_objects or [],
            "related_object_groups": response.related_object_groups or {},
            "entities": response.entities or [],
            "unresolved_candidates": response.unresolved_candidates or [],
            "limitations": response.limitations or [],
            "audit_ref": response.audit_ref,
        }


def operator_status(
    *,
    state: str | None = None,
    database_url: str | None = None,
    config: str | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    runtime_config = _runtime_config(config)
    resolved_database_url = _database_url(database_url, state=state)
    if context_factory is GovernedContext:
        governed_state = create_governed_context_state(
            state_path=_state_path(state),
            database_url=resolved_database_url,
            raw_store_path=None,
            raw_store_config=runtime_config.raw_store,
        )
        status = runtime_operator_status(governed_state)
        return {
            **status,
            "state_path": str(_state_path(state)),
            "database_url": redacted_database_url(resolved_database_url or ""),
        }

    context = _context(
        state=state,
        database_url=database_url,
        config=config,
        context_factory=context_factory,
    )
    source_records = [
        row for row in context.source_records() if row.get("lifecycle_state") == "active"
    ]
    retrieval_units = context.retrieval_units()
    return {
        "status": "ok",
        "state_path": str(_state_path(state)),
        "database_url": redacted_database_url(resolved_database_url or ""),
        "imported_items_by_source": _count_by(source_records, "source_system"),
        "retrieval_records": {
            "total": len(retrieval_units),
            "by_status": _count_by(retrieval_units, "status"),
        },
        "freshness": {
            "latest_source_occurred_at": _latest_string(source_records, "occurred_at"),
        },
    }


def build_mcp_server():
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - exercised only without optional runtime dep.
        raise RuntimeError(
            "The GCB MCP server requires the Python MCP SDK. "
            'Install project dependencies or run `uv add "mcp>=1.0"`.'
        ) from exc

    mcp = FastMCP("GCB Retrieval")

    @mcp.tool(name="search_gcb")
    def search_gcb_tool(
        query: str,
        limit: int = 5,
        roles: list[str] | None = None,
        human_id: str = "local-human",
        agent_id: str = "local-agent",
        state: str | None = None,
        database_url: str | None = None,
        config: str | None = None,
    ) -> dict[str, object]:
        """Search governed GCB state and return evidence-pack fields for agents."""
        return search_gcb(
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
        """Return local GCB source/retrieval counts and simple freshness metadata."""
        return operator_status(state=state, database_url=database_url, config=config)

    return mcp


def main() -> None:
    try:
        build_mcp_server().run()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2) from exc


def _context(
    *,
    state: str | None,
    database_url: str | None,
    config: str | None,
    context_factory: ContextFactory,
) -> GovernedContext:
    runtime_config = _runtime_config(config)
    return context_factory(
        _state_path(state),
        database_url=_database_url(database_url, state=state),
        raw_store_config=runtime_config.raw_store,
        retrieval_config=runtime_config.retrieval,
    )


def _state_path(state: str | None) -> Path:
    return Path(state) if state else DEFAULT_STATE


def _database_url(database_url: str | None, *, state: str | None = None) -> str | None:
    if database_url:
        return database_url
    if state:
        return None
    return os.environ.get("GCB_DATABASE_URL")


def _runtime_config(config: str | None) -> RuntimeConfig:
    config_path = config or os.environ.get("GCB_CONFIG_PATH")
    return load_runtime_config(Path(config_path)) if config_path else RuntimeConfig()


def _count_by(rows: Sequence[dict[str, object]], key: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = str(row.get(key) or "")
        if not value:
            continue
        counts[value] = counts.get(value, 0) + 1
    return dict(sorted(counts.items()))


def _latest_string(rows: Sequence[dict[str, object]], key: str) -> str | None:
    values = sorted(str(row[key]) for row in rows if row.get(key))
    return values[-1] if values else None


if __name__ == "__main__":
    main()
