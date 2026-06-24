#!/usr/bin/env bash
set -euo pipefail

GATEWAY_SSH_TARGET="${GATEWAY_SSH_TARGET:-root@178.105.10.7}"
LOCAL_GRAFANA_PORT="${LOCAL_GRAFANA_PORT:-13000}"
LOCAL_DAGSTER_PORT="${LOCAL_DAGSTER_PORT:-13001}"
REMOTE_GRAFANA_HOST="${REMOTE_GRAFANA_HOST:-127.0.0.1}"
REMOTE_GRAFANA_PORT="${REMOTE_GRAFANA_PORT:-13000}"
REMOTE_DAGSTER_HOST="${REMOTE_DAGSTER_HOST:-127.0.0.1}"
REMOTE_DAGSTER_PORT="${REMOTE_DAGSTER_PORT:-13001}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--print-urls] [--] [extra ssh args...]

Open SSH tunnels to the 4OK dev gateway observability UIs.

Defaults:
  Grafana: http://127.0.0.1:${LOCAL_GRAFANA_PORT} -> ${GATEWAY_SSH_TARGET}:${REMOTE_GRAFANA_HOST}:${REMOTE_GRAFANA_PORT}
  Dagster: http://127.0.0.1:${LOCAL_DAGSTER_PORT} -> ${GATEWAY_SSH_TARGET}:${REMOTE_DAGSTER_HOST}:${REMOTE_DAGSTER_PORT}

Environment overrides:
  GATEWAY_SSH_TARGET=root@178.105.10.7
  LOCAL_GRAFANA_PORT=13000
  LOCAL_DAGSTER_PORT=13001
  REMOTE_GRAFANA_HOST=127.0.0.1
  REMOTE_GRAFANA_PORT=13000
  REMOTE_DAGSTER_HOST=127.0.0.1
  REMOTE_DAGSTER_PORT=13001

Examples:
  scripts/ssh-fourok-dev-observability-tunnel.sh
  scripts/ssh-fourok-dev-observability-tunnel.sh --print-urls
  GATEWAY_SSH_TARGET=root@dev-gateway.example scripts/ssh-fourok-dev-observability-tunnel.sh
EOF
}

ssh_args=()
print_urls=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --print-urls)
      print_urls=true
      shift
      ;;
    --)
      shift
      ssh_args+=("$@")
      break
      ;;
    *)
      ssh_args+=("$1")
      shift
      ;;
  esac
done

if [[ "${print_urls}" == "true" ]]; then
  printf 'Grafana: http://127.0.0.1:%s/d/fourok-local-runtime-logs/fourok-local-runtime-logs\n' "${LOCAL_GRAFANA_PORT}"
  printf 'Dagster: http://127.0.0.1:%s\n' "${LOCAL_DAGSTER_PORT}"
  exit 0
fi

printf 'Opening 4OK dev observability tunnel to %s\n' "${GATEWAY_SSH_TARGET}" >&2
printf 'Grafana: http://127.0.0.1:%s/d/fourok-local-runtime-logs/fourok-local-runtime-logs\n' "${LOCAL_GRAFANA_PORT}" >&2
printf 'Dagster: http://127.0.0.1:%s\n' "${LOCAL_DAGSTER_PORT}" >&2
printf 'Press Ctrl-C to close the tunnel.\n' >&2

exec ssh \
  -N \
  -o ExitOnForwardFailure=yes \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -L "127.0.0.1:${LOCAL_GRAFANA_PORT}:${REMOTE_GRAFANA_HOST}:${REMOTE_GRAFANA_PORT}" \
  -L "127.0.0.1:${LOCAL_DAGSTER_PORT}:${REMOTE_DAGSTER_HOST}:${REMOTE_DAGSTER_PORT}" \
  "${ssh_args[@]}" \
  "${GATEWAY_SSH_TARGET}"
