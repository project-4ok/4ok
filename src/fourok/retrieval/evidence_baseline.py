from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fourok.honcho.experiment import build_honcho_sync_plan


@dataclass(frozen=True)
class EvidenceRecord:
    source_ref: str
    source: str
    source_type: str
    text: str
    source_url: str | None
    source_updated_at: str | None
    entities: list[str]
    permission_refs: list[str]
    metadata: dict[str, object]


def search_evidence(data: dict[str, object], query: str, *, limit: int = 5) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    records = _evidence_records(data)
    scored = _rank_records(records, query=query)
    evidence = [_record_to_result(record, score=score) for score, record in scored[:limit]]
    return {
        "query": query,
        "summary": _summary(evidence, source_count=len(records)),
        "evidence": evidence,
    }


def evaluate_evidence_baseline(
    data: dict[str, object],
    cases: list[dict[str, object]],
    *,
    limit: int = 5,
) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    case_reports = [_evaluate_case(data, case=case, limit=limit) for case in cases]
    passed = sum(1 for item in case_reports if item["passed"])
    top1_hits = sum(1 for item in case_reports if item["top1_hit"])
    top3_hits = sum(1 for item in case_reports if item["top3_hit"])
    provenance_cases = sum(1 for item in case_reports if item["top_source_refs"])
    failed = len(case_reports) - passed
    return {
        "status": "ok" if failed == 0 else "needs_review",
        "summary": {
            "cases": len(case_reports),
            "passed": passed,
            "failed": failed,
            "top1_hits": top1_hits,
            "top3_hits": top3_hits,
            "provenance_cases": provenance_cases,
        },
        "cases": case_reports,
    }


def _evidence_records(data: dict[str, object]) -> list[EvidenceRecord]:
    plan = build_honcho_sync_plan(data)
    records: list[EvidenceRecord] = []
    for message in plan.messages:
        metadata = {
            key: value
            for key, value in message.metadata.items()
            if key not in {"source", "source_ref", "source_url", "source_updated_at"}
        }
        records.append(
            EvidenceRecord(
                source_ref=str(message.metadata["source_ref"]),
                source=str(message.metadata["source"]),
                source_type="message",
                text=message.text,
                source_url=_optional_string(message.metadata.get("source_url")),
                source_updated_at=_optional_string(message.metadata.get("source_updated_at")),
                entities=_entities_from_metadata(message.metadata),
                permission_refs=_string_list(message.metadata.get("permission_refs")),
                metadata=metadata,
            )
        )
    for source_ref, record in plan.source_imports.items():
        records.append(
            EvidenceRecord(
                source_ref=source_ref,
                source=record["source"],
                source_type=record["source_type"],
                text=_catalog_text(source_ref, record),
                source_url=None,
                source_updated_at=None,
                entities=_catalog_entities(record),
                permission_refs=[],
                metadata={
                    key: value
                    for key, value in record.items()
                    if key not in {"source", "source_type", "entity_ref"}
                },
            )
        )
    return records


def _rank_records(records: list[EvidenceRecord], *, query: str) -> list[tuple[int, EvidenceRecord]]:
    query_tokens = _tokens(query)
    minimum_score = 2 if len(query_tokens) > 1 else 1
    scored = [
        (score, record)
        for record in records
        if (score := _score_record(record, query_tokens=query_tokens)) >= minimum_score
    ]
    return sorted(scored, key=lambda item: (-item[0], item[1].source_ref))


def _score_record(record: EvidenceRecord, *, query_tokens: set[str]) -> int:
    haystack_tokens = _tokens(
        " ".join(
            [
                record.source_ref,
                record.source,
                record.source_type,
                record.text,
                " ".join(record.entities),
                " ".join(str(value) for value in record.metadata.values()),
            ]
        )
    )
    score = len(query_tokens.intersection(haystack_tokens))
    if (
        "employee" in query_tokens
        and record.source_type in {"user", "workspace_member"}
        and record.entities
    ):
        score += 2
    return score


def _record_to_result(record: EvidenceRecord, *, score: int) -> dict[str, object]:
    result: dict[str, object] = {
        "source_ref": record.source_ref,
        "source": record.source,
        "source_type": record.source_type,
        "score": score,
        "title": record.source_ref,
        "snippet": _snippet(record.text),
        "source_url": record.source_url,
        "source_updated_at": record.source_updated_at,
        "entities": record.entities,
        "permission_refs": record.permission_refs,
        "metadata": record.metadata,
    }
    return result


