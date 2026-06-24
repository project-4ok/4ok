from __future__ import annotations

import json
import time
import urllib.request
from collections.abc import Callable
from typing import Any, cast

GraphqlCall = Callable[[str, str, dict[str, object] | None], dict[str, object]]


def dagster_status_report(
    *,
    dagster_url: str = "http://127.0.0.1:3001/graphql",
    graphql: GraphqlCall | None = None,
) -> dict[str, object]:
    graphql_call = graphql or _dagster_graphql
    repo_data = graphql_call(dagster_url, _DAGSTER_REPOSITORY_QUERY, None)
    repo_payload = cast(dict[str, Any], repo_data.get("data", {}))
    repositories = cast(dict[str, Any], repo_payload.get("repositoriesOrError", {}))
    if repositories.get("__typename") != "RepositoryConnection":
        return {"status": "error", "repository_status": "error", "raw": repositories}
    repository_nodes = repositories.get("nodes", [])
    repo = _discover_fourok_repository(repository_nodes if isinstance(repository_nodes, list) else [])
    runs_data = graphql_call(
        dagster_url,
        _DAGSTER_RUNS_QUERY,
        {"pipelineName": "fourok_hourly_live_backfill", "limit": 5},
    )
    runs_payload = cast(dict[str, Any], runs_data.get("data", {}))
    runs_or_error = cast(dict[str, Any], runs_payload.get("runsOrError", {}))
    runs = runs_or_error.get("results", [])
    return {
        "status": "ok",
        "repository_status": "ok" if repo else "missing",
        "runtime_status": _dagster_runtime_status(runs),
        "repository": repo.get("name"),
        "location": (repo.get("location") or {}).get("name"),
        "jobs": sorted(item.get("name") for item in repo.get("pipelines", []) if item.get("name")),
        "schedules": {
            item.get("name"): (item.get("scheduleState") or {}).get("status")
            for item in repo.get("schedules", [])
            if item.get("name")
        },
        "sensors": {
            item.get("name"): (item.get("sensorState") or {}).get("status")
            for item in repo.get("sensors", [])
            if item.get("name")
        },
        "latest_runs": [_run_summary(run) for run in runs],
    }


def _run_summary(run: object) -> dict[str, object]:
    if not isinstance(run, dict):
        return {}
    return {
        "run_id": run.get("runId"),
        "status": run.get("status"),
        "start_time": run.get("startTime"),
        "end_time": run.get("endTime"),
        "step_statuses": {
            step.get("stepKey"): step.get("status")
            for step in run.get("stepStats", [])
            if isinstance(step, dict) and step.get("stepKey")
        },
    }


def _dagster_runtime_status(
    runs: object, *, max_success_age_minutes: float = 65.0
) -> dict[str, object]:
    if not isinstance(runs, list) or not runs:
        return {
            "status": "failed",
            "reason": "no_runs",
            "latest_run_status": None,
            "minutes_since_success": None,
        }
    latest = runs[0] if isinstance(runs[0], dict) else {}
    latest_status = latest.get("status")
    failures = _failed_or_incomplete_steps(latest)
    success_runs = [run for run in runs if isinstance(run, dict) and run.get("status") == "SUCCESS"]
    latest_success = success_runs[0] if success_runs else None
    minutes_since_success = _minutes_since_run_end(latest_success)
    freshness_ok = (
        minutes_since_success is not None and minutes_since_success <= max_success_age_minutes
    )
    status = "ok" if latest_status == "SUCCESS" and not failures and freshness_ok else "failed"
    reason = "ok"
    if latest_status != "SUCCESS":
        reason = "latest_run_not_success"
    elif failures:
        reason = "latest_run_has_failed_or_incomplete_steps"
    elif not freshness_ok:
        reason = "hourly_success_stale"
    return {
        "status": status,
        "reason": reason,
        "latest_run_id": latest.get("runId"),
        "latest_run_status": latest_status,
        "latest_success_run_id": latest_success.get("runId") if latest_success else None,
        "minutes_since_success": minutes_since_success,
        "max_success_age_minutes": max_success_age_minutes,
        "failed_or_incomplete_steps": failures,
    }


def _failed_or_incomplete_steps(run: object) -> dict[str, object]:
    if not isinstance(run, dict):
        return {}
    failures: dict[str, object] = {}
    for step in run.get("stepStats", []):
        if not isinstance(step, dict):
            continue
        key = step.get("stepKey")
        status = step.get("status")
        if key and status != "SUCCESS":
            failures[str(key)] = status
    return failures


def _minutes_since_run_end(run: object) -> float | None:
    if not isinstance(run, dict):
        return None
    end_time = run.get("endTime") or run.get("startTime")
    if not isinstance(end_time, int | float):
        return None
    return max(0.0, (time.time() - float(end_time)) / 60.0)


def _discover_fourok_repository(nodes: list[object]) -> dict[str, object]:
    if not nodes:
        return {}
    if len(nodes) == 1 and isinstance(nodes[0], dict):
        return nodes[0]

    def match(node: object) -> dict[str, object] | None:
        if not isinstance(node, dict):
            return None
        location = node.get("location")
        if isinstance(location, dict) and location.get("name") == "fourok_pipeline":
            return node
        pipelines = [
            item.get("name") for item in node.get("pipelines", []) if isinstance(item, dict)
        ]
        if "fourok_hourly_live_backfill" in pipelines:
            return node
        return None

    for node in nodes:
        matched = match(node)
        if matched is not None:
            return matched

    for node in nodes:
        if isinstance(node, dict):
            return node

    return {}


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
        stepStats { stepKey status startTime endTime }
        startTime
        endTime
      }
    }
    ... on PythonError { message stack }
  }
}
"""


def _dagster_graphql(
    url: str, query: str, variables: dict[str, object] | None = None
) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))
