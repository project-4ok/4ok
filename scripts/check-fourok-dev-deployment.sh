#!/usr/bin/env bash
set -euo pipefail

CHECK_TARGET="${CHECK_TARGET:-ssh}"
GATEWAY_SSH_TARGET="${GATEWAY_SSH_TARGET:-root@178.105.10.7}"
QUERY="${FOUROK_STATUS_QUERY:-${FOUROK_DEV_STATUS_QUERY:-fourok}}"
INCLUDE_GH="${INCLUDE_GH:-true}"
GH_REPO="${GH_REPO:-project-fourok/fourok-infrastructure-prod}"
OPENCLAW_IMAGE_WORKFLOW="${OPENCLAW_IMAGE_WORKFLOW:-fourok-openclaw-dev-image.yml}"
OPENCLAW_IMAGE_WORKFLOW_REQUIRED="${OPENCLAW_IMAGE_WORKFLOW_REQUIRED:-false}"
RUNTIME_DEPLOY_WORKFLOW="${RUNTIME_DEPLOY_WORKFLOW:-dev-customer-gateway-fourok-runtime-deploy}"
GATEWAY_CONTAINER="${GATEWAY_CONTAINER:-openclaw-openclaw-gateway-1}"
FOUROK_RETRIEVE_CONTAINER="${FOUROK_RETRIEVE_CONTAINER:-openclaw-fourok-app-1}"
FOUROK_RETRIEVE_COMMAND="${FOUROK_RETRIEVE_COMMAND:-/app/.venv/bin/fourok}"
FOUROK_CRITICAL_CONTAINERS="${FOUROK_CRITICAL_CONTAINERS:-openclaw-openclaw-gateway-1,openclaw-fourok-app-1,openclaw-fourok-postgres-1,openclaw-fourok-dagster-code-1,openclaw-fourok-dagster-postgres-1,openclaw-fourok-observability-1}"
CONTAINER_FILTER_REGEX="${CONTAINER_FILTER_REGEX:-openclaw-fourok|openclaw-openclaw-gateway}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:13000}"
DAGSTER_SERVER_INFO_URL="${DAGSTER_SERVER_INFO_URL:-http://127.0.0.1:13001/server_info}"
FOUROK_DASHBOARD_UID="${FOUROK_DASHBOARD_UID:-fourok-local-runtime-logs}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--json]

Run a one-command status check for a fourok/OpenClaw deployment surface.

Target modes:
  CHECK_TARGET=ssh    run Docker/curl checks on GATEWAY_SSH_TARGET over SSH (default)
  CHECK_TARGET=local  run Docker/curl checks on the local machine

Environment overrides:
  CHECK_TARGET=ssh|local
  GATEWAY_SSH_TARGET=root@178.105.10.7
  GH_REPO=project-fourok/fourok-infrastructure-prod
  INCLUDE_GH=true
  OPENCLAW_IMAGE_WORKFLOW_REQUIRED=false
  FOUROK_STATUS_QUERY=fourok
  GATEWAY_CONTAINER=openclaw-openclaw-gateway-1
  FOUROK_RETRIEVE_CONTAINER=openclaw-fourok-app-1
  FOUROK_RETRIEVE_COMMAND=/app/.venv/bin/fourok
  FOUROK_CRITICAL_CONTAINERS=comma,separated,container,names
  CONTAINER_FILTER_REGEX='openclaw-fourok|openclaw-openclaw-gateway'
  GRAFANA_URL=http://127.0.0.1:13000
  DAGSTER_SERVER_INFO_URL=http://127.0.0.1:13001/server_info
  FOUROK_DASHBOARD_UID=fourok-local-runtime-logs

The command prints JSON and exits non-zero unless the deployment status is ok.
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
  "$CHECK_TARGET" \
  "$GATEWAY_SSH_TARGET" \
  "$QUERY" \
  "$INCLUDE_GH" \
  "$GH_REPO" \
  "$OPENCLAW_IMAGE_WORKFLOW" \
  "$OPENCLAW_IMAGE_WORKFLOW_REQUIRED" \
  "$RUNTIME_DEPLOY_WORKFLOW" \
  "$GATEWAY_CONTAINER" \
  "$FOUROK_RETRIEVE_CONTAINER" \
  "$FOUROK_RETRIEVE_COMMAND" \
  "$FOUROK_CRITICAL_CONTAINERS" \
  "$CONTAINER_FILTER_REGEX" \
  "$GRAFANA_URL" \
  "$DAGSTER_SERVER_INFO_URL" \
  "$FOUROK_DASHBOARD_UID" <<'PY'
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from typing import Any

(
    check_target,
    ssh_target,
    query,
    include_gh,
    gh_repo,
    image_workflow,
    image_workflow_required,
    runtime_workflow,
    gateway_container,
    retrieve_container,
    retrieve_command,
    critical_csv,
    container_filter_regex,
    grafana_url,
    dagster_server_info_url,
    dashboard_uid,
) = sys.argv[1:]
critical_health = {item.strip() for item in critical_csv.split(",") if item.strip()}


