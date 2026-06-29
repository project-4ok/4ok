from __future__ import annotations

import json
import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import bindparam, inspect, select, text
from sqlalchemy.engine import Engine

from fourok.retrieval.reranker import RetrievalReranker, default_rerank_rules
from fourok.retrieval.search import source_record_search_rows
from fourok.retrieval.vector_search import ChunkVectorIndex

RetrieverName = Literal["keyword", "vector"]
DEFAULT_RETRIEVAL_TOKEN_BUDGET = 2000


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
    token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET
    estimated_tokens: int = 0
    candidate_count: int = 0

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
            "token_budget": self.token_budget,
            "estimated_tokens": self.estimated_tokens,
            "candidate_count": self.candidate_count,
        }


def retrieve_augmentation(
    engine: Engine,
    source_records,
    retrieval_records,
    query: str,
    *,
    canonical_objects=None,
    entity_links=None,
    token_budget: int = DEFAULT_RETRIEVAL_TOKEN_BUDGET,
    candidate_limit: int = 40,
    retrievers: tuple[RetrieverName, ...] = ("keyword", "vector"),
) -> RetrievalAugmentationResponse:
    started = time.perf_counter()
    retriever_set = ",".join(retrievers)
    keyword_count = 0
    vector_count = 0

    try:
        if token_budget < 1:
            response = RetrievalAugmentationResponse(
                status="ok",
                results=[],
                limitations=["Token budget was below 1, so no source excerpts were returned."],
                token_budget=token_budget,
            )
            _record_retrieval_query_event(
                engine,
                status="succeeded",
                retriever_set=retriever_set,
                requested_limit=token_budget,
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
        _expand_candidates_with_direct_links(
            engine,
            source_records,
            retrieval_records,
            candidates_by_key,
            query=query,
            canonical_objects=canonical_objects,
            entity_links=entity_links,
        )
        _apply_graph_link_metrics(engine, candidates_by_key, entity_links=entity_links)
        ranked_results = _rank_and_diversify(candidates_by_key, query=query)
        results = _select_results_for_token_budget(ranked_results, token_budget=token_budget)
        searched = " and ".join(name for name in retrievers)
        if results:
            limitations.append(f"Searched {searched} candidates.")
            if len(candidates_by_key) > pre_rerank_count:
                limitations.append(
                    "Expanded candidates with one-hop direct links before reranking."
                )
        else:
            limitations.append(f"Searched {searched} candidates.")
            limitations.append("No relevant source excerpts found for the selected retrievers.")
        limitations.append("Results are source excerpts, not a final answer.")
        limitations.extend(_successful_connector_import_notes(engine))
        response = RetrievalAugmentationResponse(
            status="ok",
            results=results,
            limitations=limitations,
            token_budget=token_budget,
            estimated_tokens=_estimated_result_tokens(results),
            candidate_count=len(ranked_results),
        )
        _record_retrieval_query_event(
            engine,
            status="succeeded",
            retriever_set=retriever_set,
            requested_limit=token_budget,
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
            requested_limit=token_budget,
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
            "Cite source_ref values for factual claims. "
            "If the evidence is weak or incomplete, say so."
        ),
        "",
    ]
    if not response.results:
        lines.extend(
            [
                "No relevant source excerpts found.",
                "",
                (
                    "This usually means fourok has no imported context yet, the local "
                    "runtime is not ready, or connectors have not imported data."
                ),
                "",
                "Next:",
                "  fourok status",
                "  fourok onboard",
                "",
            ]
        )
    else:
        lines.append(
            f"Budget: {response.estimated_tokens}/{response.token_budget} estimated tokens"
        )
        lines.append("")
        for index, result in enumerate(response.results, start=1):
            lines.extend(_result_card_lines(index, result))
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
        body_text = str(metadata.get("retrieval_text") or row.get("body", row.get("snippet", "")))
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
                    body_text,
                    title,
                    query,
                    source_ref,
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


