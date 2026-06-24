#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${GCB_REPO_URL:-https://github.com/project-4ok/4ok.git}"
INSTALL_DIR="${GCB_INSTALL_DIR:-$HOME/4ok}"
START_STACK="${GCB_INSTALL_START_STACK:-1}"

log() {
  printf '\n==> %s\n' "$*"
}

need_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 1
  fi
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
    printf 'Docker is required to start the local 4ok stack. Install Docker and rerun this installer.\n' >&2
    exit 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    printf 'Docker Compose v2 is required. Install the docker compose plugin and rerun this installer.\n' >&2
    exit 1
  fi
}

checkout_repo() {
  if [ -z "${GCB_INSTALL_DIR:-}" ] && [ -f "pyproject.toml" ] && [ -d "src/gcb" ]; then
    log "Using current 4ok checkout: $(pwd)"
    return 0
  fi

  if [ -d "$INSTALL_DIR/.git" ]; then
    log "Updating existing checkout: $INSTALL_DIR"
    cd "$INSTALL_DIR"
    git pull --ff-only
    return 0
  fi

  log "Cloning 4ok into $INSTALL_DIR"
  git clone "$REPO_URL" "$INSTALL_DIR"
  cd "$INSTALL_DIR"
}

main() {
  log "4ok local onboarding"
  require_runtime
  install_uv
  checkout_repo

  log "Installing Python dependencies"
  uv sync

  log "Checking Docker Compose configuration"
  uv run gcb-dev compose-config >/dev/null

  if [ "$START_STACK" = "0" ]; then
    log "Skipping container startup because GCB_INSTALL_START_STACK=0"
  else
    log "Starting local runtime, observability, and pipeline containers"
    uv run gcb-dev stack-up
  fi

  log "4ok is ready"
  printf 'Project: %s\n' "$(pwd)"
  printf 'Status:  uv run gcb-dev pipeline-ps\n'
  printf 'Try:     uv run gcb search "refund cancellation payment"\n'
  printf '\nSecrets and connector credentials are not configured by this installer.\n'
}

main "$@"
