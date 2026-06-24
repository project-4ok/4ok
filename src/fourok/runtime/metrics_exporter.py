from __future__ import annotations

import argparse
import json
import os
import sqlite3
import urllib.request
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from wsgiref.simple_server import make_server

from sqlalchemy import create_engine, inspect, text

from fourok.runtime.metric_helpers import source_latest_record_timestamp_metric as _source_metric
from fourok.runtime.retrieval_metrics import (
    embedding_coverage_metrics_connection,
    embedding_coverage_metrics_sqlite,
    retrieval_query_event_metrics_connection,
    retrieval_query_event_metrics_sqlite,
)

Metric = tuple[str, dict[str, str], float]

DAGSTER_JOB = "fourok_hourly_live_backfill"
FOUROK_DAGSTER_LOCATION = "fourok_pipeline"
FOUROK_DAGSTER_PIPELINE = "fourok_hourly_live_backfill"
FOUROK_DAGSTER_SCHEDULE = "fourok_hourly_live_backfill_schedule"
FOUROK_DAGSTER_SENSOR = "fourok_webhook_backlog_sensor"
UPDATED_OR_OCCURRED_EXPR = "coalesce(nullif(updated_at, ''), nullif(occurred_at, ''))"


def collect_runtime_metrics(
    *,
    dagster_url: str,
    state_path: Path | str,
    database_url: str | None = None,
    graphql: Callable[[str, str, dict[str, object] | None], dict[str, object]] | None = None,
) -> list[Metric]:
    graphql_call = graphql or _dagster_graphql
    metrics: list[Metric] = []
    metrics.extend(_dagster_metrics(dagster_url, graphql_call))
    if database_url:
        metrics.extend(_sql_metrics(database_url))
    else:
        metrics.extend(_state_metrics(Path(state_path)))
    return metrics


def render_prometheus_metrics(metrics: Sequence[Metric]) -> str:
    lines = [
        "# HELP fourok_runtime_exporter_up Whether the fourok runtime exporter rendered metrics."
    ]
    lines.append("# TYPE fourok_runtime_exporter_up gauge")
    lines.append("fourok_runtime_exporter_up 1")
    for name, labels, value in metrics:
        label_text = _labels(labels)
        lines.append(f"{name}{label_text} {_format_value(value)}")
    return "\n".join(lines) + "\n"


