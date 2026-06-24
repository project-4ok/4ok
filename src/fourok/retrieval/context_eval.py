from __future__ import annotations

from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext

DEFAULT_EVAL_PRINCIPAL = PrincipalContext(
    human_id="eval:human",
    agent_id="eval:agent",
    roles=(
        "operator",
        "linear:team:sales",
        "linear:team:ops",
        "workflow:renewals",
        "workflow:billing",
    ),
)


def evaluate_governed_context_retrieval(
    records: list[SourceRecord],
    cases: list[dict[str, object]],
    *,
    limit: int = 5,
    principal: PrincipalContext = DEFAULT_EVAL_PRINCIPAL,
) -> dict[str, object]:
    if limit < 1:
        raise ValueError("limit must be a positive integer")
    context = GovernedContext()
    context.ingest_source_records(records)
    case_reports = [
        _evaluate_case(context, case=case, limit=limit, principal=principal) for case in cases
    ]
    passed = sum(1 for item in case_reports if item["passed"])
    top1_hits = sum(1 for item in case_reports if item["top1_hit"])
    top3_hits = sum(1 for item in case_reports if item["top3_hit"])
    evidence_pack_cases = sum(1 for item in case_reports if item["evidence_item_count"])
    audit_cases = sum(1 for item in case_reports if item["audit_ref"])
    unacceptable_source_checks = sum(1 for item in case_reports if item["unacceptable_source_refs"])
    unacceptable_source_violations = sum(
        len(item["found_unacceptable_source_refs"]) for item in case_reports
    )
    failed = len(case_reports) - passed
    return {
        "status": "ok" if failed == 0 else "needs_review",
        "summary": {
            "cases": len(case_reports),
            "passed": passed,
            "failed": failed,
            "top1_hits": top1_hits,
            "top3_hits": top3_hits,
            "evidence_pack_cases": evidence_pack_cases,
            "audit_cases": audit_cases,
            "unacceptable_source_checks": unacceptable_source_checks,
            "unacceptable_source_violations": unacceptable_source_violations,
        },
        "cases": case_reports,
    }


def _evaluate_case(
    context: GovernedContext,
    *,
    case: dict[str, object],
    limit: int,
    principal: PrincipalContext,
) -> dict[str, object]:
    query = str(case["query"])
    expected = [item for item in case.get("expected_source_refs", []) if isinstance(item, str)]
    unacceptable = [
        item for item in case.get("unacceptable_source_refs", []) if isinstance(item, str)
    ]
    response = context.search_context(query, limit=limit, principal=principal)
    top_source_refs = [item["source_ref"] for item in response.result_candidates or []]
    found_expected = [source_ref for source_ref in expected if source_ref in top_source_refs]
    found_unacceptable = [
        source_ref for source_ref in unacceptable if source_ref in top_source_refs
    ]
    top1_hit = bool(expected and top_source_refs[:1] and top_source_refs[0] in expected)
    top3_hit = bool(expected and set(expected).intersection(top_source_refs[:3]))
    source_refs_passed = bool(found_expected) if expected else bool(top_source_refs)
    passed = source_refs_passed and not found_unacceptable
    return {
        "id": case.get("id") or query,
        "category": case.get("category") if isinstance(case.get("category"), str) else None,
        "query": query,
        "expected_source_refs": expected,
        "found_expected_source_refs": found_expected,
        "unacceptable_source_refs": unacceptable,
        "found_unacceptable_source_refs": found_unacceptable,
        "top_source_refs": top_source_refs,
        "top1_hit": top1_hit,
        "top3_hit": top3_hit,
        "passed": passed,
        "failure_reason": _failure_reason(
            source_refs_passed=source_refs_passed,
            found_unacceptable=found_unacceptable,
        ),
        "result_candidate_count": len(response.result_candidates or []),
        "evidence_item_count": len(response.evidence_items or []),
        "related_object_count": len(response.related_objects or []),
        "unresolved_candidate_count": len(response.unresolved_candidates or []),
        "limitation_count": len(response.limitations or []),
        "audit_ref": response.audit_ref,
    }


def _failure_reason(*, source_refs_passed: bool, found_unacceptable: list[str]) -> str | None:
    reasons: list[str] = []
    if not source_refs_passed:
        reasons.append("missing_expected_source_refs")
    if found_unacceptable:
        reasons.append("found_unacceptable_source_refs")
    return ",".join(reasons) if reasons else None
