from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

CandidateRow = dict[str, Any]
RerankPredicate = Callable[[CandidateRow, str], bool]


@dataclass(frozen=True)
class RerankRule:
    name: str
    multiplier: float = 1.0
    additive: float = 0.0
    predicate: RerankPredicate = lambda row, query: False

    def applies(self, row: CandidateRow, query: str) -> bool:
        return self.predicate(row, query)


def default_rerank_rules() -> tuple[RerankRule, ...]:
    return (
        RerankRule(
            name="penalize_openviking_tool_noise",
            multiplier=0.2,
            predicate=_is_openviking_tool_noise,
        ),
        RerankRule(
            name="boost_linear_work_item_for_current_priority_query",
            multiplier=1.8,
            additive=0.01,
            predicate=_is_current_priority_linear_work_item,
        ),
        RerankRule(
            name="boost_named_crm_person",
            multiplier=1.4,
            additive=0.004,
            predicate=_is_named_crm_person_query,
        ),
    )


class RetrievalReranker:
    def __init__(self, rules: Sequence[RerankRule]) -> None:
        self._rules = tuple(rules)

    def rerank(self, rows: Sequence[CandidateRow], *, query: str) -> list[CandidateRow]:
        reranked = [self._apply(row, query) for row in rows]
        return sorted(
            reranked,
            key=lambda row: (
                -float(row["rerank_score"]),
                str(row.get("occurred_at", "")),
                str(row.get("source_ref", "")),
            ),
        )

    def _apply(self, row: CandidateRow, query: str) -> CandidateRow:
        updated = dict(row)
        score = float(updated.get("score", 0.0) or 0.0)
        reasons: list[str] = []
        for rule in self._rules:
            if rule.applies(updated, query):
                score = score * rule.multiplier + rule.additive
                reasons.append(rule.name)
        updated["rerank_score"] = round(score, 6)
        updated["rerank_reasons"] = tuple(reasons) if reasons else ("specific source excerpt",)
        return updated


def _is_openviking_tool_noise(row: CandidateRow, query: str) -> bool:
    if str(row.get("source_system", "")).casefold() != "openviking":
        return False
    haystack = " ".join(
        str(row.get(key, "")) for key in ("title", "snippet", "record_type")
    ).casefold()
    noise_markers = (
        "toolresult",
        "<skill>",
        "</skill>",
        "installed linear cli",
        "location>/app/skills",
    )
    return any(marker in haystack for marker in noise_markers)


def _is_current_priority_linear_work_item(row: CandidateRow, query: str) -> bool:
    q = query.casefold()
    if not any(term in q for term in ("current", "priority", "priorities", "working on")):
        return False
    if str(row.get("source_system", "")).casefold() != "linear":
        return False
    if str(row.get("record_type", "")).casefold() not in {"work_item", "issue", "task"}:
        return False
    haystack = " ".join(str(row.get(key, "")) for key in ("title", "snippet")).casefold()
    return any(
        term in haystack for term in ("priority", "priorities", "right now", "current", "this week")
    )


def _is_named_crm_person_query(row: CandidateRow, query: str) -> bool:
    words = [word for word in query.split() if len(word) > 2]
    if len(words) < 2:
        return False
    if str(row.get("record_type", "")).casefold() != "person":
        return False
    title = str(row.get("title", "")).casefold()
    return all(word.casefold() in title for word in words[:2])
