from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import bindparam, select, text
from sqlalchemy.engine import Engine

from fourok.retrieval.reranker import RetrievalReranker, default_rerank_rules
from fourok.retrieval.search import snippet_for, source_record_search_rows
from fourok.retrieval.vector_search import ChunkVectorIndex

RetrieverName = Literal["keyword", "vector"]


@dataclass(frozen=True)
class RetrievalCandidate:
    source_ref: str
    source_system: str
    record_type: str
    title: str
    occurred_at: str
    snippet: str
    score: float
    retrievers: tuple[str, ...] = field(default_factory=tuple)
    permission_refs: tuple[str, ...] = field(default_factory=tuple)
    rerank_reasons: tuple[str, ...] = field(default_factory=tuple)
    unit_index: int = 0


@dataclass(frozen=True)
class RetrievalAugmentationResponse:
    status: str
    results: list[RetrievalCandidate]
    limitations: list[str]

    @property
    def context_block(self) -> str:
        return render_augmentation_block(self)

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "context_block": self.context_block,
            "results": [
                {
                    "source_ref": result.source_ref,
                    "source_system": result.source_system,
                    "record_type": result.record_type,
                    "title": result.title,
                    "occurred_at": result.occurred_at,
                    "snippet": result.snippet,
                    "score": result.score,
                    "retrievers": list(result.retrievers),
                    "permission_refs": list(result.permission_refs),
                    "rerank_reasons": list(result.rerank_reasons),
                }
                for result in self.results
            ],
            "limitations": self.limitations,
        }


def retrieve_augmentation(
    engine: Engine,
    source_records,
    retrieval_records,
    query: str,
    *,
    limit: int = 5,
    candidate_limit: int = 40,
    retrievers: tuple[RetrieverName, ...] = ("keyword", "vector"),
) -> RetrievalAugmentationResponse:
    started = time.perf_counter()
    retriever_set = ",".join(retrievers)
    keyword_count = 0
    vector_count = 0

    try:
        if limit < 1:
            response = RetrievalAugmentationResponse(
                status="ok",
                results=[],
                limitations=["Limit was below 1, so no source excerpts were returned."],
            )
            _record_retrieval_query_event(
                engine,
                status="succeeded",
                retriever_set=retriever_set,
                requested_limit=limit,
                candidate_limit=candidate_limit,
                pre_rerank_candidates=0,
                keyword_candidates=0,
                vector_candidates=0,
                distinct_sources=0,
                returned_results=0,
                duration_ms=_elapsed_ms(started),
            )
            return response

        candidates_by_key: dict[tuple[str, int], dict[str, object]] = {}
        limitations: list[str] = []

        if "keyword" in retrievers:
            keyword_rows = source_record_search_rows(
                engine,
                source_records,
                retrieval_records,
                query,
                limit=candidate_limit,
                exclude_source_refs=set(),
            )
            keyword_count = len(keyword_rows)
            _merge_ranked_rows(
                candidates_by_key,
                _metadata_by_source_ref(
                    engine, source_records, [row["source_ref"] for row in keyword_rows]
                ),
                keyword_rows,
                query=query,
                retriever="keyword",
            )

        if "vector" in retrievers:
            vector_rows = _vector_rows(engine, query, limit=candidate_limit)
            vector_count = len(vector_rows)
            if vector_rows:
                _merge_ranked_rows(
                    candidates_by_key,
                    _metadata_by_source_ref(
                        engine, source_records, [row["source_ref"] for row in vector_rows]
                    ),
                    vector_rows,
                    query=query,
                    retriever="vector",
                )
            else:
                limitations.append("Semantic/vector candidates were unavailable or empty.")

        pre_rerank_count = len(candidates_by_key)
        distinct_sources = len({source_ref for source_ref, _unit_index in candidates_by_key})
        results = _rank_and_diversify(candidates_by_key, query=query, limit=limit)
        searched = " and ".join(name for name in retrievers)
        if results:
            limitations.append(f"Searched {searched} candidates.")
        else:
            limitations.append(f"Searched {searched} candidates.")
            limitations.append("No relevant source excerpts found for the selected retrievers.")
        limitations.append("Results are source excerpts, not a final answer.")
        response = RetrievalAugmentationResponse(
            status="ok", results=results, limitations=limitations
        )
        _record_retrieval_query_event(
            engine,
            status="succeeded",
            retriever_set=retriever_set,
            requested_limit=limit,
            candidate_limit=candidate_limit,
            pre_rerank_candidates=pre_rerank_count,
            keyword_candidates=keyword_count,
            vector_candidates=vector_count,
            distinct_sources=distinct_sources,
            returned_results=len(results),
            duration_ms=_elapsed_ms(started),
        )
        return response
    except Exception:
        _record_retrieval_query_event(
            engine,
            status="failed",
            retriever_set=retriever_set,
            requested_limit=limit,
            candidate_limit=candidate_limit,
            pre_rerank_candidates=0,
            keyword_candidates=keyword_count,
            vector_candidates=vector_count,
            distinct_sources=0,
            returned_results=0,
            duration_ms=_elapsed_ms(started),
        )
        raise


