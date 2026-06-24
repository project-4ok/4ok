#!/usr/bin/env bash
set -euo pipefail

CHECK_TARGET="${CHECK_TARGET:-ssh}"
GATEWAY_SSH_TARGET="${GATEWAY_SSH_TARGET:-root@178.105.10.7}"
DAGSTER_GRAPHQL_URL="${DAGSTER_GRAPHQL_URL:-http://127.0.0.1:13001/graphql}"
DAGSTER_REPOSITORY_LOCATION="${DAGSTER_REPOSITORY_LOCATION:-gcb_pipeline}"
DAGSTER_REPOSITORY_NAME="${DAGSTER_REPOSITORY_NAME:-__repository__}"
DAGSTER_JOB_NAME="${DAGSTER_JOB_NAME:-gcb_hourly_live_backfill}"
DAGSTER_POLL_TIMEOUT_SECONDS="${DAGSTER_POLL_TIMEOUT_SECONDS:-600}"
DAGSTER_POLL_INTERVAL_SECONDS="${DAGSTER_POLL_INTERVAL_SECONDS:-10}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--json]

Launch and poll gcb_hourly_live_backfill through the deployed Dagster webserver GraphQL API.
This proves the same operator-visible Dagster instance used by stage1 acceptance.

Environment overrides:
  CHECK_TARGET=ssh|local
  GATEWAY_SSH_TARGET=root@178.105.10.7
  DAGSTER_GRAPHQL_URL=http://127.0.0.1:13001/graphql
  DAGSTER_REPOSITORY_LOCATION=gcb_pipeline
  DAGSTER_REPOSITORY_NAME=__repository__
  DAGSTER_JOB_NAME=gcb_hourly_live_backfill
  DAGSTER_POLL_TIMEOUT_SECONDS=600
  DAGSTER_POLL_INTERVAL_SECONDS=10
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

python3 - \
  "${CHECK_TARGET}" \
  "${GATEWAY_SSH_TARGET}" \
  "${DAGSTER_GRAPHQL_URL}" \
  "${DAGSTER_REPOSITORY_LOCATION}" \
  "${DAGSTER_REPOSITORY_NAME}" \
  "${DAGSTER_JOB_NAME}" \
  "${DAGSTER_POLL_TIMEOUT_SECONDS}" \
  "${DAGSTER_POLL_INTERVAL_SECONDS}" <<'PY'
from __future__ import annotations

import json
import shlex
import subprocess
import sys
import textwrap

(
    check_target,
    ssh_target,
    dagster_url,
    repository_location,
    repository_name,
    job_name,
    timeout_seconds,
    interval_seconds,
) = sys.argv[1:]


def target_python_command(python_source: str, python_args: list[str]) -> list[str]:
    local_command = ["python3", "-c", python_source, *python_args]
    if check_target == "local":
        return local_command
    if check_target == "ssh":
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            ssh_target,
            shlex.join(local_command),
        ]
    return ["python3", "-c", f"raise SystemExit('unsupported CHECK_TARGET: {check_target}')"]


remote_source = r'''
from __future__ import annotations

import json
import sys
import time
import urllib.request

(
    dagster_url,
    repository_location,
    repository_name,
    job_name,
    timeout_seconds,
    interval_seconds,
) = sys.argv[1:]
timeout_seconds = int(timeout_seconds)
interval_seconds = int(interval_seconds)


def graphql(query: str, variables: dict[str, object] | None = None) -> dict[str, object]:
    body = json.dumps({"query": query, "variables": variables or {}}).encode()
    request = urllib.request.Request(
        dagster_url,
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())

launch_query = """
mutation Launch($params: ExecutionParams!) {
  launchRun(executionParams: $params) {
    __typename
    ... on LaunchRunSuccess { run { runId status } }
    ... on PythonError { message stack }
    ... on RunConfigValidationInvalid { errors { message } }
    ... on PipelineNotFoundError { message }
    ... on UnauthorizedError { message }
  }
}
"""
run_query = """
query Run($runId: ID!) {
  runOrError(runId: $runId) {
    __typename
    ... on Run { runId status startTime endTime stepStats { stepKey status } }
    ... on RunNotFoundError { message }
  }
}
"""
params = {
    "selector": {
        "repositoryLocationName": repository_location,
        "repositoryName": repository_name,
        "jobName": job_name,
    },
    "runConfigData": {},
    "mode": "default",
    "executionMetadata": {
        "tags": [
            {"key": "launched_by", "value": "hermes-post-deploy-verify"},
        ]
    },
}
launch = graphql(launch_query, {"params": params})
launch_result = launch.get("data", {}).get("launchRun", {})
if launch_result.get("__typename") != "LaunchRunSuccess":
    print(json.dumps({"status": "failed", "launch": launch_result}, indent=2, sort_keys=True))
    raise SystemExit(1)

run_id = launch_result["run"]["runId"]
deadline = time.monotonic() + timeout_seconds
last_run = {}
while time.monotonic() < deadline:
    run_response = graphql(run_query, {"runId": run_id})
    last_run = run_response.get("data", {}).get("runOrError", {})
    status = last_run.get("status")
    if status in {"SUCCESS", "FAILURE", "CANCELED"}:
        report = {
            "status": "ok" if status == "SUCCESS" else "failed",
            "dagster_url": dagster_url,
            "job_name": job_name,
            "run_id": run_id,
            "run_status": status,
            "run": last_run,
        }
        print(json.dumps(report, indent=2, sort_keys=True))
        raise SystemExit(0 if status == "SUCCESS" else 1)
    time.sleep(interval_seconds)

print(json.dumps({"status": "failed", "error": "timeout", "run_id": run_id, "run": last_run}, indent=2, sort_keys=True))
raise SystemExit(1)
'''

python_args = [
    dagster_url,
    repository_location,
    repository_name,
    job_name,
    timeout_seconds,
    interval_seconds,
]
command = target_python_command(remote_source, python_args)
proc = subprocess.run(command, text=True, capture_output=True)
print(proc.stdout, end="")
if proc.stderr:
    print(proc.stderr, file=sys.stderr, end="")
sys.exit(proc.returncode)
PY
