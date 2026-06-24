#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${FOUROK_REPO_URL:-https://github.com/project-fourok/fourok.git}"
INSTALL_DIR="${FOUROK_INSTALL_DIR:-$HOME/fourok}"
START_STACK="${FOUROK_INSTALL_START_STACK:-1}"

log() {
  printf '\n==> %s\n' "$*"
}

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 1
  fi
}

port_available() {
  uv run python - "$1" <<'PY'
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    sock.bind(("127.0.0.1", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

port_reserved() {
  case " ${FOUROK_RESERVED_HOST_PORTS:-} " in
    *" $1 "*) return 0 ;;
    *) return 1 ;;
  esac
}

reserve_host_port() {
  FOUROK_RESERVED_HOST_PORTS="${FOUROK_RESERVED_HOST_PORTS:-} $1"
}

choose_host_port() {
  local var_name="$1"
  local preferred_port="$2"
  local port="${!var_name:-$preferred_port}"

  if [ "${!var_name:-}" != "" ]; then
    reserve_host_port "$port"
    export "$var_name=$port"
    return 0
  fi

  while port_reserved "$port" || ! port_available "$port"; do
    if [ "$port" = "$preferred_port" ]; then
      log "Port $preferred_port is busy; choosing a free local port for $var_name"
    fi
    port=$((port + 1))
  done

  reserve_host_port "$port"
  export "$var_name=$port"
}

choose_onboarding_ports() {
  choose_host_port FOUROK_GRAFANA_PORT 3000
  choose_host_port FOUROK_LOKI_PORT 3100
  choose_host_port FOUROK_TEMPO_PORT 3200
  choose_host_port FOUROK_OTLP_GRPC_PORT 4317
  choose_host_port FOUROK_OTLP_HTTP_PORT 4318
  choose_host_port FOUROK_DAGSTER_PORT 3001
  choose_host_port FOUROK_MCP_PORT 8010
}

install_uv() {
  if need_command uv; then
    return 0
  fi
  log "Installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if ! need_command uv; then
    printf 'uv install did not put uv on PATH. Open a new shell or add ~/.local/bin to PATH.\n' >&2
    exit 1
  fi
}

require_runtime() {
  if ! need_command git; then
    printf 'git is required. Install git and rerun this installer.\n' >&2
    exit 1
  fi
  if ! need_command docker; then
    printf 'Docker is required to start the local fourok stack. Install Docker and rerun this installer.\n' >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    printf 'Docker Compose v2 is required. Install the docker compose plugin and rerun this installer.\n' >&2
    exit 1
  fi
}

checkout_repo() {
  if [ -z "${FOUROK_INSTALL_DIR:-}" ] && [ -f "pyproject.toml" ] && [ -d "src/fourok" ]; then
    log "Using current fourok checkout: $(pwd)"
    return 0
  fi

  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing checkout: $INSTALL_DIR"
    cd "$INSTALL_DIR"
    git pull --ff-only
    return 0
  fi

  log "Cloning fourok into $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
}

write_local_config() {
  mkdir -p .local/raw .local/backups
  if [ -f .local/fourok.toml ]; then
    log "Keeping existing local config: .local/fourok.toml"
    return 0
  fi

  log "Writing local runtime config: .local/fourok.toml"
  cat >.local/fourok.toml <<'EOF'
[raw_store]
backend = "filesystem"
path = "/app/.local/raw"

[backup]
path = "/app/.local/backups"

[telemetry]
enabled = true
endpoint = "http://observability:4318"
service_name = "fourok-app"

[connectors]
enabled = []
EOF
}

start_local_stack() {
  export POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-local-check}"
  export DAGSTER_POSTGRES_PASSWORD="${DAGSTER_POSTGRES_PASSWORD:-local-check}"
  export FOUROK_IMAGE_TAG="${FOUROK_IMAGE_TAG:-$(git rev-parse --short HEAD)}"
  export FOUROK_DATABASE_URL="${FOUROK_DATABASE_URL:-postgresql+psycopg://fourok:${POSTGRES_PASSWORD}@postgres:5432/fourok}"
  choose_onboarding_ports

  log "Starting local runtime, observability, and pipeline containers"
  docker compose \
    up \
    --build \
    --force-recreate \
    -d \
    postgres \
    app \
    mcp \
    observability \
    promtail \
    fourok-metrics-exporter \
    dagster-postgres \
    dagster-code \
    dagster-webserver \
    dagster-daemon
}

seed_fixture_data() {
  log "Seeding fixture retrieval data"
  for attempt in $(seq 1 12); do
    if docker compose exec -T app /app/.venv/bin/fourok search "refund cancellation payment" >/dev/null; then
      return 0
    fi
    log "Fixture seed not ready yet; retrying ($attempt/12)"
    sleep 5
  done
  printf 'Could not seed fixture retrieval data. Check docker compose logs app and retry.\n' >&2
  exit 1
}

main() {
  log "fourok local onboarding"
  require_runtime
  install_uv
  checkout_repo

  log "Installing Python dependencies"
  uv sync

  write_local_config

  log "Checking Docker Compose configuration"
  uv run fourok-dev compose-config >/dev/null

  if [ "$START_STACK" = "0" ]; then
    log "Skipping container startup because FOUROK_INSTALL_START_STACK=0"
  else
    log "Starting local runtime, observability, and pipeline containers"
    start_local_stack
    seed_fixture_data
  fi

  log "fourok is ready"
  printf 'Project: %s\n' "$(pwd)"
  printf 'Next:    uv run fourok onboard\n'
  printf 'Status:  uv run fourok status\n'
  printf 'Try:     uv run fourok retrieve "refund cancellation payment"\n'
  printf '\nSecrets and connector credentials are not configured by this installer.\n'
}

main "$@"