def _expand_candidates_with_direct_links(
    engine: Engine,
    source_records,
    retrieval_records,
    candidates_by_key: dict[tuple[str, int], dict[str, object]],
    *,
    query: str,
    canonical_objects=None,
    entity_links=None,
) -> None:
    if not candidates_by_key:
        return
    seed_rows = list(candidates_by_key.values())
    for seed in seed_rows:
        seed_ref = str(seed["source_ref"])
        for linked_ref in _direct_context_source_refs(
            engine,
            source_records,
            seed_ref,
            canonical_objects=canonical_objects,
            entity_links=entity_links,
        ):
            if linked_ref == seed_ref:
                continue
            row = _candidate_row_for_source_ref(
                engine,
                source_records,
                retrieval_records,
                linked_ref,
                query=query,
                score=max(float(seed.get("score", 0.0) or 0.0) * 0.5, 0.000001),
                retriever="direct-link",
                reason=f"direct link from {seed_ref}",
            )
            if row is None:
                continue
            key = (str(row["source_ref"]), int(row["unit_index"]))
            existing = candidates_by_key.get(key)
            if existing is None and not _has_substantive_snippet(row):
                continue
            if existing is None:
                candidates_by_key[key] = row
                continue
            existing["score"] = max(
                float(existing.get("score", 0.0) or 0.0), float(row["score"])
            )
            existing_retrievers = existing["retrievers"]
            assert isinstance(existing_retrievers, set)
            existing_retrievers.add("direct-link")
            _append_rerank_reason(existing, str(row["rerank_reasons"][0]))


def _apply_graph_link_metrics(
    engine: Engine,
    candidates_by_key: dict[tuple[str, int], dict[str, object]],
    *,
    entity_links=None,
) -> None:
    if entity_links is None or not candidates_by_key:
        return
    counts = _graph_link_counts(
        engine,
        entity_links,
        sorted({str(source_ref) for source_ref, _unit_index in candidates_by_key}),
    )
    for (source_ref, _unit_index), candidate in candidates_by_key.items():
        link_count = counts.get(source_ref, 0)
        if link_count <= 0 or not _has_substantive_snippet(candidate):
            continue
        candidate["graph_link_count"] = link_count
        candidate["score"] = (
            float(candidate.get("score", 0.0) or 0.0) + _graph_link_boost(link_count)
        )
        _append_rerank_reason(candidate, f"graph_link_count={link_count}")


def _append_rerank_reason(candidate: dict[str, object], reason: str) -> None:
    reasons = tuple(str(item) for item in candidate.get("rerank_reasons", ()))
    if reason in reasons:
        return
    candidate["rerank_reasons"] = (*reasons, reason)


def _has_substantive_snippet(candidate: dict[str, object]) -> bool:
    snippet = str(candidate.get("snippet", "")).strip().casefold()
    if not snippet:
        return False
    without_emails = re.sub(r"\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b", "", snippet).strip()
    return without_emails != "employee"


def _graph_link_boost(link_count: int) -> float:
    return min(0.04, math.log1p(link_count) * 0.01)


def _graph_link_counts(engine: Engine, entity_links, source_refs: list[str]) -> dict[str, int]:
    if not source_refs:
        return {}
    counts = {source_ref: 0 for source_ref in source_refs}
    outgoing = (
        select(entity_links.c.source_ref, entity_links.c.link_ref)
        .where(entity_links.c.source_ref.in_(bindparam("source_refs", expanding=True)))
        .where(entity_links.c.status.in_(["linked", "accepted"]))
    )
    incoming = (
        select(entity_links.c.object_ref, entity_links.c.link_ref)
        .where(entity_links.c.object_ref.in_(bindparam("source_refs", expanding=True)))
        .where(entity_links.c.status.in_(["linked", "accepted"]))
    )
    with engine.connect() as connection:
        for row in connection.execute(outgoing, {"source_refs": source_refs}).mappings():
            counts[str(row["source_ref"])] = counts.get(str(row["source_ref"]), 0) + 1
        for row in connection.execute(incoming, {"source_refs": source_refs}).mappings():
            counts[str(row["object_ref"])] = counts.get(str(row["object_ref"]), 0) + 1
    return counts


def _candidate_row_for_source_ref(
    engine: Engine,
    source_records,
    retrieval_records,
    source_ref: str,
    *,
    query: str,
    score: float,
    retriever: str,
    reason: str,
) -> dict[str, object] | None:
    statement = (
        select(
            source_records.c.source_ref,
            source_records.c.source_system,
            source_records.c.record_type,
            source_records.c.title,
            source_records.c.occurred_at,
            source_records.c.permission_refs,
            source_records.c.retrieval_text,
            retrieval_records.c.prepared_text,
            retrieval_records.c.unit_index,
        )
        .select_from(
            source_records.outerjoin(
                retrieval_records,
                (source_records.c.source_ref == retrieval_records.c.source_ref)
                & (retrieval_records.c.status == "current")
                & (retrieval_records.c.unit_index == 0),
            )
        )
        .where(source_records.c.source_ref == source_ref)
        .where(source_records.c.lifecycle_state == "active")
    )
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    if row is None:
        return None
    title = str(row["title"])
    text_value = str(row["retrieval_text"] or row["prepared_text"] or "")
    return {
        "source_ref": str(row["source_ref"]),
        "source_system": str(row["source_system"]),
        "record_type": str(row["record_type"]),
        "title": title,
        "occurred_at": str(row["occurred_at"]),
        "permission_refs": _json_string_tuple(str(row["permission_refs"])),
        "snippet": _evidence_snippet(text_value, title, query, source_ref),
        "score": score,
        "retrievers": {retriever},
        "rerank_reasons": (reason,),
        "unit_index": int(row["unit_index"] or 0),
    }