def metrics_response(
    *, dagster_url: str, state_path: Path | str, database_url: str | None = None
) -> str:
    return render_prometheus_metrics(
        collect_runtime_metrics(
            dagster_url=dagster_url, state_path=state_path, database_url=database_url
        )
    )


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m fourok.runtime.metrics_exporter")
    parser.add_argument("--host", default=os.environ.get("FOUROK_METRICS_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("FOUROK_METRICS_PORT", "9108"))
    )
    parser.add_argument(
        "--dagster-url",
        default=os.environ.get("FOUROK_DAGSTER_GRAPHQL_URL", "http://127.0.0.1:3001/graphql"),
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=Path(
            os.environ.get("FOUROK_STATE_PATH", "/app/.local/dagster/fourok-state.sqlite")
        ),
    )
    parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL", ""))
    args = parser.parse_args(argv)

    def app(environ, start_response):
        if environ.get("PATH_INFO") not in {"/", "/metrics"}:
            start_response("404 Not Found", [("Content-Type", "text/plain; charset=utf-8")])
            return [b"not found\n"]
        try:
            body = metrics_response(
                dagster_url=args.dagster_url,
                state_path=args.state,
                database_url=args.database_url or None,
            )
            status = "200 OK"
        except Exception as exc:  # pragma: no cover - defensive HTTP surface
            body = (
                "# HELP fourok_runtime_exporter_up Whether the fourok runtime exporter "
                "rendered metrics.\n"
                "# TYPE fourok_runtime_exporter_up gauge\n"
                "fourok_runtime_exporter_up 0\n"
                f'fourok_runtime_exporter_error{{error_class="{type(exc).__name__}"}} 1\n'
            )
            status = "500 Internal Server Error"
        start_response(status, [("Content-Type", "text/plain; version=0.0.4; charset=utf-8")])
        return [body.encode("utf-8")]

    with make_server(args.host, args.port, app) as server:
        server.serve_forever()


def _dagster_metrics(
    dagster_url: str,
    graphql: Callable[[str, str, dict[str, object] | None], dict[str, object]],
) -> list[Metric]:
    repo_data = graphql(dagster_url, _DAGSTER_REPOSITORY_QUERY, None)
    runs_data = graphql(
        dagster_url, _DAGSTER_RUNS_QUERY, {"pipelineName": DAGSTER_JOB, "limit": 10}
    )
    metrics: list[Metric] = []
    repo = _discover_fourok_repository(repo_data)
    if not repo:
        metrics.append(
            (
                "fourok_dagster_repository_discovery_status",
                {"status": "missing"},
                1.0,
            )
        )
    else:
        metrics.append(
            (
                "fourok_dagster_repository_discovery_status",
                {"status": "ok"},
                1.0,
            )
        )
    for schedule in repo.get("schedules", []) if isinstance(repo, dict) else []:
        name = str(schedule.get("name", ""))
        status = ((schedule.get("scheduleState") or {}).get("status") or "").upper()
        metrics.append(
            ("fourok_dagster_schedule_running", {"name": name}, 1 if status == "RUNNING" else 0)
        )
    for sensor in repo.get("sensors", []) if isinstance(repo, dict) else []:
        name = str(sensor.get("name", ""))
        status = ((sensor.get("sensorState") or {}).get("status") or "").upper()
        metrics.append(
            ("fourok_dagster_sensor_running", {"name": name}, 1 if status == "RUNNING" else 0)
        )

    runs = runs_data.get("data", {}).get("runsOrError", {}).get("results", [])
    seen_statuses: set[str] = set()
    last_success = 0.0
    step_failure_counts: dict[str, float] = {}
    for index, run in enumerate(runs):
        status = str(run.get("status", "UNKNOWN"))
        if index == 0:
            metrics.append(
                ("fourok_dagster_latest_run_status", {"job": DAGSTER_JOB, "status": status}, 1)
            )
        if status not in seen_statuses:
            metrics.append(("fourok_dagster_run_status", {"job": DAGSTER_JOB, "status": status}, 1))
            seen_statuses.add(status)
        if status == "SUCCESS":
            last_success = max(last_success, _float(run.get("endTime")))
        if index == 0 and _float(run.get("startTime")) and _float(run.get("endTime")):
            metrics.append(
                (
                    "fourok_dagster_run_duration_seconds",
                    {"job": DAGSTER_JOB, "status": status},
                    _float(run.get("endTime")) - _float(run.get("startTime")),
                )
            )
        for step in run.get("stepStats", []):
            step_key = str(step.get("stepKey", ""))
            step_status = str(step.get("status", "UNKNOWN"))
            start = _float(step.get("startTime"))
            end = _float(step.get("endTime"))
            if index == 0:
                metrics.append(
                    (
                        "fourok_dagster_latest_run_stage_status",
                        {"job": DAGSTER_JOB, "stage": step_key, "status": step_status},
                        1,
                    )
                )
            if index == 0 and start and end:
                duration = end - start
                metrics.append(
                    (
                        "fourok_dagster_step_duration_seconds",
                        {"job": DAGSTER_JOB, "step": step_key, "status": step_status},
                        duration,
                    )
                )
                if step_key == "fourok_retrieval_records":
                    metrics.append(
                        (
                            "fourok_embedding_index_duration_seconds",
                            {"job": DAGSTER_JOB, "status": step_status},
                            duration,
                        )
                    )
            if step_status == "FAILURE":
                step_failure_counts[step_key] = step_failure_counts.get(step_key, 0) + 1
    for step_key, count in sorted(step_failure_counts.items()):
        metrics.append(
            ("fourok_dagster_step_failures_total", {"job": DAGSTER_JOB, "step": step_key}, count)
        )
    metrics.append(
        ("fourok_dagster_last_success_timestamp_seconds", {"job": DAGSTER_JOB}, last_success)
    )
    return metrics


def _state_metrics(state_path: Path) -> list[Metric]:
    if not state_path.exists():
        return []
    metrics: list[Metric] = []
    with sqlite3.connect(state_path) as connection:
        connection.row_factory = sqlite3.Row
        if _has_table(connection, "source_records"):
            source_record_columns = _sqlite_columns(connection, "source_records")
            for row in connection.execute(
                "select source_system, record_type, count(*) as count "
                "from source_records where lifecycle_state = 'active' "
                "group by source_system, record_type"
            ):
                metrics.append(
                    (
                        "fourok_source_records_total",
                        {"source_system": row["source_system"], "record_type": row["record_type"]},
                        float(row["count"]),
                    )
                )
            latest_timestamp_expr = "nullif(updated_at, '')"
            if "occurred_at" in source_record_columns:
                latest_timestamp_expr = UPDATED_OR_OCCURRED_EXPR
            for row in connection.execute(
                "select source_system, max(" + latest_timestamp_expr + ") as latest_timestamp "
                "from source_records where lifecycle_state = 'active' "
                "and " + latest_timestamp_expr + " is not null "
                "group by source_system"
            ):
                metrics.append(
                    _source_metric(_timestamp(row["latest_timestamp"]), row["source_system"])
                )
            if "metadata_json" in source_record_columns:
                metrics.extend(_google_drive_file_metrics_sqlite(connection))
        if _has_table(connection, "raw_landed_records"):
            for row in connection.execute(
                "select source_system, stream, count(*) as count "
                "from raw_landed_records group by source_system, stream"
            ):
                metrics.append(
                    (
                        "fourok_raw_landed_records_total",
                        {"source_system": row["source_system"], "stream": row["stream"]},
                        float(row["count"]),
                    )
                )
        if _has_table(connection, "canonical_objects"):
            for row in connection.execute(
                "select object_type, count(*) as count from canonical_objects group by object_type"
            ):
                metrics.append(
                    (
                        "fourok_canonical_objects_total",
                        {"object_type": row["object_type"]},
                        float(row["count"]),
                    )
                )
        if _has_table(connection, "entity_links"):
            for row in connection.execute(
                "select relationship, count(*) as count from entity_links group by relationship"
            ):
                metrics.append(
                    (
                        "fourok_entity_links_total",
                        {"relationship": row["relationship"]},
                        float(row["count"]),
                    )
                )
        if _has_table(connection, "retrieval_records"):
            for row in connection.execute(
                "select status, count(*) as count from retrieval_records group by status"
            ):
                metrics.append(
                    (
                        "fourok_retrieval_records_total",
                        {"status": row["status"]},
                        float(row["count"]),
                    )
                )
            metrics.extend(embedding_coverage_metrics_sqlite(connection))
        if _has_table(connection, "retrieval_query_events"):
            metrics.extend(retrieval_query_event_metrics_sqlite(connection))
        if _has_table(connection, "webhook_events"):
            for row in connection.execute(
                "select source_system, status, count(*) as count "
                "from webhook_events group by source_system, status"
            ):
                metrics.append(
                    (
                        "fourok_webhook_events_total",
                        {"source_system": row["source_system"], "status": row["status"]},
                        float(row["count"]),
                    )
                )
        if _has_table(connection, "connector_job_runs"):
            for row in connection.execute(
                "select connector_name, status, count(*) as count "
                "from connector_job_runs group by connector_name, status"
            ):
                metrics.append(
                    (
                        "fourok_connector_job_runs_total",
                        {"connector": row["connector_name"], "status": row["status"]},
                        float(row["count"]),
                    )
                )
            metrics.extend(_connector_latest_metrics_sqlite(connection))
    return metrics


def _sql_metrics(database_url: str) -> list[Metric]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            table_names = set(inspect(connection).get_table_names())
            metrics: list[Metric] = []
            if "source_records" in table_names:
                source_record_columns = {
                    column["name"] for column in inspect(connection).get_columns("source_records")
                }
                for row in connection.execute(
                    text(
                        "select source_system, record_type, count(*) as count "
                        "from source_records where lifecycle_state = 'active' "
                        "group by source_system, record_type"
                    )
                ).mappings():
                    metrics.append(
                        (
                            "fourok_source_records_total",
                            {
                                "source_system": str(row["source_system"]),
                                "record_type": str(row["record_type"]),
                            },
                            float(row["count"]),
                        )
                    )
                    metrics.append(
                        (
                            "fourok_raw_landed_records_total",
                            {
                                "source_system": str(row["source_system"]),
                                "stream": str(row["record_type"]),
                            },
                            float(row["count"]),
                        )
                    )
                latest_timestamp_expr = "nullif(updated_at, '')"
                if "occurred_at" in source_record_columns:
                    latest_timestamp_expr = UPDATED_OR_OCCURRED_EXPR
                for row in connection.execute(
                    text(
                        "select source_system, max("
                        + latest_timestamp_expr
                        + ") as latest_timestamp "
                        "from source_records "
                        "where lifecycle_state = 'active' "
                        "and " + latest_timestamp_expr + " is not null "
                        "group by source_system"
                    )
                ).mappings():
                    metrics.append(
                        _source_metric(_timestamp(row["latest_timestamp"]), row["source_system"])
                    )
                if "metadata_json" in source_record_columns:
                    metrics.extend(_google_drive_file_metrics_connection(connection))
            if "raw_landed_records" in table_names:
                for row in connection.execute(
                    text(
                        "select source_system, stream, count(*) as count "
                        "from raw_landed_records group by source_system, stream"
                    )
                ).mappings():
                    metrics.append(
                        (
                            "fourok_raw_landed_records_total",
                            {
                                "source_system": str(row["source_system"]),
                                "stream": str(row["stream"]),
                            },
                            float(row["count"]),
                        )
                    )
            if "canonical_objects" in table_names:
                for row in connection.execute(
                    text(
                        "select object_type, count(*) as count "
                        "from canonical_objects group by object_type"
                    )
                ).mappings():
                    metrics.append(
                        (
                            "fourok_canonical_objects_total",
                            {"object_type": str(row["object_type"])},
                            float(row["count"]),
                        )
                    )
            if "entity_links" in table_names:
                entity_link_columns = {
                    column["name"] for column in inspect(connection).get_columns("entity_links")
                }
                relationship_column = (
                    "relationship" if "relationship" in entity_link_columns else "relationship_type"
                )
                for row in connection.execute(
                    text(
                        f"select {relationship_column} as relationship, count(*) as count "
                        "from entity_links group by relationship"
                    )
                ).mappings():
                    metrics.append(
                        (
                            "fourok_entity_links_total",
                            {"relationship": str(row["relationship"])},
                            float(row["count"]),
                        )
                    )
            if "retrieval_records" in table_names:
                for row in connection.execute(
                    text("select status, count(*) as count from retrieval_records group by status")
                ).mappings():
                    metrics.append(
                        (
                            "fourok_retrieval_records_total",
                            {"status": str(row["status"])},
                            float(row["count"]),
                        )
                    )
                metrics.extend(embedding_coverage_metrics_connection(connection, table_names))
            if "retrieval_query_events" in table_names:
                metrics.extend(retrieval_query_event_metrics_connection(connection))
            if "webhook_events" in table_names:
                for row in connection.execute(
                    text(
                        "select source_system, status, count(*) as count "
                        "from webhook_events group by source_system, status"
                    )
                ).mappings():
                    metrics.append(
                        (
                            "fourok_webhook_events_total",
                            {
                                "source_system": str(row["source_system"]),
                                "status": str(row["status"]),
                            },
                            float(row["count"]),
                        )
                    )
            if "connector_job_runs" in table_names:
                for row in connection.execute(
                    text(
                        "select connector_name, status, count(*) as count "
                        "from connector_job_runs group by connector_name, status"
                    )
                ).mappings():
                    metrics.append(
                        (
                            "fourok_connector_job_runs_total",
                            {
                                "connector": str(row["connector_name"]),
                                "status": str(row["status"]),
                            },
                            float(row["count"]),
                        )
                    )
                metrics.extend(_connector_latest_metrics_connection(connection))
            return metrics
    finally:
        engine.dispose()


def _has_table(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?", (table_name,)
    ).fetchone()
    return row is not None


def _sqlite_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"pragma table_info({table_name})")}


