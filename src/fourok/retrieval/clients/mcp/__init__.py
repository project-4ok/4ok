from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fourok.governance import GovernedContext
from fourok.retrieval.api import RetrievalAPI

ContextFactory = Callable[..., GovernedContext]


def retrieve(
    query: str,
    *,
    state: str | Path | None = None,
    database_url: str | None = None,
    config: str | Path | None = None,
    context_factory: ContextFactory = GovernedContext,
) -> dict[str, object]:
    api = RetrievalAPI(
        state=state,
        database_url=database_url,
        config=config,
        context_factory=context_factory,
    )
    return api.retrieve_augmentation(query)


search_fourok = retrieve


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
    return RetrievalAPI(
        state=state,
        database_url=database_url,
        config=config,
        context_factory=context_factory,
    ).open(source_ref, retrieval_event_id=retrieval_event_id, rank=rank)