def _rank_and_diversify(
    candidates_by_key: dict[tuple[str, int], dict[str, object]],
    *,
    query: str,
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
    return results


def _expand_ranked_results(
    engine: Engine,
    source_records,
    retrieval_records,
    results: list[RetrievalCandidate],
    *,
    query: str,
    canonical_objects=None,
    entity_links=None,
) -> list[RetrievalCandidate]:
    if not results:
        return results
    original_refs = {result.source_ref for result in results}
    emitted_refs: set[str] = set()
    expanded: list[RetrievalCandidate] = []
    for result in results:
        expanded.append(result)
        emitted_refs.add(result.source_ref)
        for source_ref in _direct_context_source_refs(
            engine,
            source_records,
            result.source_ref,
            canonical_objects=canonical_objects,
            entity_links=entity_links,
        ):
            if source_ref in emitted_refs or source_ref in original_refs:
                continue
            candidate = _candidate_for_source_ref(
                engine,
                source_records,
                retrieval_records,
                source_ref,
                query=query,
                linked_from=result,
            )
            if candidate is None:
                continue
            expanded.append(candidate)
            emitted_refs.add(source_ref)
    return expanded


def _direct_context_source_refs(
    engine: Engine,
    source_records,
    source_ref: str,
    *,
    canonical_objects=None,
    entity_links=None,
) -> list[str]:
    refs: list[str] = []
    refs.extend(_thread_context_source_refs(engine, source_records, source_ref))
    refs.extend(
        _canonical_link_source_refs(
            engine,
            source_ref,
            canonical_objects=canonical_objects,
            entity_links=entity_links,
        )
    )
    deduped: list[str] = []
    seen = {source_ref}
    for ref in refs:
        if not ref or ref in seen:
            continue
        deduped.append(ref)
        seen.add(ref)
    return deduped


def _canonical_link_source_refs(
    engine: Engine,
    source_ref: str,
    *,
    canonical_objects=None,
    entity_links=None,
) -> list[str]:
    if canonical_objects is None or entity_links is None:
        return []
    outgoing_statement = (
        select(entity_links.c.object_ref)
        .where(entity_links.c.source_ref == source_ref)
        .where(entity_links.c.status.in_(["linked", "accepted"]))
    )
    incoming_statement = (
        select(entity_links.c.source_ref)
        .where(entity_links.c.object_ref == source_ref)
        .where(entity_links.c.status.in_(["linked", "accepted"]))
    )
    with engine.connect() as connection:
        object_refs = [
            str(row["object_ref"])
            for row in connection.execute(outgoing_statement).mappings()
            if row["object_ref"]
        ]
        refs = [
            str(row["source_ref"])
            for row in connection.execute(incoming_statement).mappings()
            if row["source_ref"]
        ]
        if object_refs:
            object_statement = select(
                canonical_objects.c.object_ref,
                canonical_objects.c.source_refs,
            ).where(canonical_objects.c.object_ref.in_(bindparam("object_refs", expanding=True)))
            for row in connection.execute(
                object_statement, {"object_refs": sorted(set(object_refs))}
            ).mappings():
                source_refs = _json_string_tuple(str(row["source_refs"]))
                refs.extend(source_refs or (str(row["object_ref"]),))
        return refs


def _thread_context_source_refs(engine: Engine, source_records, source_ref: str) -> list[str]:
    with engine.connect() as connection:
        seed = (
            connection.execute(
                select(source_records.c.thread_ref).where(source_records.c.source_ref == source_ref)
            )
            .mappings()
            .first()
        )
        if seed is None or not seed["thread_ref"]:
            return []
        statement = (
            select(source_records.c.source_ref)
            .where(source_records.c.thread_ref == str(seed["thread_ref"]))
            .where(source_records.c.source_ref != source_ref)
            .where(source_records.c.lifecycle_state == "active")
            .order_by(source_records.c.occurred_at.desc(), source_records.c.source_ref)
            .limit(3)
        )
        return [
            str(row["source_ref"])
            for row in connection.execute(statement).mappings()
            if row["source_ref"]
        ]


def _candidate_for_source_ref(
    engine: Engine,
    source_records,
    retrieval_records,
    source_ref: str,
    *,
    query: str,
    linked_from: RetrievalCandidate,
) -> RetrievalCandidate | None:
    statement = (
        select(
            source_records.c.source_ref,
            source_records.c.source_system,
            source_records.c.record_type,
            source_records.c.title,
            source_records.c.occurred_at,
            source_records.c.permission_refs,
            source_records.c.retrieval_text,
            retrieval_records.c.prepared_text,
            retrieval_records.c.unit_index,
        )
        .select_from(
            source_records.outerjoin(
                retrieval_records,
                (source_records.c.source_ref == retrieval_records.c.source_ref)
                & (retrieval_records.c.status == "current")
                & (retrieval_records.c.unit_index == 0),
            )
        )
        .where(source_records.c.source_ref == source_ref)
        .where(source_records.c.lifecycle_state == "active")
    )
    with engine.connect() as connection:
        row = connection.execute(statement).mappings().first()
    if row is None:
        return None
    title = str(row["title"])
    text_value = str(row["retrieval_text"] or row["prepared_text"] or "")
    return RetrievalCandidate(
        source_ref=str(row["source_ref"]),
        source_system=str(row["source_system"]),
        record_type=str(row["record_type"]),
        title=title,
        occurred_at=str(row["occurred_at"]),
        snippet=_evidence_snippet(text_value, title, query, source_ref),
        score=round(max(linked_from.score * 0.5, 0.000001), 6),
        retrievers=("direct-context",),
        permission_refs=_json_string_tuple(str(row["permission_refs"])),
        rerank_reasons=(f"direct context for {linked_from.source_ref}",),
        unit_index=int(row["unit_index"] or 0),
    )


def _select_results_for_token_budget(
    results: list[RetrievalCandidate], *, token_budget: int
) -> list[RetrievalCandidate]:
    selected: list[RetrievalCandidate] = []
    used = 0
    for result in results:
        next_index = len(selected) + 1
        card_tokens = _estimate_tokens("\n".join(_result_card_lines(next_index, result)))
        if selected and used + card_tokens > token_budget:
            break
        selected.append(result)
        used += card_tokens
        if used >= token_budget:
            break
    return selected


def _estimated_result_tokens(results: list[RetrievalCandidate]) -> int:
    return sum(
        _estimate_tokens("\n".join(_result_card_lines(index, result)))
        for index, result in enumerate(results, start=1)
    )


def _result_card_lines(index: int, result: RetrievalCandidate) -> list[str]:
    why_relevant = ", ".join(result.rerank_reasons) or "specific source excerpt"
    return [
        f"[{index}] {_agent_result_label(result)} — {result.title or '(untitled)'}",
        f"source_ref: {result.source_ref}",
        f"why_relevant: {why_relevant}",
        f"date: {_source_date_label(result.occurred_at)}",
        *_evidence_card_lines(result.snippet),
        "",
    ]


def _evidence_card_lines(snippet: str) -> list[str]:
    if "\n" not in snippet:
        return [f"evidence: {snippet}"]
    return ["evidence:", *snippet.splitlines()]


def _source_date_label(value: str, *, now: datetime | None = None) -> str:
    if not value:
        return "unknown"
    parsed = _parse_source_datetime(value)
    if parsed is None:
        return value
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    now_utc = now_utc.astimezone(UTC)
    source_time = parsed.astimezone(UTC)
    day_delta = (now_utc.date() - source_time.date()).days
    source_day = source_time.date().isoformat()
    if day_delta == 0:
        relative = "today"
    elif day_delta == 1:
        relative = "yesterday"
    elif day_delta > 1:
        relative = f"{day_delta} days ago"
    elif day_delta == -1:
        relative = "tomorrow"
    else:
        relative = f"in {abs(day_delta)} days"
    return f"{relative} ({source_day})"


def _parse_source_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _estimate_tokens(text_value: str) -> int:
    return max(1, (len(text_value) + 3) // 4)


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
        source_records.c.retrieval_text,
        source_records.c.occurred_at,
        source_records.c.permission_refs,
    ).where(source_records.c.source_ref.in_(bindparam("source_refs", expanding=True)))
    with engine.connect() as connection:
        return {
            str(row["source_ref"]): {
                "source_system": str(row["source_system"]),
                "record_type": str(row["record_type"]),
                "title": str(row["title"]),
                "retrieval_text": str(row["retrieval_text"]),
                "occurred_at": str(row["occurred_at"]),
                "permission_refs": _json_string_tuple(str(row["permission_refs"])),
            }
            for row in connection.execute(statement, {"source_refs": unique_refs}).mappings()
        }


def _vector_rows(engine: Engine, query: str, *, limit: int) -> list[dict[str, object]]:
    try:
        vector_results = ChunkVectorIndex(
            engine, recreate_mismatched_schema=False
        ).search(query, limit=limit)
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


def _successful_connector_import_notes(engine: Engine) -> list[str]:
    try:
        if not inspect(engine).has_table("connector_job_runs"):
            return []
        with engine.connect() as connection:
            rows = [
                dict(row)
                for row in connection.execute(
                    text(
                        """
                        SELECT connector_name, status, finished_at
                        FROM connector_job_runs
                        WHERE status = 'succeeded' AND finished_at IS NOT NULL AND finished_at != ''
                        ORDER BY finished_at DESC, connector_name
                        """
                    )
                ).mappings()
            ]
    except Exception:
        return []
    latest_by_source: dict[str, str] = {}
    for row in rows:
        source = str(row.get("connector_name") or "").removesuffix("-live")
        finished_at = str(row.get("finished_at") or "")
        if source and source not in latest_by_source:
            latest_by_source[source] = finished_at
    if not latest_by_source:
        return []
    now = datetime.now(UTC)
    parts = [
        f"{source} succeeded {_relative_age(finished_at, now)}"
        for source, finished_at in sorted(latest_by_source.items())
    ]
    return ["Connector imports: " + "; ".join(parts) + "."]


def _relative_age(finished_at: str, now: datetime) -> str:
    try:
        finished = datetime.fromisoformat(finished_at)
    except ValueError:
        return "at unknown time"
    if finished.tzinfo is None:
        finished = finished.replace(tzinfo=UTC)
    seconds = max(0, int((now - finished).total_seconds()))
    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} h ago"
    days = hours // 24
    return f"{days} d ago"


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


