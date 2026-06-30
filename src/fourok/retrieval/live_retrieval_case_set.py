from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fourok.etl.extract.connectors import (
    load_google_drive_source_records,
    load_linear_source_records,
    load_slack_source_records,
    load_twenty_source_records,
)
from fourok.etl.extract.source_records import SourceRecord
from fourok.governance import GovernedContext
from fourok.governance.policy import PrincipalContext
from fourok.runtime.source_imports import import_source_records

DEFAULT_CASES_PATH = Path("tests/fixtures/retrieval_eval/live_retrieval_case_set.json")
DEFAULT_REPORT_PATH = Path(".local/codex-runs/live-retrieval-case-set/report.md")
DEFAULT_SLACK_FIXTURE = Path("tests/fixtures/connectors/singer_slack_messages.jsonl")
DEFAULT_GOOGLE_DRIVE_FIXTURE = Path(
    "tests/fixtures/connectors/singer_google_drive_metadata_only.jsonl"
)
DEFAULT_LINEAR_FIXTURE = Path("tests/fixtures/connectors/singer_linear_work_items.jsonl")
DEFAULT_TWENTY_FIXTURE = Path("tests/fixtures/connectors/singer_twenty_crm.jsonl")


@dataclass(frozen=True)
class LiveRetrievalCase:
    case_id: str
    query: str
    expected_source_ref_prefix: str
    expected_source_system: str
    expected_record_type: str
    expected_permission_refs: tuple[str, ...]


def default_live_cases_path() -> Path:
    return DEFAULT_CASES_PATH


def run_live_retrieval_case_set(
    *,
    context: GovernedContext,
    cases_path: Path,
    seed_fixtures: bool,
    case_limit: int,
    report_path: Path,
) -> dict[str, object]:
    if case_limit < 1:
        raise SystemExit("--case-limit must be a positive integer")

    cases = load_live_retrieval_cases(cases_path)
    seed_report = None
    if seed_fixtures:
        seed_report = seed_live_retrieval_fixtures(context)

    case_reports = [
        evaluate_live_retrieval_case(
            context=context,
            case=case,
            result_limit=case_limit,
        )
        for case in cases
    ]

    passed = sum(1 for item in case_reports if item["passed"])
    failed = len(case_reports) - passed
    report: dict[str, object] = {
        "status": "ok" if failed == 0 else "needs_review",
        "seed_fixtures": seed_fixtures,
        "case_limit": case_limit,
        "cases_path": str(cases_path),
        "summary": {
            "cases": len(case_reports),
            "passed": passed,
            "failed": failed,
        },
        "cases": case_reports,
    }
    if seed_report is not None:
        report["seed_report"] = seed_report

    write_live_retrieval_case_report(report=report, report_path=report_path)
    return report


def load_live_retrieval_cases(path: Path) -> list[LiveRetrievalCase]:
    raw_cases = _read_json(path)
    if not isinstance(raw_cases, list):
        raise SystemExit("cases file must contain a JSON list")

    cases: list[LiveRetrievalCase] = []
    for item in raw_cases:
        if not isinstance(item, dict):
            raise SystemExit("case entries must be objects")
        case_id = str(item.get("id") or "case")
        query = _required_string(item, "query")
        expected_source_ref_prefix = _required_string(item, "expected_source_ref_prefix")
        expected_source_system = _required_string(item, "expected_source_system")
        expected_record_type = _required_string(item, "expected_record_type")
        expected_permission_refs = _string_tuple(item.get("expected_permission_refs", ()))
        cases.append(
            LiveRetrievalCase(
                case_id=case_id,
                query=query,
                expected_source_ref_prefix=expected_source_ref_prefix,
                expected_source_system=expected_source_system,
                expected_record_type=expected_record_type,
                expected_permission_refs=expected_permission_refs,
            )
        )
    if not cases:
        raise SystemExit("cases file must contain at least one case")
    return cases


