from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from fourok.etl.extract.email_parser import EmailMessage
from fourok.governance.policy import PrincipalContext
from fourok.retrieval.api import RetrievalAPI
from fourok.retrieval.augmentation import DEFAULT_RETRIEVAL_TOKEN_BUDGET


def search_fixture(
    *,
    messages: list[EmailMessage],
    query: str,
    limit: int = 5,
    state: Path | str | None = None,
    database_url: str | None = None,
) -> dict[str, object]:
    return RetrievalAPI(state=state, database_url=database_url).search_fixture(
        messages,
        query,
        limit=limit,
    )


def search_state(
    query: str,
    *,
    limit: int = 5,
    principal: PrincipalContext,
    state: Path | str | None = None,
    database_url: str | None = None,
    context_factory: Callable[..., object] | None = None,
) -> dict[str, object]:
    return RetrievalAPI(
        state=state,
        database_url=database_url,
        context_factory=context_factory,
    ).search_evidence(
        query,
        limit=limit,
        roles=principal.roles,
        human_id=principal.human_id,
        agent_id=principal.agent_id,
    )


def retrieve_augmentation(
    query: str,
    *,
    token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET,
    candidate_limit: int = 40,
    retrievers: Sequence[str] = ("keyword", "vector"),
    state: Path | str | None = None,
    database_url: str | None = None,
) -> dict[str, object]:
    return RetrievalAPI(state=state, database_url=database_url).retrieve_augmentation(
        query,
        token_budget=token_budget,
        candidate_limit=candidate_limit,
        retrievers=retrievers,
    )


def retrieve_block(
    query: str,
    *,
    token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET,
    candidate_limit: int = 40,
    retrievers: Sequence[str] = ("keyword", "vector"),
    state: Path | str | None = None,
    database_url: str | None = None,
) -> str:
    return RetrievalAPI(state=state, database_url=database_url).retrieve_augmentation_block(
        query,
        token_budget=token_budget,
        candidate_limit=candidate_limit,
        retrievers=retrievers,
    )


def ask_fixture(
    *,
    messages: list[EmailMessage],
    query: str,
    principal: PrincipalContext,
    limit: int = 5,
    state: Path | str | None = None,
    database_url: str | None = None,
) -> dict[str, object]:
    return RetrievalAPI(state=state, database_url=database_url).ask_fixture(
        messages,
        query,
        principal=principal,
        limit=limit,
    )


def run_live_retrieval_case_set(
    *,
    cases_path: Path,
    seed_fixtures: bool,
    case_limit: int,
    report_path: Path,
    state: Path | str | None = None,
    database_url: str | None = None,
) -> dict[str, object]:
    return RetrievalAPI(state=state, database_url=database_url).run_live_retrieval_case_set(
        cases_path=cases_path,
        seed_fixtures=seed_fixtures,
        case_limit=case_limit,
        report_path=report_path,
    )
