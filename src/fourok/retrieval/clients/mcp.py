from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from fourok.governance import GovernedContext
from fourok.retrieval.api import RetrievalAPI

ContextFactory = Callable[..., GovernedContext]


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
    return RetrievalAPI(
        state=state,
        database_url=database_url,
        config=config,
        context_factory=context_factory,
    ).search_evidence(
        query,
        limit=limit,
        roles=roles,
        human_id=human_id,
        agent_id=agent_id,
    )


def operator_status(
    *,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    return RetrievalAPI(
        state=state,
        database_url=database_url,
        config=config,
        context_factory=context_factory,
    ).operator_status()
