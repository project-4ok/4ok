from __future__ import annotations

import json
from pathlib import Path


def test_fourok_dashboard_starts_with_agent_runtime_coverage_row() -> None:
    dashboard = json.loads(Path("deploy/observability/fourok-local-runtime-logs.json").read_text())
    panels = dashboard["panels"]
    by_title = {panel["title"]: panel for panel in panels}

    assert dashboard["title"] == "fourok dashboard"
    assert by_title["[Agent] Runtime observability coverage"]["gridPos"]["y"] == 0

    expected_top_stat_panels = {
        "[Agent] Prometheus 4OK metrics present": "fourok_source_records_total or fourok_dagster_schedule_running or fourok_retrieval_records_total",
        "[Agent] Recent Loki fourok log streams": 'count(count_over_time({compose_project=~"$compose_project"}[15m]))',
        "[Agent] Retrieval request telemetry present": "fourok_retrieval_requests_total or fourok_search_requests_total or fourok_retrieval_prepare_total",
        "[Agent] Embedding coverage telemetry present": "fourok_embedding_coverage_ratio or fourok_embedding_records_total",
    }
    for title, expr in expected_top_stat_panels.items():
        panel = by_title[title]
        assert panel["gridPos"]["y"] == 3
        assert panel["type"] == "stat"
        assert panel["targets"][0]["expr"] == expr

    assert by_title["[Pipeline] Dagster lineage health map"]["gridPos"]["y"] > 3
