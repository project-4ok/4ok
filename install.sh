#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${FOUROK_REPO_URL:-https://github.com/project-4ok/4ok.git}"
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
  if ! docker info >/dev/null 2>&1; then
    printf 'Docker is installed, but the Docker daemon is not reachable. Start Docker and rerun this installer.\n' >&2
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

install_cli_shims() {
  local bin_dir="$HOME/.local/bin"
  local project_dir
  project_dir="$(pwd -P)"

  log "Installing fourok CLI shims into $bin_dir"
  mkdir -p "$bin_dir"

  for command in fourok fourok-dev fourok-mcp; do
    cat >"$bin_dir/$command" <<EOF
#!/usr/bin/env bash
exec uv --project "$project_dir" run $command "\$@"
EOF
    chmod +x "$bin_dir/$command"
  done

  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *)
      printf 'Add ~/.local/bin to PATH to use fourok directly from a new shell:\n'
      printf '  export PATH="$HOME/.local/bin:$PATH"\n'
      ;;
  esac
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

main() {
  log "fourok local onboarding"
  require_runtime
  install_uv
  checkout_repo

  log "Installing Python dependencies"
  uv sync

  install_cli_shims

  write_local_config

  log "Checking Docker Compose configuration"
  uv run fourok-dev compose-config >/dev/null

  if [ "$START_STACK" = "0" ]; then
    log "Skipping container startup because FOUROK_INSTALL_START_STACK=0"
  else
    log "Starting local runtime, observability, and pipeline containers"
    start_local_stack
  fi

  log "fourok is ready"
  printf 'Project: %s\n' "$(pwd)"
  printf 'Next:    fourok onboard\n'
  printf 'Status:  fourok status\n'
  printf '\nSecrets and connector credentials are not configured by this installer.\n'
}

main "$@"