def _google_drive_file_metrics_sqlite(connection: sqlite3.Connection) -> list[Metric]:
    return _google_drive_file_metrics_from_rows(
        connection.execute(
            "select metadata_json from source_records "
            "where source_system = 'google_drive' "
            "and record_type = 'document' "
            "and lifecycle_state = 'active'"
        )
    )


def _google_drive_file_metrics_connection(connection) -> list[Metric]:
    rows = connection.execute(
        text(
            "select metadata_json from source_records "
            "where source_system = 'google_drive' "
            "and record_type = 'document' "
            "and lifecycle_state = 'active'"
        )
    ).mappings()
    return _google_drive_file_metrics_from_rows(rows)


def _connector_latest_metrics_sqlite(connection: sqlite3.Connection) -> list[Metric]:
    rows = connection.execute(
        """
        select connector_name, status, finished_at
        from connector_job_runs
        where connector_name != ''
        order by connector_name, finished_at desc, started_at desc, job_id desc
        """
    )
    return _connector_latest_metrics_from_rows(rows)


def _connector_latest_metrics_connection(connection) -> list[Metric]:
    rows = connection.execute(
        text(
            """
            select connector_name, status, finished_at
            from connector_job_runs
            where connector_name != ''
            order by connector_name, finished_at desc, started_at desc, job_id desc
            """
        )
    ).mappings()
    return _connector_latest_metrics_from_rows(rows)


