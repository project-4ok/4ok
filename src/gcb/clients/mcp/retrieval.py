from __future__ import annotations

from collections.abc import Sequence

from gcb.api.retrieval import RetrievalAPI


def search_4ok(
    query: str,
    *,
    limit: int = 5,
    roles: Sequence[str] | None = None,
    human_id: str = "local-human",
    agent_id: str = "local-agent",
    state: str | None = None,
    database_url: str | None = None,
    config: str | None = None,
    context_factory=None,
) -> dict[str, object]:
    api = RetrievalAPI(
        state=state,
        database_url=database_url,
        config=config,
        **({"context_factory": context_factory} if context_factory is not None else {}),
    )
    return api.search_evidence(
        query,
        limit=limit,
        roles=roles,
        human_id=human_id,
        agent_id=agent_id,
    )


search_gcb = search_4ok


def operator_status(
    *,
    state: str | None = None,
    database_url: str | None = None,
    config: str | None = None,
    context_factory=None,
) -> dict[str, object]:
    api = RetrievalAPI(
        state=state,
        database_url=database_url,
        config=config,
        **({"context_factory": context_factory} if context_factory is not None else {}),
    )
    return api.operator_status()
