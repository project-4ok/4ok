from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from gcb.governance import GovernedContext
from gcb.retrieval.vector_search import ChunkVectorIndex, VectorSearchResult


@dataclass(frozen=True)
class RetrievalEvalCase:
    case_id: str
    query: str
    expected_source_refs: list[str]


@dataclass(frozen=True)
class RetrievalMetrics:
    method: str
    case_count: int
    top1_hits: int
    top3_hits: int

    @property
    def top1_rate(self) -> float:
        return self.top1_hits / self.case_count if self.case_count else 0

    @property
    def top3_rate(self) -> float:
        return self.top3_hits / self.case_count if self.case_count else 0


def load_retrieval_eval_cases(path: Path) -> list[RetrievalEvalCase]:
    raw_cases = json.loads(path.read_text())
    return [
        RetrievalEvalCase(
            case_id=raw_case["id"],
            query=raw_case["query"],
            expected_source_refs=raw_case["expected_source_refs"],
        )
        for raw_case in raw_cases
    ]


def compare_retrieval_methods(
    context: GovernedContext,
    vector_index: ChunkVectorIndex,
    cases: list[RetrievalEvalCase],
    *,
    limit: int = 3,
) -> list[RetrievalMetrics]:
    methods = {
        "full_text": lambda query: [
            result.source_ref for result in context.search_context(query, limit=limit).results
        ],
        "vector": lambda query: [
            result.source_ref for result in vector_index.search(query, limit=limit)
        ],
        "hybrid": lambda query: [
            result.source_ref
            for result in hybrid_results(
                context=context,
                vector_index=vector_index,
                query=query,
                limit=limit,
            )
        ],
    }
    return [
        _metrics_for_method(method=name, cases=cases, search=search)
        for name, search in methods.items()
    ]


def hybrid_results(
    *,
    context: GovernedContext,
    vector_index: ChunkVectorIndex,
    query: str,
    limit: int,
) -> list[VectorSearchResult]:
    full_text_results = context.search_context(query, limit=limit).results
    vector_results = vector_index.search(query, limit=limit)
    scores: dict[str, float] = {}
    result_by_source_ref: dict[str, VectorSearchResult] = {}

    for rank, result in enumerate(full_text_results, start=1):
        scores[result.source_ref] = scores.get(result.source_ref, 0.0) + 1 / (60 + rank)
        result_by_source_ref.setdefault(
            result.source_ref,
            VectorSearchResult(
                source_ref=result.source_ref,
                chunk_index=rank,
                text=result.snippet,
                score=0.0,
            ),
        )

    for rank, result in enumerate(vector_results, start=1):
        scores[result.source_ref] = scores.get(result.source_ref, 0.0) + 1 / (60 + rank)
        result_by_source_ref[result.source_ref] = result

    ranked_source_refs = sorted(scores, key=lambda source_ref: (-scores[source_ref], source_ref))
    return [result_by_source_ref[source_ref] for source_ref in ranked_source_refs[:limit]]


def _metrics_for_method(
    *,
    method: str,
    cases: list[RetrievalEvalCase],
    search,
) -> RetrievalMetrics:
    top1_hits = 0
    top3_hits = 0
    for case in cases:
        source_refs = search(case.query)
        expected = set(case.expected_source_refs)
        if source_refs[:1] and source_refs[0] in expected:
            top1_hits += 1
        if expected.intersection(source_refs[:3]):
            top3_hits += 1
    return RetrievalMetrics(
        method=method,
        case_count=len(cases),
        top1_hits=top1_hits,
        top3_hits=top3_hits,
    )