def _connector_latest_metrics_from_rows(rows) -> list[Metric]:
    seen: set[str] = set()
    metrics: list[Metric] = []
    for row in rows:
        connector = str(row["connector_name"])
        if connector in seen:
            continue
        seen.add(connector)
        status = str(row["status"])
        metrics.append(
            ("fourok_connector_latest_run_status", {"connector": connector, "status": status}, 1)
        )
        metrics.append(
            (
                "fourok_connector_latest_finished_timestamp_seconds",
                {"connector": connector},
                _timestamp(str(row["finished_at"])),
            )
        )
    return metrics


def _google_drive_file_metrics_from_rows(rows) -> list[Metric]:
    counts: dict[tuple[str, str, str], int] = {}
    for row in rows:
        metadata = _metadata_object(row["metadata_json"])
        mime_type = _metadata_string(metadata, "mime_type")
        content_status = _metadata_string(metadata, "content_status")
        export_status = _metadata_string(metadata, "export_status")
        if not mime_type and not content_status and not export_status:
            continue
        key = (mime_type, content_status, export_status)
        counts[key] = counts.get(key, 0) + 1
    return [
        (
            "fourok_google_drive_files_total",
            {
                "mime_type": mime_type,
                "content_status": content_status,
                "export_status": export_status,
            },
            float(count),
        )
        for (mime_type, content_status, export_status), count in sorted(counts.items())
    ]


