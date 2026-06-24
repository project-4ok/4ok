from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

DASHBOARD_UID = "fourok-local-runtime-logs"
DEFAULT_GRAFANA_URL = "http://127.0.0.1:3000"

PROMETHEUS_SIGNALS = {
    "fourok_source_records_total": "fourok_source_records_total",
    "fourok_retrieval_records_total": "fourok_retrieval_records_total",
    "fourok_retrieval_requests_total": "fourok_retrieval_requests_total",
    "fourok_embedding_coverage_ratio": "fourok_embedding_coverage_ratio",
    "fourok_dagster_last_success_timestamp_seconds": (
        'fourok_dagster_last_success_timestamp_seconds{exported_job="fourok_hourly_live_backfill"}'
    ),
}

HttpGet = Callable[[str, dict[str, str] | None], Any]


def grafana_report(
    *,
    grafana_url: str = DEFAULT_GRAFANA_URL,
    http_get: HttpGet | None = None,
) -> dict[str, Any]:
    """Return an agent-readable summary of the fourok Grafana dashboard.

    The agent accesses Grafana through its HTTP API: health, dashboard search,
    datasource inventory, Prometheus datasource proxy, and Loki datasource proxy.
    This keeps Grafana as the human overview while giving agents a deterministic
    CLI surface for the same source of operational truth.
    """
    base_url = grafana_url.rstrip("/")
    get = http_get or _http_get(base_url)
    report: dict[str, Any] = {
        "status": "ok",
        "access": {
            "method": "grafana_http_api",
            "base_url": base_url,
            "dashboard_uid": DASHBOARD_UID,
        },
        "dashboard": {"uid": DASHBOARD_UID, "title": None, "url": None},
        "datasources": {},
        "signals": {},
        "recommendations": [],
    }

    _record_health(report, get)
    _record_dashboard(report, base_url, get)
    _record_datasources(report, get)
    _record_prometheus_signals(report, get)
    _record_loki_signal(report, get)
    _finalize_status(report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fourok-agent-grafana")
    parser.add_argument("--grafana-url", default=DEFAULT_GRAFANA_URL)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args(argv)

    report = grafana_report(grafana_url=args.grafana_url)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(_format_text(report))
    return 0 if report["status"] == "ok" else 1


def _http_get(base_url: str) -> HttpGet:
    def get(path: str, params: dict[str, str] | None = None) -> Any:
        query = ""
        if params:
            query = "?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(f"{base_url}{path}{query}", timeout=15) as response:
            return json.load(response)

    return get


def _record_health(report: dict[str, Any], get: HttpGet) -> None:
    try:
        health = get("/api/health", None)
        report["health"] = health
        if health.get("database") != "ok":
            report["recommendations"].append("grafana_health_not_ok")
    except Exception as exc:
        report["health"] = {"error": str(exc)}
        report["recommendations"].append("grafana_unreachable")


def _record_dashboard(report: dict[str, Any], base_url: str, get: HttpGet) -> None:
    try:
        dashboards = get("/api/search", {"type": "dash-db", "query": "fourok"})
    except Exception as exc:
        report["dashboard"]["error"] = str(exc)
        report["recommendations"].append("dashboard_search_failed")
        return

    matches = [item for item in dashboards if item.get("uid") == DASHBOARD_UID]
    if not matches:
        report["recommendations"].append("dashboard_missing")
        return

    dashboard = matches[0]
    url = dashboard.get("url")
    report["dashboard"] = {
        "uid": DASHBOARD_UID,
        "title": dashboard.get("title"),
        "url": f"{base_url}{url}" if isinstance(url, str) else None,
    }
    if dashboard.get("title") != "fourok dashboard":
        report["recommendations"].append("dashboard_title_stale")


def _record_datasources(report: dict[str, Any], get: HttpGet) -> None:
    try:
        datasources = get("/api/datasources", None)
    except Exception as exc:
        report["datasources_error"] = str(exc)
        report["recommendations"].append("datasource_inventory_failed")
        return

    by_uid = {item.get("uid"): item for item in datasources}
    for uid in ("prometheus", "loki", "tempo"):
        report["datasources"][uid] = "present" if uid in by_uid else "missing"
        if uid not in by_uid:
            report["recommendations"].append(f"{uid}_datasource_missing")


def _record_prometheus_signals(report: dict[str, Any], get: HttpGet) -> None:
    for name, query in PROMETHEUS_SIGNALS.items():
        path = "/api/datasources/proxy/uid/prometheus/api/v1/query"
        signal = _query_vector_signal(get, path, query)
        report["signals"][name] = signal
        if signal["status"] != "present":
            report["recommendations"].append("dashboard_has_gaps")


def _record_loki_signal(report: dict[str, Any], get: HttpGet) -> None:
    path = "/api/datasources/proxy/uid/loki/loki/api/v1/query_range"
    params = {
        "query": '{compose_project=~"fourok|governed-company-brain|openclaw"}',
        "limit": "5",
        "direction": "BACKWARD",
    }
    try:
        response = get(path, params)
        result = response.get("data", {}).get("result", [])
    except Exception as exc:
        report["signals"]["loki_recent_fourok_logs"] = {"status": "error", "error": str(exc)}
        report["recommendations"].append("dashboard_has_gaps")
        return

    report["signals"]["loki_recent_fourok_logs"] = {
        "status": "present" if result else "missing",
        "series": len(result),
    }
    if not result:
        report["recommendations"].append("dashboard_has_gaps")


def _query_vector_signal(get: HttpGet, path: str, query: str) -> dict[str, Any]:
    try:
        response = get(path, {"query": query})
        result = response.get("data", {}).get("result", [])
    except Exception as exc:
        return {"status": "error", "query": query, "error": str(exc)}
    return {"status": "present" if result else "missing", "query": query, "series": len(result)}


def _finalize_status(report: dict[str, Any]) -> None:
    recommendations = list(dict.fromkeys(report["recommendations"]))
    report["recommendations"] = recommendations
    if recommendations:
        report["status"] = "degraded"


def _format_text(report: dict[str, Any]) -> str:
    dashboard = report["dashboard"]
    lines = [
        f"status: {report['status']}",
        f"access: {report['access']['method']} {report['access']['base_url']}",
        f"dashboard: {dashboard.get('title')} {dashboard.get('url')}",
        "datasources: "
        + ", ".join(f"{name}={status}" for name, status in report["datasources"].items()),
        "signals:",
    ]
    for name, signal in report["signals"].items():
        lines.append(f"  {name}: {signal['status']} series={signal.get('series', 0)}")
    if report["recommendations"]:
        lines.append("recommendations: " + ", ".join(report["recommendations"]))
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
