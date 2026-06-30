from __future__ import annotations

import os
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import cast

from fourok.etl.extract.email_parser import EmailMessage
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext
from fourok.governance.state import create_governed_context_state
from fourok.retrieval.augmentation import DEFAULT_RETRIEVAL_TOKEN_BUDGET, RetrieverName
from fourok.runtime.dashboard import operator_status as runtime_operator_status
from fourok.runtime.operator_live import redacted_database_url
from fourok.storage.config import RuntimeConfig, load_runtime_config
from fourok.workflows import HumanAgentWorkflow

DEFAULT_STATE = Path(".local/fourok-state.sqlite")
ContextFactory = Callable[..., GovernedContext]


class RetrievalAPI:
    """Single domain boundary for retrieval clients.

    CLI, MCP, and future agent adapters should call this API instead of opening
    governed context state directly.
    """

    def __init__(
        self,
        *,
        state: str | Path | None = None,
        database_url: str | None = None,
        config: str | Path | None = None,
        context_factory: ContextFactory | None = GovernedContext,
    ) -> None:
        self._state = Path(state) if state is not None else DEFAULT_STATE
        self._state_explicit = state is not None
        self._database_url = database_url or (
            None if self._state_explicit else os.environ.get("FOUROK_DATABASE_URL")
        )
        config_path = config or os.environ.get("FOUROK_CONFIG_PATH")
        self._runtime_config = (
            load_runtime_config(Path(config_path)) if config_path else RuntimeConfig()
        )
        self._context_factory = context_factory or GovernedContext

    def search_evidence(
        self,
        query: str,
        *,
        limit: int = 5,
        roles: Sequence[str] | None = None,
        human_id: str = "local-human",
        agent_id: str = "local-agent",
    ) -> dict[str, object]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query is required")
        if limit < 1:
            raise ValueError("limit must be greater than zero")
        response = self._context().search_context(
            normalized_query,
            limit=limit,
            principal=PrincipalContext(
                human_id=human_id,
                agent_id=agent_id,
                roles=tuple(roles or ("operator",)),
            ),
        )
        return {
            "query": getattr(response, "query", normalized_query) or normalized_query,
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

    def retrieve_augmentation(
        self,
        query: str,
        *,
        token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET,
        candidate_limit: int = 40,
        retrievers: Sequence[str] = ("keyword", "vector"),
    ) -> dict[str, object]:
        retriever_tuple = tuple(retrievers)
        invalid = sorted(set(retriever_tuple) - {"keyword", "vector"})
        if invalid:
            raise ValueError(f"Unsupported retriever(s): {', '.join(invalid)}")
        response = self._context().retrieve_augmentation(
            query,
            token_budget=token_budget,
            candidate_limit=candidate_limit,
            retrievers=cast(tuple[RetrieverName, ...], retriever_tuple),
        )
        return response.to_dict()

    def retrieve_augmentation_block(
        self,
        query: str,
        *,
        token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET,
        candidate_limit: int = 40,
        retrievers: Sequence[str] = ("keyword", "vector"),
    ) -> str:
        response = self._context().retrieve_augmentation(
            query,
            token_budget=token_budget,
            candidate_limit=candidate_limit,
            retrievers=cast(tuple[RetrieverName, ...], tuple(retrievers)),
        )
        return response.context_block

    def open(
        self,
        source_ref: str,
        *,
        retrieval_event_id: str | None = None,
        rank: int | None = None,
    ) -> dict[str, object]:
        normalized_ref = source_ref.strip()
        if not normalized_ref:
            raise ValueError("source_ref is required")
        return self._context().inspect_source(
            normalized_ref,
            retrieval_event_id=retrieval_event_id,
            rank=rank,
            principal=PrincipalContext.local_default(),
        )

    def search_fixture(
        self,
        messages: list[EmailMessage],
        query: str,
        *,
        limit: int = 5,
    ) -> dict[str, object]:
        context = self._context()
        context.ingest(messages)
        response = context.search_context(query, limit=limit)
        return {"query": query, "results": [asdict(result) for result in response.results]}

    def ask_fixture(
        self,
        messages: list[EmailMessage],
        query: str,
        *,
        principal: PrincipalContext,
        limit: int = 5,
    ) -> dict[str, object]:
        context = self._context()
        context.ingest(messages)
        workflow = HumanAgentWorkflow(context, principal)
        response = workflow.ask(query, limit=limit)
        return {
            "query": query,
            "summary": response.summary,
            "evidence": [item.__dict__ for item in response.evidence],
        }

    def run_live_retrieval_case_set(
        self,
        *,
        cases_path: Path,
        seed_fixtures: bool,
        case_limit: int,
        report_path: Path,
    ) -> dict[str, object]:
        from fourok.retrieval.live_retrieval_case_set import run_live_retrieval_case_set

        return run_live_retrieval_case_set(
            context=self._context(),
            cases_path=cases_path,
            seed_fixtures=seed_fixtures,
            case_limit=case_limit,
            report_path=report_path,
        )

    def operator_status(self) -> dict[str, object]:
        if self._context_factory is GovernedContext:
            governed_state = create_governed_context_state(
                state_path=self._state,
                database_url=self._database_url,
                raw_store_path=None,
                raw_store_config=self._runtime_config.raw_store,
            )
            status = runtime_operator_status(governed_state)
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
        try:
            return self._context_factory(
                self._state,
                database_url=self._database_url,
                raw_store_config=self._runtime_config.raw_store,
                retrieval_config=self._runtime_config.retrieval,
            )
        except TypeError as exc:
            if "raw_store_config" not in str(exc) and "retrieval_config" not in str(exc):
                raise
            return self._context_factory(self._state, database_url=self._database_url)


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
