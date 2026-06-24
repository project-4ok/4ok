#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET="${REPO_ROOT}/scripts/refresh-openviking-live-stage1-case.sh"

bash -n "${TARGET}"
help_output="$(${TARGET} --help)"

for expected in \
  "Normalize OpenClaw/OpenViking session messages" \
  "CHECK_TARGET=ssh" \
  "CHECK_TARGET=local" \
  "OPENVIKING_SESSIONS_DIR=/var/lib/openclaw/sessions" \
  "STAGE1_CASES=/app/.local/stage1/live_retrieval_case_set.generated.json" \
  "scripts/check-4ok-dev-all.sh --json"
do
  if [[ "${help_output}" != *"${expected}"* ]]; then
    echo "missing expected help text: ${expected}" >&2
    exit 1
  fi
done

for expected in \
  "docker exec" \
  "backfill-openviking-messages" \
  "live_retrieval_case_set.generated.json" \
  "expected_source_system\": \"openviking" \
  "expected_permission_refs" \
  "OPENVIKING_QUERY"
do
  if ! grep -F "${expected}" "${TARGET}" >/dev/null; then
    echo "missing expected OpenViking refresh implementation text: ${expected}" >&2
    exit 1
  fi
done

printf 'openviking refresh validation passed\n'