def _metadata_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _metadata_string(metadata: dict[str, object], key: str) -> str:
    value = metadata.get(key)
    return value if isinstance(value, str) else ""


def _first_repo(payload: dict[str, object]) -> dict[str, object]:
    return _discover_fourok_repository(payload.get("data", {}).get("repositoriesOrError", {}))


def _discover_fourok_repository(payload: dict[str, object]) -> dict[str, object]:
    repos = payload.get("data", {}).get("repositoriesOrError", {})
    nodes = repos.get("nodes", []) if isinstance(repos, dict) else []
    if not isinstance(nodes, list) or not nodes:
        return {}
    if len(nodes) == 1 and isinstance(nodes[0], dict):
        return nodes[0]

    def is_target(node: object) -> dict[str, object] | None:
        if not isinstance(node, dict):
            return None
        location = node.get("location")
        if isinstance(location, dict) and location.get("name") == FOUROK_DAGSTER_LOCATION:
            return node
        pipelines = [
            item.get("name") for item in node.get("pipelines", []) if isinstance(item, dict)
        ]
        if FOUROK_DAGSTER_PIPELINE in pipelines:
            return node
        schedules = [
            item.get("name") for item in node.get("schedules", []) if isinstance(item, dict)
        ]
        if FOUROK_DAGSTER_SCHEDULE in schedules:
            return node
        sensors = [item.get("name") for item in node.get("sensors", []) if isinstance(item, dict)]
        if FOUROK_DAGSTER_SENSOR in sensors:
            return node
        return None

    for node in nodes:
        result = is_target(node)
        if result is not None:
            return result

    for node in nodes:
        if isinstance(node, dict):
            return node
    return {}


def _dagster_graphql(
    url: str, query: str, variables: dict[str, object] | None = None
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _timestamp(value: str) -> float:
    if not value:
        return 0.0
    try:
        return float(value)
    except ValueError:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _labels(labels: dict[str, str]) -> str:
    if not labels:
        return ""
    return (
        "{"
        + ",".join(f'{key}="{_escape_label(value)}"' for key, value in sorted(labels.items()))
        + "}"
    )


def _escape_label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _format_value(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)


_DAGSTER_REPOSITORY_QUERY = """
query RepositoryStatus {
  repositoriesOrError {
    __typename
    ... on RepositoryConnection {
      nodes {
        name
        location { name }
        pipelines { name }
        schedules { name scheduleState { status } }
        sensors { name sensorState { status } }
      }
    }
    ... on PythonError { message stack }
  }
}
"""

_DAGSTER_RUNS_QUERY = """
query LatestRuns($pipelineName: String!, $limit: Int!) {
  runsOrError(filter: {pipelineName: $pipelineName}, limit: $limit) {
    __typename
    ... on Runs {
      results {
        runId
        status
        startTime
        endTime
        stepStats { stepKey status startTime endTime }
      }
    }
    ... on PythonError { message stack }
  }
}
"""


if __name__ == "__main__":
    main()
