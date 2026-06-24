from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from gcb.devtools.dev import dagster_status_report
from gcb.governance import GovernedContext
from gcb.governance.state import create_governed_context_state
from gcb.retrieval.live_retrieval_case_set import run_live_retrieval_case_set
from gcb.storage.health import check_runtime_health

Check = Callable[[], dict[str, object]]


def stage1_acceptance_report(
    *,
    health: Check,
    retrieval: Check,
    permission: Check,
    dagster: Check,
    grafana: Check,
) -> dict[str, object]:
    details = {
        "health": health(),
        "retrieval": retrieval(),
        "permission": permission(),
        "dagster": dagster(),
        "grafana": grafana(),
    }
    checks = {name: str(report.get("status", "failed")) for name, report in details.items()}
    report = {
        "status": "ok" if all(status == "ok" for status in checks.values()) else "failed",
        "checks": checks,
        **details,
    }
    report["resume"] = _resume_state(checks)
    return report


def _resume_state(checks: dict[str, str]) -> dict[str, object]:
    open_gates = [name for name, status in checks.items() if status != "ok"]
    return {
        "open_gates": open_gates,
        "last_verification": "uv run gcb stage1-acceptance --json",
        "blockers": open_gates,
        "next_command": (
            "uv run gcb stage1-acceptance --json"
            if open_gates
            else "Start Stage 2 OpenClaw plugin before-prompt RAG summary."
        ),
    }


def run_stage1_acceptance(
    *,
    state_path: Path,
    database_url: str | None,
    cases_path: Path,
    case_limit: int,
    report_path: Path,
    dagster_url: str,
    grafana_url: str,
    skip_dagster: bool = False,
    skip_grafana: bool = False,
) -> dict[str, object]:
    retrieval_holder: dict[str, object] = {}

    def health() -> dict[str, object]:
        state = create_governed_context_state(
            state_path=state_path,
            database_url=database_url,
            raw_store_path=None,
        )
        return check_runtime_health(state)

    def retrieval() -> dict[str, object]:
        context = GovernedContext(state_path, database_url=database_url)
        report = run_live_retrieval_case_set(
            context=context,
            cases_path=cases_path,
            seed_fixtures=False,
            case_limit=case_limit,
            report_path=report_path,
        )
        retrieval_holder.clear()
        retrieval_holder.update(report)
        return report

    def _has_expected_permission_refs(case: dict[str, object]) -> bool:
        permission_refs = case.get("expected_permission_refs")
        return isinstance(permission_refs, list) and bool(permission_refs)

    def permission() -> dict[str, object]:
        report = retrieval_holder or retrieval()
        cases = [case for case in report.get("cases", []) if isinstance(case, dict)]
        permission_cases = [case for case in cases if _has_expected_permission_refs(case)]
        failed = [case.get("id") for case in permission_cases if not case.get("passed")]
        if not permission_cases:
            return {"status": "skipped", "checked_cases": 0, "failed_cases": []}
        return {
            "status": "ok" if not failed else "needs_review",
            "checked_cases": len(permission_cases),
            "failed_cases": failed,
        }

    def dagster() -> dict[str, object]:
        if skip_dagster:
            return {"status": "skipped"}
        report = dagster_status_report(dagster_url=dagster_url)
        return _dagster_gate_report(report)

    def grafana() -> dict[str, object]:
        if skip_grafana:
            return {"status": "skipped"}
        return grafana_dashboard_report(grafana_url=grafana_url)

    return stage1_acceptance_report(
        health=health,
        retrieval=retrieval,
        permission=permission,
        dagster=dagster,
        grafana=grafana,
    )


def _dagster_gate_report(report: dict[str, object]) -> dict[str, object]:
    schedules = cast(dict[str, object], report.get("schedules", {}))
    sensors = cast(dict[str, object], report.get("sensors", {}))
    schedule_ok = bool(schedules) and all(value == "RUNNING" for value in schedules.values())
    sensor_ok = bool(sensors) and all(value == "RUNNING" for value in sensors.values())
    runtime_status = cast(dict[str, object], report.get("runtime_status", {}))
    status = (
        "ok"
        if report.get("repository_status") == "ok"
        and schedule_ok
        and sensor_ok
        and runtime_status.get("status") == "ok"
        else "failed"
    )
    return {**report, "status": status}


def grafana_dashboard_report(
    *,
    grafana_url: str,
    dashboard_uid: str = "gcb-local-runtime-logs",
) -> dict[str, object]:
    base = grafana_url.rstrip("/")
    try:
        health = _get_json(f"{base}/api/health")
        dashboard = _get_json(f"{base}/api/dashboards/uid/{urllib.parse.quote(dashboard_uid)}")
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {
            "status": "failed",
            "error_class": type(exc).__name__,
            "dashboard_uid": dashboard_uid,
        }

    panels = dashboard.get("dashboard", {}).get("panels", [])
    titles = [panel.get("title") for panel in panels if isinstance(panel, dict)]
    required = {
        "[Pipeline] Dagster schedule running",
        "[Pipeline] Webhook sensor running",
        "[Logs] Latest 5 runtime errors by service",
    }
    missing = sorted(required - set(titles))
    freshness_query = (
        "(time() - gcb_dagster_last_success_timestamp_seconds"
        '{exported_job="gcb_hourly_live_backfill"}) / 60'
    )
    backfill_freshness = _grafana_prometheus_instant_query(base, freshness_query)
    minutes_since_success = backfill_freshness.get("value")
    freshness_ok = isinstance(minutes_since_success, int | float) and minutes_since_success <= 65
    return {
        "status": (
            "ok" if health.get("database") == "ok" and not missing and freshness_ok else "failed"
        ),
        "database": health.get("database"),
        "version": health.get("version"),
        "dashboard_uid": dashboard_uid,
        "dashboard_title": dashboard.get("dashboard", {}).get("title"),
        "panel_count": len(titles),
        "missing_required_panels": missing,
        "minutes_since_successful_hourly_backfill": minutes_since_success,
        "max_minutes_since_successful_hourly_backfill": 65,
        "backfill_freshness_query_status": backfill_freshness.get("status"),
    }


def _grafana_prometheus_instant_query(base_url: str, query: str) -> dict[str, object]:
    url = (
        f"{base_url}/api/datasources/proxy/uid/prometheus/api/v1/query?"
        f"{urllib.parse.urlencode({'query': query})}"
    )
    try:
        response = _get_json(url)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        return {"status": "failed", "error_class": type(exc).__name__, "value": None}
    results = response.get("data", {}).get("result", [])
    if not isinstance(results, list) or not results:
        return {"status": "failed", "reason": "no_series", "value": None}
    first = results[0]
    if not isinstance(first, dict):
        return {"status": "failed", "reason": "invalid_series", "value": None}
    sample = first.get("value")
    if not isinstance(sample, list) or len(sample) < 2:
        return {"status": "failed", "reason": "invalid_sample", "value": None}
    try:
        value = float(sample[1])
    except (TypeError, ValueError):
        return {"status": "failed", "reason": "invalid_value", "value": None}
    return {"status": "ok", "value": value, "query": query}


def _get_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))
