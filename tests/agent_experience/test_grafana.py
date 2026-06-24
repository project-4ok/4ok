from __future__ import annotations

import json

from typing import Any

from fourok.agent_experience.grafana import grafana_report


def test_grafana_report_documents_agent_api_access_and_dashboard_state() -> None:
    calls: list[str] = []

    def fake_get(path: str, params: dict[str, str] | None = None) -> Any:
        calls.append(path)
        if path == "/api/health":
            return {"database": "ok", "version": "13.0.1"}
        if path == "/api/search":
            return [
                {
                    "uid": "fourok-local-runtime-logs",
                    "title": "4ok dashboard",
                    "url": "/d/fourok-local-runtime-logs/4ok-dashboard",
                }
            ]
        if path == "/api/datasources":
            return [
                {"uid": "prometheus", "type": "prometheus", "name": "Prometheus"},
                {"uid": "loki", "type": "loki", "name": "Loki"},
                {"uid": "tempo", "type": "tempo", "name": "Tempo"},
            ]
        if path.endswith("/api/v1/query"):
            metric = (params or {})["query"]
            result = [] if metric == "fourok_retrieval_requests_total" else [{"metric": {}, "value": [1, "3"]}]
            return {"status": "success", "data": {"result": result}}
        if path.endswith("/loki/api/v1/query_range"):
            return {"status": "success", "data": {"result": [{"stream": {}, "values": [["1", "log"]]}]}}
        raise AssertionError(path)

    report = grafana_report(grafana_url="http://grafana.local", http_get=fake_get)

    assert report["status"] == "degraded"
    assert report["access"] == {
        "method": "grafana_http_api",
        "base_url": "http://grafana.local",
        "dashboard_uid": "fourok-local-runtime-logs",
    }
    assert report["dashboard"] == {
        "title": "4ok dashboard",
        "uid": "fourok-local-runtime-logs",
        "url": "http://grafana.local/d/fourok-local-runtime-logs/4ok-dashboard",
    }
    assert report["datasources"] == {
        "prometheus": "present",
        "loki": "present",
        "tempo": "present",
    }
    assert report["signals"]["fourok_source_records_total"]["status"] == "present"
    assert report["signals"]["fourok_retrieval_requests_total"]["status"] == "missing"
    assert report["signals"]["loki_recent_4ok_logs"]["status"] == "present"
    assert "dashboard_has_gaps" in report["recommendations"]
    assert "/api/health" in calls


def test_grafana_report_json_output_is_serializable() -> None:
    report = grafana_report(
        grafana_url="http://grafana.local",
        http_get=lambda path, params=None: {
            "/api/health": {"database": "ok"},
            "/api/search": [],
            "/api/datasources": [],
        }[path],
    )

    encoded = json.dumps(report, sort_keys=True)

    assert "grafana_http_api" in encoded
    assert report["status"] == "degraded"