def evaluate_live_retrieval_case(
    *,
    context: GovernedContext,
    case: LiveRetrievalCase,
    result_limit: int,
) -> dict[str, object]:
    principal = PrincipalContext(
        human_id="local-human",
        agent_id="local-agent",
        roles=case.expected_permission_refs or ("operator",),
    )
    response = context.search_context(
        case.query,
        limit=result_limit,
        principal=principal,
    )

    result_source_refs = [_to_source_ref(result) for result in response.results]
    matching_results = [
        source_ref
        for source_ref in result_source_refs
        if source_ref.startswith(case.expected_source_ref_prefix)
    ]
    evidence_items = [
        _normalize_evidence_item(item)
        for item in (response.evidence_items or [])
        if isinstance(item, dict)
    ]
    matching_evidence = [
        item
        for item in evidence_items
        if item.get("source_ref", "").startswith(case.expected_source_ref_prefix)
    ]
    evidence_item = matching_evidence[0] if matching_evidence else None

    failure_reasons: list[str] = []
    if not matching_results:
        failure_reasons.append("expected_source_ref_not_found_in_results")
    if evidence_item is None:
        failure_reasons.append("expected_source_ref_not_found_in_evidence")

    if evidence_item is not None:
        if evidence_item.get("source_system") != case.expected_source_system:
            failure_reasons.append("source_system_mismatch")
        if evidence_item.get("record_type") != case.expected_record_type:
            failure_reasons.append("record_type_mismatch")

        permission_refs = evidence_item.get("permission_refs")
        if not isinstance(permission_refs, list):
            failure_reasons.append("evidence_permission_refs_missing")
        elif case.expected_permission_refs and not set(case.expected_permission_refs).issubset(
            set(permission_refs)
        ):
            failure_reasons.append("missing_expected_permission_refs")

    passed = len(failure_reasons) == 0
    return {
        "id": case.case_id,
        "query": case.query,
        "expected_source_ref_prefix": case.expected_source_ref_prefix,
        "expected_source_system": case.expected_source_system,
        "expected_record_type": case.expected_record_type,
        "expected_permission_refs": list(case.expected_permission_refs),
        "result_count": len(response.results),
        "matched_source_refs": matching_results,
        "result_source_refs": result_source_refs,
        "evidence_source_refs": [item.get("source_ref") for item in evidence_items],
        "evidence_item": evidence_item or {},
        "failure_reason": failure_reasons[0] if failure_reasons else None,
        "all_failure_reasons": failure_reasons,
        "passed": passed,
    }


def seed_live_retrieval_fixtures(context: GovernedContext) -> dict[str, object]:
    records = _load_live_retrieval_fixtures()
    report = import_source_records(context, records)
    return report.to_dict()


def write_live_retrieval_case_report(
    *,
    report: dict[str, object],
    report_path: Path,
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    summary = report.get("summary", {})
    lines = [
        "# Live Retrieval Case Set Check Report",
        f"- status: {report.get('status', 'needs_review')}",
        f"- seed_fixtures: {report.get('seed_fixtures')}",
        f"- case_limit: {report.get('case_limit')}",
        f"- cases_path: {report.get('cases_path')}",
        "",
        "## Summary",
        f"- cases: {summary.get('cases')}",
        f"- passed: {summary.get('passed')}",
        f"- failed: {summary.get('failed')}",
        "",
        "## Cases",
    ]

    for case in report.get("cases", []):
        if not isinstance(case, dict):
            continue
        case_status = "PASS" if case.get("passed") else "FAIL"
        lines.extend(
            [
                f"### {case.get('id')} ({case_status})",
                f"- query: {case.get('query')}",
                f"- expected_source_ref_prefix: {case.get('expected_source_ref_prefix')}",
                f"- matched_source_refs: {case.get('matched_source_refs')}",
                f"- evidence_source_ref: {case.get('evidence_item', {}).get('source_ref')}",
                f"- evidence_source_system: {case.get('evidence_item', {}).get('source_system')}",
                f"- evidence_record_type: {case.get('evidence_item', {}).get('record_type')}",
                "- evidence_permission_refs: "
                f"{case.get('evidence_item', {}).get('permission_refs')}",
                f"- failure_reason: {case.get('failure_reason')}",
                "",
            ]
        )

    lines.extend(
        [
            "## Exact Report",
            "```json",
            json.dumps(report, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_live_retrieval_fixtures() -> list[SourceRecord]:
    records: list[SourceRecord] = []
    records.extend(load_slack_source_records(DEFAULT_SLACK_FIXTURE))
    records.extend(load_google_drive_source_records(DEFAULT_GOOGLE_DRIVE_FIXTURE))
    records.extend(load_linear_source_records(DEFAULT_LINEAR_FIXTURE))
    records.extend(load_twenty_source_records(DEFAULT_TWENTY_FIXTURE))
    return records


def _to_source_ref(result: object) -> str:
    return str(getattr(result, "source_ref", ""))


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"could not read cases file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"cases file is not valid JSON: {path}") from exc


def _required_string(item: dict[str, object], key: str) -> str:
    raw = item.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise SystemExit(f"case requires string {key}")
    return raw.strip()


def _string_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(value.strip() for value in values if isinstance(value, str) and value.strip())


def _normalize_evidence_item(item: dict[str, object]) -> dict[str, object]:
    source_ref = item.get("source_ref")
    source_system = item.get("source_system")
    record_type = item.get("record_type")
    permission_refs = item.get("permission_refs")
    if isinstance(permission_refs, list):
        normalized_permissions = [
            value for value in permission_refs if isinstance(value, str) and value.strip()
        ]
    else:
        normalized_permissions = permission_refs
    return {
        "source_ref": str(source_ref) if source_ref else "",
        "source_system": str(source_system) if isinstance(source_system, str) else "",
        "record_type": str(record_type) if isinstance(record_type, str) else "",
        "permission_refs": normalized_permissions,
        "source_type": item.get("source_type") if isinstance(item.get("source_type"), str) else "",
    }