def _snippet_without_title_prefix(text_value: str, title: str, source_ref: str = "") -> str:
    evidence = text_value.strip()
    identifier = source_ref.rsplit(":", 1)[-1] if source_ref else ""
    prefixes = [
        " ".join(part.split())
        for part in [
            f"{identifier} {title}" if identifier and title else "",
            title,
            identifier,
        ]
        if part and part.strip()
    ]
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            pattern = r"^\s*" + r"\s+".join(re.escape(part) for part in prefix.split())
            match = re.match(pattern + r"(?:\s+|$)", evidence, flags=re.IGNORECASE)
            if match:
                evidence = evidence[match.end() :].lstrip()
                changed = True
    return evidence


def _evidence_snippet(text_value: str, title: str, query: str, source_ref: str = "") -> str:
    evidence_text = _snippet_without_title_prefix(text_value, title, source_ref)
    return _compact_preserving_paragraphs(
        _paragraph_snippet_for(evidence_text, query, window=900), limit=1200
    )


def _paragraph_snippet_for(text_value: str, query: str, *, window: int) -> str:
    normalized_text = _normalize_evidence_text(text_value)
    if not normalized_text:
        return ""
    lower_text = normalized_text.casefold()
    terms = [term.strip().casefold().strip('"') for term in query.split() if term.strip()]
    first_index = min(
        (index for term in terms if (index := lower_text.find(term)) >= 0),
        default=0,
    )
    start = max(first_index - window // 2, 0)
    end = min(start + window, len(normalized_text))
    snippet = normalized_text[start:end].strip()
    if start > 0:
        snippet = f"... {snippet}"
    if end < len(normalized_text):
        snippet = f"{snippet} ..."
    return snippet


def _normalize_evidence_text(text_value: str) -> str:
    lines = [" ".join(line.split()) for line in text_value.replace("\r\n", "\n").split("\n")]
    normalized: list[str] = []
    previous_blank = True
    for line in lines:
        if not line:
            if not previous_blank:
                normalized.append("")
            previous_blank = True
            continue
        normalized.append(line)
        previous_blank = False
    while normalized and not normalized[-1]:
        normalized.pop()
    return "\n".join(normalized)


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


def _compact_preserving_paragraphs(text_value: str, *, limit: int = 420) -> str:
    compacted = _normalize_evidence_text(text_value)
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1].rstrip() + "…"


def _compact(text_value: str, *, limit: int = 420) -> str:
    compacted = " ".join(text_value.split())
    if len(compacted) <= limit:
        return compacted
    return compacted[: limit - 1].rstrip() + "…"