def render_augmentation_block(response: RetrievalAugmentationResponse) -> str:
    lines = [
        "fourok RETRIEVAL FOR AGENTS",
        "",
        (
            "How to use this: Answer from these evidence cards only when relevant. "
            "Cite source_ref values for factual claims. Respect permission_refs. "
            "If the evidence is weak or incomplete, say so."
        ),
        "",
    ]
    if not response.results:
        lines.extend(["No relevant source excerpts found.", ""])
    else:
        for index, result in enumerate(response.results, start=1):
            permission_refs = (
                ", ".join(result.permission_refs) if result.permission_refs else "none recorded"
            )
            why_relevant = ", ".join(result.rerank_reasons) or "specific source excerpt"
            lines.extend(
                [
                    f"[{index}] {_agent_result_label(result)} — {result.title or '(untitled)'}",
                    f"source_ref: {result.source_ref}",
                    f"permission_refs: {permission_refs}",
                    f"why_relevant: {why_relevant}",
                    f"date: {result.occurred_at or 'unknown'}",
                    f"evidence: {result.snippet}",
                    "",
                ]
            )
    lines.append("Retrieval notes:")
    lines.extend(f"- {limitation}" for limitation in response.limitations)
    return "\n".join(lines).rstrip() + "\n"


def _merge_ranked_rows(
    candidates_by_key: dict[tuple[str, int], dict[str, object]],
    metadata_by_ref: dict[str, dict[str, object]],
    rows: list[dict[str, object]],
    *,
    query: str,
    retriever: str,
) -> None:
    for rank, row in enumerate(rows, start=1):
        source_ref = str(row["source_ref"])
        unit_index = int(row.get("unit_index", 0) or 0)
        key = (source_ref, unit_index)
        metadata = metadata_by_ref.get(source_ref, {})
        title = str(row.get("subject", metadata.get("title", "")))
        candidate = candidates_by_key.setdefault(
            key,
            {
                "source_ref": source_ref,
                "source_system": metadata.get("source_system", ""),
                "record_type": metadata.get("record_type", ""),
                "title": title,
                "occurred_at": str(row.get("date", metadata.get("occurred_at", ""))),
                "permission_refs": _object_string_tuple(metadata.get("permission_refs", ())),
                "snippet": _evidence_snippet(
                    str(row.get("body", row.get("snippet", ""))), title, query
                ),
                "score": 0.0,
                "retrievers": set(),
                "unit_index": unit_index,
            },
        )
        candidate["score"] = float(candidate["score"]) + 1.0 / (60 + rank)
        candidate_retrievers = candidate["retrievers"]
        assert isinstance(candidate_retrievers, set)
        candidate_retrievers.add(retriever)


def _rank_and_diversify(
    candidates_by_key: dict[tuple[str, int], dict[str, object]],
    *,
    query: str,
    limit: int,
) -> list[RetrievalCandidate]:
    rows = RetrievalReranker(default_rerank_rules()).rerank(
        list(candidates_by_key.values()), query=query
    )
    results: list[RetrievalCandidate] = []
    per_source_count: dict[str, int] = {}
    for row in rows:
        source_ref = str(row["source_ref"])
        if per_source_count.get(source_ref, 0) >= 2:
            continue
        per_source_count[source_ref] = per_source_count.get(source_ref, 0) + 1
        retrievers = tuple(sorted(str(item) for item in row["retrievers"]))
        permission_refs = tuple(str(item) for item in row.get("permission_refs", ()))
        rerank_reasons = tuple(str(item) for item in row.get("rerank_reasons", ()))
        results.append(
            RetrievalCandidate(
                source_ref=source_ref,
                source_system=str(row["source_system"]),
                record_type=str(row["record_type"]),
                title=str(row["title"]),
                occurred_at=str(row["occurred_at"]),
                snippet=str(row["snippet"]),
                score=round(float(row.get("rerank_score", row["score"])), 6),
                retrievers=retrievers,
                permission_refs=permission_refs,
                rerank_reasons=rerank_reasons,
                unit_index=int(row["unit_index"]),
            )
        )
        if len(results) >= limit:
            break
    return results


def _metadata_by_source_ref(
    engine: Engine, source_records, source_refs: list[str]
) -> dict[str, dict[str, object]]:
    unique_refs = sorted({ref for ref in source_refs if ref})
    if not unique_refs:
        return {}
    statement = select(
        source_records.c.source_ref,
        source_records.c.source_system,
        source_records.c.record_type,
        source_records.c.title,
        source_records.c.occurred_at,
        source_records.c.permission_refs,
    ).where(source_records.c.source_ref.in_(bindparam("source_refs", expanding=True)))
    with engine.connect() as connection:
        return {
            str(row["source_ref"]): {
                "source_system": str(row["source_system"]),
                "record_type": str(row["record_type"]),
                "title": str(row["title"]),
                "occurred_at": str(row["occurred_at"]),
                "permission_refs": _json_string_tuple(str(row["permission_refs"])),
            }
            for row in connection.execute(statement, {"source_refs": unique_refs}).mappings()
        }


