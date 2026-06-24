#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CHECK_TARGET="${CHECK_TARGET:-ssh}"
GATEWAY_SSH_TARGET="${GATEWAY_SSH_TARGET:-root@178.105.10.7}"
STAGE1_RUNNER="${STAGE1_RUNNER:-auto}"
FOUR_OK_STAGE1_CONTAINER="${FOUR_OK_STAGE1_CONTAINER:-openclaw-fourok-app-1}"
FOUR_OK_STAGE1_COMMAND="${FOUR_OK_STAGE1_COMMAND:-/app/.venv/bin/fourok}"
LOCAL_STAGE1_COMMAND="${LOCAL_STAGE1_COMMAND:-uv run fourok}"
DAGSTER_GRAPHQL_URL="${DAGSTER_GRAPHQL_URL:-http://fourok-dagster-webserver:3001/graphql}"
GRAFANA_URL="${GRAFANA_URL:-http://fourok-observability:3000}"
STAGE1_CASES="${STAGE1_CASES:-}"
REFRESH_DAGSTER_BACKFILL="${REFRESH_DAGSTER_BACKFILL:-true}"
DAGSTER_BACKFILL_CHECK="${DAGSTER_BACKFILL_CHECK:-${REPO_ROOT}/scripts/run-4ok-dev-dagster-backfill.sh}"
DEPLOYMENT_CHECK="${DEPLOYMENT_CHECK:-${REPO_ROOT}/scripts/check-4ok-dev-deployment.sh}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--json]

Run two 4OK/OpenClaw gates and combine their JSON results:
  1. deployment surface check via scripts/check-4ok-dev-deployment.sh --json
  2. fourok stage1-acceptance --json on the selected target

The top-level status is ok only when both gates return status=ok.
The command exits non-zero otherwise.

Target modes:
  CHECK_TARGET=ssh    run target checks on GATEWAY_SSH_TARGET over SSH (default)
  CHECK_TARGET=local  run target checks on this machine

Stage 1 runners:
  STAGE1_RUNNER=auto    ssh -> docker, local -> host (default)
  STAGE1_RUNNER=docker  run stage1 inside FOUR_OK_STAGE1_CONTAINER on the target
  STAGE1_RUNNER=host    run stage1 with LOCAL_STAGE1_COMMAND on the target shell

Environment overrides:
  CHECK_TARGET=ssh|local
  GATEWAY_SSH_TARGET=root@178.105.10.7
  STAGE1_RUNNER=auto|docker|host
  FOUR_OK_STAGE1_CONTAINER=openclaw-fourok-app-1
  FOUR_OK_STAGE1_COMMAND=/app/.venv/bin/fourok
  LOCAL_STAGE1_COMMAND='uv run fourok'
  DAGSTER_GRAPHQL_URL=http://fourok-dagster-webserver:3001/graphql
  GRAFANA_URL=http://fourok-observability:3000
  STAGE1_CASES=/app/.local/stage1/live_retrieval_case_set.generated.json
  REFRESH_DAGSTER_BACKFILL=true
  DAGSTER_BACKFILL_CHECK=scripts/run-4ok-dev-dagster-backfill.sh
  DEPLOYMENT_CHECK=scripts/check-4ok-dev-deployment.sh
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
  "${STAGE1_RUNNER}" \
  "${FOUR_OK_STAGE1_CONTAINER}" \
  "${FOUR_OK_STAGE1_COMMAND}" \
  "${LOCAL_STAGE1_COMMAND}" \
  "${DAGSTER_GRAPHQL_URL}" \
  "${GRAFANA_URL}" \
  "${STAGE1_CASES}" \
  "${REFRESH_DAGSTER_BACKFILL}" \
  "${DAGSTER_BACKFILL_CHECK}" \
  "${DEPLOYMENT_CHECK}" <<'PY'
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from typing import Any

(
    check_target,
    ssh_target,
    stage1_runner,
    stage1_container,
    stage1_command,
    local_stage1_command,
    dagster_url,
    grafana_url,
    stage1_cases,
    refresh_dagster_backfill,
    dagster_backfill_check,
    deployment_check,
) = sys.argv[1:]


