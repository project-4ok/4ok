#!/usr/bin/env bash
set -euo pipefail

CHECK_TARGET="${CHECK_TARGET:-ssh}"
GATEWAY_SSH_TARGET="${GATEWAY_SSH_TARGET:-root@178.105.10.7}"
DAGSTER_WEBSERVER_CONTAINER="${DAGSTER_WEBSERVER_CONTAINER:-openclaw-fourok-dagster-webserver-1}"
DAGSTER_CODE_CONTAINER="${DAGSTER_CODE_CONTAINER:-openclaw-fourok-dagster-code-1}"
FOUROK_APP_CONTAINER="${FOUROK_APP_CONTAINER:-openclaw-fourok-app-1}"
CONNECTOR_SMOKE="${CONNECTOR_SMOKE:-true}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--json]

Print detailed non-secret diagnostics for a fourok/OpenClaw target.

Target modes:
  CHECK_TARGET=ssh    run on GATEWAY_SSH_TARGET over SSH (default)
  CHECK_TARGET=local  run on local Docker host

Environment overrides:
  GATEWAY_SSH_TARGET=root@178.105.10.7
  DAGSTER_WEBSERVER_CONTAINER=openclaw-fourok-dagster-webserver-1
  DAGSTER_CODE_CONTAINER=openclaw-fourok-dagster-code-1
  FOUROK_APP_CONTAINER=openclaw-fourok-app-1
  CONNECTOR_SMOKE=true
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json) shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

python3 - "$CHECK_TARGET" "$GATEWAY_SSH_TARGET" "$DAGSTER_WEBSERVER_CONTAINER" "$DAGSTER_CODE_CONTAINER" "$FOUROK_APP_CONTAINER" "$CONNECTOR_SMOKE" <<'PY'
from __future__ import annotations

import json
import shlex
import subprocess
import sys
from typing import Any

check_target, ssh_target, web, code, app, connector_smoke = sys.argv[1:]


def run(cmd: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)


def shell(command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    if check_target == "local":
        return run(["bash", "-lc", command], timeout)
    return run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", ssh_target, command], timeout)


def docker_exec(container: str, command: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return shell(f"docker exec {shlex.quote(container)} sh -lc {shlex.quote(command)}", timeout)


def ok(proc: subprocess.CompletedProcess[str]) -> bool:
    return proc.returncode == 0

workspace = docker_exec(web, "cat /opt/dagster/dagster_home/workspace.yaml 2>/dev/null || true")
workspace_host = None
for line in workspace.stdout.splitlines():
    stripped = line.strip()
    if stripped.startswith("host:"):
        workspace_host = stripped.split(":", 1)[1].strip()

resolve_host = None
if workspace_host:
    p = docker_exec(web, f"getent hosts {shlex.quote(workspace_host)} >/dev/null && echo ok || echo failed")
    resolve_host = p.stdout.strip() or "failed"

secret_keys = [
    "SLACK_BOT_TOKEN",
    "TAP_SLACK_API_KEY",
    "LINEAR_API_KEY",
    "TWENTY_API_KEY",
    "GOOGLE_WORKSPACE_OAUTH_CLIENT_SECRET_JSON",
    "GOOGLE_WORKSPACE_OAUTH_REFRESH_TOKEN",
    "GOOGLE_WORKSPACE_DRIVE_IDS",
]
secret_probe = docker_exec(code, "python - <<'PY2'\nimport os,json\nkeys=" + repr(secret_keys) + "\nprint(json.dumps({k: bool(os.environ.get(k)) for k in keys}, sort_keys=True))\nPY2")
try:
    secret_presence = json.loads(secret_probe.stdout) if ok(secret_probe) else {}
except json.JSONDecodeError:
    secret_presence = {}

containers = shell("docker ps --format '{{.Names}}\\t{{.Status}}' | grep -E 'openclaw-fourok|openclaw-openclaw-gateway|fourok|dagster' | sort", 60)
container_rows = []
for line in containers.stdout.splitlines():
    if "\t" in line:
        name, status = line.split("\t", 1)
        container_rows.append({"name": name, "status": status})

stage1 = docker_exec(app, "/app/.venv/bin/fourok stage1-acceptance --json --dagster-url http://fourok-dagster-webserver:3001/graphql --grafana-url http://fourok-observability:3000", 180)
try:
    stage1_json = json.loads(stage1.stdout) if stage1.stdout.strip().startswith("{") else None
except json.JSONDecodeError:
    stage1_json = None

connector_results: dict[str, Any] = {}
if connector_smoke.lower() == "true":
    jobs = [
        "google-drive-live-to-raw",
        "linear-live-to-raw",
        "slack-live-to-raw",
        "twenty-live-to-raw",
    ]
    for job in jobs:
        cmd = f"cd /app && TARGET_FOUROK_RAW_JSONL_LANDING_DIR=/app/.local/diagnostics-{job} /app/.venv/bin/meltano --cwd /app/deploy/meltano run {job}"
        p = docker_exec(code, cmd, 120)
        combined = "\n".join([p.stdout, p.stderr])
        interesting = [
            line for line in combined.splitlines()
            if any(token in line.lower() for token in ["failed", "error", "unauthorized", "required", "invalid", "record_count"])
        ][-12:]
        connector_results[job] = {
            "status": "ok" if p.returncode == 0 else "failed",
            "exit_code": p.returncode,
            "diagnostic_lines": interesting,
        }

report = {
    "status": "ok" if stage1_json and stage1_json.get("status") == "ok" else "failed",
    "target": {"mode": check_target, "ssh_target": ssh_target if check_target == "ssh" else None},
    "containers": container_rows,
    "dagster_workspace": {
        "host": workspace_host,
        "host_resolves_from_webserver": resolve_host,
        "raw": workspace.stdout,
    },
    "secret_presence_in_dagster_code": secret_presence,
    "stage1_summary": {
        "exit_code": stage1.returncode,
        "status": stage1_json.get("status") if stage1_json else "invalid_json",
        "checks": stage1_json.get("checks") if stage1_json else None,
        "resume": stage1_json.get("resume") if stage1_json else None,
    },
    "connector_smoke": connector_results,
}
print(json.dumps(report, indent=2, sort_keys=True))
sys.exit(0 if report["status"] == "ok" else 1)
PY