def _vector_rows(engine: Engine, query: str, *, limit: int) -> list[dict[str, object]]:
    try:
        vector_results = ChunkVectorIndex(engine).search(query, limit=limit)
    except Exception:
        return []
    source_refs = [result.source_ref for result in vector_results if result.score > 0]
    metadata = _metadata_by_source_ref_from_table_name(engine, source_refs)
    rows: list[dict[str, object]] = []
    for result in vector_results:
        if result.score <= 0:
            continue
        row_meta = metadata.get(result.source_ref, {})
        rows.append(
            {
                "source_ref": result.source_ref,
                "unit_index": result.chunk_index,
                "subject": row_meta.get("title", ""),
                "body": result.text,
                "date": row_meta.get("occurred_at", ""),
            }
        )
    return rows


def _metadata_by_source_ref_from_table_name(
    engine: Engine, source_refs: list[str]
) -> dict[str, dict[str, str]]:
    unique_refs = sorted({ref for ref in source_refs if ref})
    if not unique_refs:
        return {}
    statement = text(
        """
        SELECT source_ref, title, occurred_at
        FROM source_records
        WHERE source_ref IN :source_refs
        """
    ).bindparams(bindparam("source_refs", expanding=True))
    with engine.connect() as connection:
        return {
            str(row["source_ref"]): {
                "title": str(row["title"]),
                "occurred_at": str(row["occurred_at"]),
            }
            for row in connection.execute(statement, {"source_refs": unique_refs}).mappings()
        }


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 3)


def _record_retrieval_query_event(
    engine: Engine,
    *,
    status: str,
    retriever_set: str,
    requested_limit: int,
    candidate_limit: int,
    pre_rerank_candidates: int,
    keyword_candidates: int,
    vector_candidates: int,
    distinct_sources: int,
    returned_results: int,
    duration_ms: float,
) -> None:
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS retrieval_query_events (
                        event_id TEXT PRIMARY KEY,
                        occurred_at TEXT NOT NULL,
                        status TEXT NOT NULL,
                        retriever_set TEXT NOT NULL,
                        requested_limit INTEGER NOT NULL,
                        candidate_limit INTEGER NOT NULL,
                        pre_rerank_candidates INTEGER NOT NULL,
                        keyword_candidates INTEGER NOT NULL,
                        vector_candidates INTEGER NOT NULL,
                        distinct_sources INTEGER NOT NULL,
                        returned_results INTEGER NOT NULL,
                        duration_ms REAL NOT NULL
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO retrieval_query_events (
                        event_id, occurred_at, status, retriever_set, requested_limit,
                        candidate_limit, pre_rerank_candidates, keyword_candidates,
                        vector_candidates, distinct_sources, returned_results, duration_ms
                    ) VALUES (
                        :event_id, :occurred_at, :status, :retriever_set, :requested_limit,
                        :candidate_limit, :pre_rerank_candidates, :keyword_candidates,
                        :vector_candidates, :distinct_sources, :returned_results, :duration_ms
                    )
                    """
                ),
                {
                    "event_id": f"retrieval-query:{uuid.uuid4()}",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "status": status,
                    "retriever_set": retriever_set,
                    "requested_limit": requested_limit,
                    "candidate_limit": candidate_limit,
                    "pre_rerank_candidates": pre_rerank_candidates,
                    "keyword_candidates": keyword_candidates,
                    "vector_candidates": vector_candidates,
                    "distinct_sources": distinct_sources,
                    "returned_results": returned_results,
                    "duration_ms": duration_ms,
                },
            )
    except Exception:
        # Retrieval observability must never break user-facing retrieval.
        return


def _snippet_without_title_prefix(text_value: str, title: str) -> str:
    compacted = " ".join(text_value.split())
    normalized_title = " ".join(title.split())
    if not normalized_title:
        return compacted
    prefix = f"{normalized_title} "
    while compacted.casefold().startswith(prefix.casefold()):
        compacted = compacted[len(prefix) :].lstrip()
    return compacted


def _evidence_snippet(text_value: str, title: str, query: str) -> str:
    evidence_text = _snippet_without_title_prefix(text_value, title)
    return _compact(snippet_for(evidence_text, query, window=280))


def _agent_result_label(result: RetrievalCandidate) -> str:
    source = result.source_system.replace("_", " ").title() or "Source"
    record_type = result.record_type.replace("_", " ") or "record"
    return f"{source} {record_type}"


def _json_string_tuple(value: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return ()
    return _object_string_tuple(parsed)


def _object_string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item.strip())


def _compact(text_value: str, *, limit: int = 420) -> str:
    compacted = " ".join(text_value.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1].rstrip() + "…"
