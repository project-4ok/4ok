#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="${REPO_ROOT}/scripts/ssh-4ok-dev-observability-tunnel.sh"

bash -n "${TARGET}"
urls_output="$(${TARGET} --print-urls)"
help_output="$(${TARGET} --help)"

case "${urls_output}" in
  *"Grafana: http://127.0.0.1:13000/d/fourok-local-runtime-logs/fourok-local-runtime-logs"* ) ;;
  *) echo "missing Grafana URL output" >&2; exit 1 ;;
esac

case "${urls_output}" in
  *"Dagster: http://127.0.0.1:13001"* ) ;;
  *) echo "missing Dagster URL output" >&2; exit 1 ;;
esac

case "${help_output}" in
  *"GATEWAY_SSH_TARGET=root@178.105.10.7"* ) ;;
  *) echo "missing default dev gateway target" >&2; exit 1 ;;
esac

if ! grep -F -- '-o ExitOnForwardFailure=yes' "${TARGET}" >/dev/null; then
  echo "tunnel should fail fast when local forwarding cannot bind" >&2
  exit 1
fi

printf 'dev observability tunnel validation passed\n'