def parse_json_output(output: str) -> dict[str, Any] | None:
    stripped = output.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                return None
    return None


def run_gate(command: list[str], *, timeout: int, env: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        proc = subprocess.run(command, text=True, capture_output=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "failed",
            "exit_code": None,
            "error": "timeout",
            "stdout": exc.stdout or "",
            "stderr": exc.stderr or "",
        }
    parsed = parse_json_output(proc.stdout)
    if parsed is None:
        return {
            "status": "failed",
            "exit_code": proc.returncode,
            "error": "invalid_json_output",
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
    gate_status = "ok" if proc.returncode == 0 and parsed.get("status") == "ok" else "failed"
    return {
        "status": gate_status,
        "exit_code": proc.returncode,
        "report": parsed,
        "stderr": proc.stderr.strip(),
    }


def target_shell_command(shell_command: str) -> list[str]:
    if check_target == "local":
        return ["bash", "-lc", shell_command]
    if check_target == "ssh":
        return [
            "ssh",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            ssh_target,
            shell_command,
        ]
    return ["bash", "-lc", f"echo unsupported CHECK_TARGET: {shlex.quote(check_target)} >&2; exit 2"]


deployment_env = os.environ.copy()
deployment_env.update({"CHECK_TARGET": check_target, "GATEWAY_SSH_TARGET": ssh_target})
deployment = run_gate([deployment_check, "--json"], timeout=180, env=deployment_env)

dagster_backfill = {"status": "skipped", "reason": "REFRESH_DAGSTER_BACKFILL=false"}
if refresh_dagster_backfill.strip().lower() in {"1", "true", "yes", "on"}:
    backfill_env = os.environ.copy()
    backfill_env.update(
        {
            "CHECK_TARGET": check_target,
            "GATEWAY_SSH_TARGET": ssh_target,
            "DAGSTER_GRAPHQL_URL": "http://127.0.0.1:13001/graphql"
            if check_target == "ssh"
            else dagster_url,
        }
    )
    dagster_backfill = run_gate([dagster_backfill_check, "--json"], timeout=720, env=backfill_env)

resolved_runner = stage1_runner
if resolved_runner == "auto":
    resolved_runner = "host" if check_target == "local" else "docker"

stage1_args = f"stage1-acceptance --json --dagster-url {shlex.quote(dagster_url)} --grafana-url {shlex.quote(grafana_url)}"
if stage1_cases:
    stage1_args += f" --cases {shlex.quote(stage1_cases)}"
if resolved_runner == "docker":
    inner = f"{stage1_command} {stage1_args}"
    stage1_shell = f"docker exec {shlex.quote(stage1_container)} sh -lc {shlex.quote(inner)}"
elif resolved_runner == "host":
    stage1_shell = f"{local_stage1_command} {stage1_args}"
else:
    stage1_shell = f"echo unsupported STAGE1_RUNNER: {shlex.quote(stage1_runner)} >&2; exit 2"

stage1 = run_gate(target_shell_command(stage1_shell), timeout=360)

checks = {
    "deployment": deployment,
    "dagster_backfill": dagster_backfill,
    "stage1_acceptance": stage1,
}
status = "ok" if all(check.get("status") == "ok" for check in checks.values()) else "failed"
summary = {
    name: {
        "status": check.get("status"),
        "exit_code": check.get("exit_code"),
        "inner_status": (check.get("report") or {}).get("status") if isinstance(check.get("report"), dict) else None,
    }
    for name, check in checks.items()
}
report = {
    "status": status,
    "target": {"mode": check_target, "ssh_target": ssh_target if check_target == "ssh" else None},
    "stage1_runner": resolved_runner,
    "stage1_container": stage1_container if resolved_runner == "docker" else None,
    "stage1_cases": stage1_cases or None,
    "summary": summary,
    "checks": checks,
}
print(json.dumps(report, indent=2, sort_keys=True))
sys.exit(0 if status == "ok" else 1)
PY
