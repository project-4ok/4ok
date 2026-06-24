#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="${REPO_ROOT}/scripts/run-4ok-dev-dagster-backfill.sh"

bash -n "${TARGET}"
help_output="$(${TARGET} --help)"

for expected in \
  "Launch and poll fourok_hourly_live_backfill through the deployed Dagster webserver GraphQL API" \
  "CHECK_TARGET=ssh" \
  "DAGSTER_GRAPHQL_URL=http://127.0.0.1:13001/graphql" \
  "DAGSTER_REPOSITORY_LOCATION=fourok_pipeline" \
  "DAGSTER_REPOSITORY_NAME=__repository__" \
  "DAGSTER_JOB_NAME=fourok_hourly_live_backfill" \
  "DAGSTER_POLL_TIMEOUT_SECONDS=600"
do
  if [[ "${help_output}" != *"${expected}"* ]]; then
    echo "missing expected help text: ${expected}" >&2
    exit 1
  fi
done

for expected in \
  "launchRun" \
  "ExecutionParams" \
  "runOrError" \
  "hermes-post-deploy-verify" \
  "urllib.request" \
  "target_python_command" \
  "SUCCESS" \
  "status"
do
  if ! grep -F "${expected}" "${TARGET}" >/dev/null; then
    echo "missing expected Dagster GraphQL launch implementation text: ${expected}" >&2
    exit 1
  fi
done

printf 'dagster backfill launcher validation passed\n'
