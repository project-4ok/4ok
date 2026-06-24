#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="${REPO_ROOT}/scripts/check-fourok-dev-deployment.sh"

bash -n "${TARGET}"
help_output="$(${TARGET} --help)"

for expected in \
  "CHECK_TARGET=ssh    run Docker/curl checks on GATEWAY_SSH_TARGET over SSH" \
  "CHECK_TARGET=local  run Docker/curl checks on the local machine" \
  "GATEWAY_SSH_TARGET=root@178.105.10.7" \
  "OPENCLAW_IMAGE_WORKFLOW_REQUIRED=false" \
  "FOUROK_CRITICAL_CONTAINERS=comma,separated,container,names" \
  "GRAFANA_URL=http://127.0.0.1:13000" \
  "DAGSTER_SERVER_INFO_URL=http://127.0.0.1:13001/server_info" \
  "The command prints JSON and exits non-zero unless the deployment status is ok."
do
  if [[ "${help_output}" != *"${expected}"* ]]; then
    echo "missing expected help text: ${expected}" >&2
    exit 1
  fi
done

for expected in \
  "CHECK_TARGET" \
  "project-fourok/fourok-infrastructure-prod" \
  "check_status" \
  "newest_run_status" \
  "newest_completed_run" \
  "required" \
  "optional_check_status" \
  "fourok-openclaw-dev-image.yml" \
  "dev-customer-gateway-fourok-runtime-deploy" \
  "openclaw-openclaw-gateway-1" \
  "openclaw-fourok-app-1" \
  "FOUROK_RETRIEVE_CONTAINER=openclaw-fourok-app-1" \
  "FOUROK_RETRIEVE_COMMAND=/app/.venv/bin/fourok" \
  "retrieve --format json" \
  "fourok-local-runtime-logs" \
  "target_shell" \
  "bash" \
  "ssh"
do
  if ! grep -F "${expected}" "${TARGET}" >/dev/null; then
    echo "missing expected host-agnostic deployment check: ${expected}" >&2
    exit 1
  fi
done

printf 'deployment status validation passed\n'