def run(cmd: list[str], *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def target_shell(command: str, *, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    if check_target == "local":
        return run(["bash", "-lc", command], timeout=timeout)
    if check_target == "ssh":
        return run([
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            ssh_target,
            command,
        ], timeout=timeout)
    return subprocess.CompletedProcess(["invalid-target"], 2, "", f"unsupported CHECK_TARGET: {check_target}")


def parse_gh(workflow: str, *, required: bool = True) -> dict[str, Any]:
    if include_gh.lower() != "true":
        return {"status": "skipped", "required": required}
    if shutil.which("gh") is None:
        return {"status": "skipped", "reason": "gh_not_found", "required": required}
    proc = run([
        "gh",
        "run",
        "list",
        "--repo",
        gh_repo,
        "--workflow",
        workflow,
        "--limit",
        "10",
        "--json",
        "databaseId,status,conclusion,headSha,url,displayTitle,createdAt",
    ])
    if proc.returncode != 0:
        failed = {"check_status": "failed", "stderr": proc.stderr.strip(), "required": required}
        return failed if required else {**failed, "check_status": "skipped", "optional_check_status": "failed"}
    try:
        runs = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        failed = {"check_status": "failed", "error": type(exc).__name__, "required": required}
        return failed if required else {**failed, "check_status": "skipped", "optional_check_status": "failed"}
    if not runs:
        failed = {"check_status": "failed", "reason": "no_runs", "required": required}
        return failed if required else {**failed, "check_status": "skipped", "optional_check_status": "failed"}
    newest = runs[0]
    completed = [run for run in runs if run.get("status") == "completed"]
    if not completed:
        failed = {
            **newest,
            "check_status": "failed",
            "required": required,
            "reason": "no_completed_runs",
            "newest_run_status": newest.get("status"),
        }
        return failed if required else {**failed, "check_status": "skipped", "optional_check_status": "failed"}
    newest_completed_run = completed[0]
    check_status = "ok" if newest_completed_run.get("conclusion") == "success" else "failed"
    result = {
        **newest_completed_run,
        "check_status": check_status,
        "required": required,
        "newest_run_status": newest.get("status"),
        "newest_run_databaseId": newest.get("databaseId"),
        "newest_completed_run": {
            key: newest_completed_run.get(key)
            for key in ("databaseId", "status", "conclusion", "headSha", "url", "displayTitle", "createdAt")
        },
    }
    return result if required or check_status == "ok" else {**result, "check_status": "skipped", "optional_check_status": check_status}


docker_cmd = (
    "docker ps --format '{{.Names}}\\t{{.Status}}' "
    f"| grep -E {shlex.quote(container_filter_regex)} | sort"
)
containers_proc = target_shell(docker_cmd)
containers: dict[str, str] = {}
if containers_proc.returncode == 0:
    for line in containers_proc.stdout.splitlines():
        if "\t" in line:
            name, status = line.split("\t", 1)
            containers[name] = status

missing = sorted(critical_health - set(containers))
unhealthy = sorted(
    name for name in critical_health if name in containers and "(healthy)" not in containers[name]
)
containers_status = "ok" if not missing and not unhealthy else "failed"

retrieve_cmd = f"docker exec {shlex.quote(retrieve_container)} sh -lc " + shlex.quote(
    f"{retrieve_command} retrieve --format json {shlex.quote(query)}"
)
retrieve_proc = target_shell(retrieve_cmd, timeout=90)
try:
    retrieve_json = json.loads(retrieve_proc.stdout) if retrieve_proc.returncode == 0 else {}
except json.JSONDecodeError:
    retrieve_json = {}
retrieve = {
    "status": "ok" if retrieve_json.get("status") == "ok" else "failed",
    "result_count": len(retrieve_json.get("results", [])) if isinstance(retrieve_json.get("results"), list) else None,
    "query": query,
}
if retrieve_proc.returncode != 0:
    retrieve["stderr"] = retrieve_proc.stderr.strip()


grafana_search_url = grafana_url.rstrip("/") + "/api/search?query=fourok"
grafana_proc = target_shell(f"curl -fsS {shlex.quote(grafana_search_url)}")
try:
    dashboards = json.loads(grafana_proc.stdout) if grafana_proc.returncode == 0 else []
except json.JSONDecodeError:
    dashboards = []
grafana_uids = [item.get("uid") for item in dashboards if isinstance(item, dict)]
grafana = {
    "status": "ok" if dashboard_uid in grafana_uids else "failed",
    "dashboard_uid": dashboard_uid,
    "dashboard_uids": grafana_uids,
    "url": grafana_url,
}


dagster_proc = target_shell(f"curl -fsS {shlex.quote(dagster_server_info_url)}")
try:
    dagster_json = json.loads(dagster_proc.stdout) if dagster_proc.returncode == 0 else {}
except json.JSONDecodeError:
    dagster_json = {}
dagster = {
    "status": "ok" if dagster_json.get("dagster_version") else "failed",
    "dagster_version": dagster_json.get("dagster_version"),
    "server_info_url": dagster_server_info_url,
}

checks = {
    "github_openclaw_image_workflow": parse_gh(
        image_workflow,
        required=image_workflow_required.strip().lower() in {"1", "true", "yes", "on"},
    ),
    "github_runtime_deploy_workflow": parse_gh(runtime_workflow),
    "containers": {
        "status": containers_status,
        "critical_missing": missing,
        "critical_unhealthy": unhealthy,
        "observed": containers,
    },
    "fourok_retrieve": retrieve,
    "grafana": grafana,
    "dagster": dagster,
}
status = "ok" if all(
    check.get("check_status", check.get("status")) in {"ok", "skipped"}
    for check in checks.values()
) else "failed"
report = {
    "status": status,
    "target": {"mode": check_target, "ssh_target": ssh_target if check_target == "ssh" else None},
    "checks": checks,
}
print(json.dumps(report, indent=2, sort_keys=True))
sys.exit(0 if status == "ok" else 1)
PY
