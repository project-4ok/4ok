from __future__ import annotations

import re
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
            name="boost_linear_work_item_for_current_priority_query",
            multiplier=1.8,
            additive=0.01,
            predicate=_is_current_priority_linear_work_item,
        ),
        RerankRule(
            name="boost_person_title_token_match",
            multiplier=2.0,
            additive=0.02,
            predicate=_is_person_title_token_match,
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
        reasons = [str(item) for item in updated.get("rerank_reasons", ())]
        for rule in self._rules:
            if rule.applies(updated, query):
                score = score * rule.multiplier + rule.additive
                reasons.append(rule.name)
        updated["rerank_score"] = round(score, 6)
        updated["rerank_reasons"] = tuple(reasons) if reasons else ("specific source excerpt",)
        return updated


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


def _is_person_title_token_match(row: CandidateRow, query: str) -> bool:
    if str(row.get("record_type", "")).casefold() != "person":
        return False
    query_tokens = _tokens(query)
    if not query_tokens:
        return False
    title_tokens = set(_tokens(str(row.get("title", ""))))
    return _has_token_match(query_tokens, title_tokens)


def _has_token_match(query_tokens: list[str], title_tokens: set[str]) -> bool:
    for query_token in query_tokens:
        for title_token in title_tokens:
            if query_token == title_token:
                return True
            if (
                len(query_token) >= 4
                and len(title_token) >= 4
                and _is_one_edit_away(query_token, title_token)
            ):
                return True
    return False


def _is_one_edit_away(left: str, right: str) -> bool:
    if abs(len(left) - len(right)) > 1:
        return False
    if left == right:
        return True
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) <= 1
    if len(left) < len(right):
        left, right = right, left
    i = j = edits = 0
    while i < len(left) and j < len(right):
        if left[i] == right[j]:
            i += 1
            j += 1
            continue
        edits += 1
        if edits > 1:
            return False
        i += 1
    return True


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", value.casefold()) if len(token) > 2]


def _is_named_crm_person_query(row: CandidateRow, query: str) -> bool:
    words = [word for word in query.split() if len(word) > 2]
    if len(words) < 2:
        return False
    if str(row.get("record_type", "")).casefold() != "person":
        return False
    title = str(row.get("title", "")).casefold()
    return all(word.casefold() in title for word in words[:2])
