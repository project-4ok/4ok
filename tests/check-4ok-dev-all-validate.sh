#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="${REPO_ROOT}/scripts/check-4ok-dev-all.sh"

bash -n "${TARGET}"
help_output="$(${TARGET} --help)"

for expected in \
  "deployment surface check via scripts/check-4ok-dev-deployment.sh --json" \
  "fourok stage1-acceptance --json on the selected target" \
  "The top-level status is ok only when both gates return status=ok." \
  "CHECK_TARGET=ssh    run target checks on GATEWAY_SSH_TARGET over SSH" \
  "CHECK_TARGET=local  run target checks on this machine" \
  "STAGE1_RUNNER=auto    ssh -> docker, local -> host" \
  "STAGE1_RUNNER=docker  run stage1 inside FOUR_OK_STAGE1_CONTAINER on the target" \
  "STAGE1_RUNNER=host    run stage1 with LOCAL_STAGE1_COMMAND on the target shell" \
  "GATEWAY_SSH_TARGET=root@178.105.10.7" \
  "LOCAL_STAGE1_COMMAND='uv run fourok'" \
  "STAGE1_CASES=/app/.local/stage1/live_retrieval_case_set.generated.json" \
  "REFRESH_DAGSTER_BACKFILL=true"
do
  if [[ "${help_output}" != *"${expected}"* ]]; then
    echo "missing expected help text: ${expected}" >&2
    exit 1
  fi
done

for expected in \
  "deployment" \
  "stage1_acceptance" \
  "status = \"ok\" if all(check.get(\"status\") == \"ok\"" \
  "sys.exit(0 if status == \"ok\" else 1)" \
  "CHECK_TARGET" \
  "STAGE1_RUNNER" \
  "STAGE1_CASES" \
  "target_shell_command" \
  "docker exec" \
  "LOCAL_STAGE1_COMMAND" \
  "stage1-acceptance" \
  "check-4ok-dev-deployment.sh" \
  "run-4ok-dev-dagster-backfill.sh" \
  "REFRESH_DAGSTER_BACKFILL" \
  "dagster_backfill"
do
  if ! grep -F "${expected}" "${TARGET}" >/dev/null; then
    echo "missing expected host-agnostic combined-check implementation text: ${expected}" >&2
    exit 1
  fi
done

printf 'combined status validation passed\n'