def _evaluate_case(
    data: dict[str, object],
    *,
    case: dict[str, object],
    limit: int,
) -> dict[str, object]:
    query = str(case["query"])
    expected = [item for item in case.get("expected_source_refs", []) if isinstance(item, str)]
    expected_entities = [
        item for item in case.get("expected_entities", []) if isinstance(item, str)
    ]
    expected_permission_refs = [
        item for item in case.get("expected_permission_refs", []) if isinstance(item, str)
    ]
    pack = search_evidence(data, query, limit=limit)
    top_source_refs = [item["source_ref"] for item in pack["evidence"] if item.get("source_ref")]
    top_entities = _top_entities(pack["evidence"])
    top_permission_refs = _top_permission_refs(pack["evidence"])
    found_expected = [source_ref for source_ref in expected if source_ref in top_source_refs]
    found_entities = [entity for entity in expected_entities if entity in top_entities]
    found_permission_refs = [ref for ref in expected_permission_refs if ref in top_permission_refs]
    top1_hit = bool(expected and top_source_refs[:1] and top_source_refs[0] in expected)
    top3_hit = bool(expected and set(expected).intersection(top_source_refs[:3]))
    source_refs_passed = bool(found_expected) if expected else bool(top_source_refs)
    entities_passed = bool(found_entities) if expected_entities else True
    permissions_passed = bool(found_permission_refs) if expected_permission_refs else True
    passed = source_refs_passed and entities_passed and permissions_passed
    return {
        "id": case.get("id") or query,
        "category": case.get("category") if isinstance(case.get("category"), str) else None,
        "query": query,
        "expected_source_refs": expected,
        "found_expected_source_refs": found_expected,
        "expected_entities": expected_entities,
        "found_expected_entities": found_entities,
        "expected_permission_refs": expected_permission_refs,
        "found_expected_permission_refs": found_permission_refs,
        "top_source_refs": top_source_refs,
        "top_entities": top_entities,
        "top_permission_refs": top_permission_refs,
        "top1_hit": top1_hit,
        "top3_hit": top3_hit,
        "passed": passed,
        "failure_reason": _failure_reason(
            source_refs_passed=source_refs_passed,
            entities_passed=entities_passed,
            permissions_passed=permissions_passed,
        ),
        "result_count": len(pack["evidence"]),
        "top_evidence": pack["evidence"][:1],
    }


def _top_entities(evidence: list[dict[str, object]]) -> list[str]:
    entities: list[str] = []
    for item in evidence:
        value = item.get("entities")
        if not isinstance(value, list):
            continue
        for entity in value:
            if isinstance(entity, str) and entity not in entities:
                entities.append(entity)
    return entities


def _top_permission_refs(evidence: list[dict[str, object]]) -> list[str]:
    permission_refs: list[str] = []
    for item in evidence:
        value = item.get("permission_refs")
        if not isinstance(value, list):
            continue
        for ref in value:
            if isinstance(ref, str) and ref not in permission_refs:
                permission_refs.append(ref)
    return permission_refs


def _failure_reason(
    *,
    source_refs_passed: bool,
    entities_passed: bool,
    permissions_passed: bool,
) -> str | None:
    reasons: list[str] = []
    if not source_refs_passed:
        reasons.append("missing_expected_source_refs")
    if not entities_passed:
        reasons.append("missing_expected_entities")
    if not permissions_passed:
        reasons.append("missing_expected_permission_refs")
    return ",".join(reasons) if reasons else None


def _summary(evidence: list[dict[str, object]], *, source_count: int) -> str:
    if not evidence:
        return f"No indexed records matched. 0 of {source_count} indexed records matched."
    top = evidence[0]
    return (
        f"Top evidence: {top['source_ref']} from {top['source']}. "
        f"{len(evidence)} of {source_count} indexed records matched."
    )


def _catalog_text(source_ref: str, record: dict[str, str]) -> str:
    values = [source_ref, record["source"], record["source_type"]]
    values.extend(value for key, value in record.items() if key not in {"source", "source_type"})
    return " ".join(values)


def _entities_from_metadata(metadata: dict[str, object]) -> list[str]:
    entities: list[str] = []
    for key in ("candidate_entities", "actors", "assignees", "employee_peer"):
        _extend_entities(entities, metadata.get(key))
    return entities


def _catalog_entities(record: dict[str, str]) -> list[str]:
    entity_ref = record.get("entity_ref")
    return [entity_ref] if entity_ref else []


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _extend_entities(entities: list[str], value: object) -> None:
    if isinstance(value, str) and value.startswith("employee:") and value not in entities:
        entities.append(value)
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.startswith("employee:") and item not in entities:
                entities.append(item)


def _tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", value.lower()) if token}


def _snippet(value: str, *, limit: int = 240) -> str:
    return value if len(value) <= limit else f"{value[:limit].rstrip()}..."


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
