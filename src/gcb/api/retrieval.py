from __future__ import annotations

import os
from dataclasses import asdict
from pathlib import Path
from typing import Sequence, cast

from gcb.cli_parts.shared import DEFAULT_STATE
from gcb.governance import GovernedContext
from gcb.governance.policy import PrincipalContext
from gcb.governance.state import create_governed_context_state
from gcb.retrieval.augmentation import RetrievalAugmentationResponse, RetrieverName
from gcb.runtime.dashboard import operator_status as runtime_operator_status
from gcb.runtime.operator_live import redacted_database_url
from gcb.storage.config import RuntimeConfig, load_runtime_config


class RetrievalAPI:
    """Primary 4OK retrieval boundary used by CLI, MCP, and future clients."""

    def __init__(
        self,
        *,
        state: str | Path | None = None,
        database_url: str | None = None,
        config: str | Path | None = None,
        context_factory=GovernedContext,
    ) -> None:
        self._state = Path(state) if state is not None else DEFAULT_STATE
        self._database_url = database_url or (
            _database_url_from_env() if state is None else None
        )
        self._runtime_config = _runtime_config(config)
        self._context_factory = context_factory

    def retrieve_for_agent(
        self,
        query: str,
        *,
        candidate_limit: int = 40,
        retrievers: Sequence[str] = ("keyword", "vector"),
    ) -> RetrievalAugmentationResponse:
        resolved_retrievers = _retrievers(retrievers)
        return self._context().retrieve_augmentation(
            query,
            limit=5,
            candidate_limit=candidate_limit,
            retrievers=resolved_retrievers,
        )

    def search_evidence(
        self,
        query: str,
        *,
        limit: int = 5,
        roles: Sequence[str] | None = None,
        human_id: str = "local-human",
        agent_id: str = "local-agent",
    ) -> dict[str, object]:
        response = self._context().search_context(
            query,
            limit=limit,
            principal=PrincipalContext(
                human_id=human_id,
                agent_id=agent_id,
                roles=tuple(roles or ("operator",)),
            ),
        )
        return {
            "query": response.query or query,
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

    def operator_status(self) -> dict[str, object]:
        if self._context_factory is GovernedContext:
            state = create_governed_context_state(
                state_path=self._state,
                database_url=self._database_url,
                raw_store_path=None,
                raw_store_config=self._runtime_config.raw_store,
            )
            status = runtime_operator_status(state)
            return {
                **status,
                "state_path": str(self._state),
                "database_url": redacted_database_url(self._database_url or ""),
            }

        context = self._context()
        source_records = [
            row for row in context.source_records() if row.get("lifecycle_state") == "active"
        ]
        retrieval_units = context.retrieval_units()
        return {
            "status": "ok",
            "state_path": str(self._state),
            "database_url": redacted_database_url(self._database_url or ""),
            "imported_items_by_source": _count_by(source_records, "source_system"),
            "retrieval_records": {
                "total": len(retrieval_units),
                "by_status": _count_by(retrieval_units, "status"),
            },
            "freshness": {
                "latest_source_occurred_at": _latest_string(source_records, "occurred_at"),
            },
        }

    def _context(self) -> GovernedContext:
        return self._context_factory(
            self._state,
            database_url=self._database_url,
            raw_store_config=self._runtime_config.raw_store,
            retrieval_config=self._runtime_config.retrieval,
        )

def _runtime_config(config: str | Path | None) -> RuntimeConfig:
    config_path = config or os.environ.get("FOUR_OK_CONFIG_PATH") or os.environ.get(
        "GCB_CONFIG_PATH"
    )
    return load_runtime_config(Path(config_path)) if config_path else RuntimeConfig()


def _database_url_from_env() -> str | None:
    return os.environ.get("FOUR_OK_DATABASE_URL") or os.environ.get("GCB_DATABASE_URL")


def _retrievers(retrievers: Sequence[str]) -> tuple[RetrieverName, ...]:
    normalized = tuple(item.strip() for item in retrievers if item.strip())
    invalid = sorted(set(normalized) - {"keyword", "vector"})
    if invalid:
        raise ValueError(f"Unsupported retriever(s): {', '.join(invalid)}")
    return cast(tuple[RetrieverName, ...], normalized or ("keyword", "vector"))


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
