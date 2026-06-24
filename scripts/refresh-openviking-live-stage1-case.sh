#!/usr/bin/env bash
set -euo pipefail

CHECK_TARGET="${CHECK_TARGET:-ssh}"
GATEWAY_SSH_TARGET="${GATEWAY_SSH_TARGET:-root@178.105.10.7}"
FOUR_OK_APP_CONTAINER="${FOUR_OK_APP_CONTAINER:-openclaw-fourok-app-1}"
OPENVIKING_SESSIONS_DIR="${OPENVIKING_SESSIONS_DIR:-/var/lib/openclaw/sessions}"
OPENVIKING_QUERY="${OPENVIKING_QUERY:-What are my priorities today}"
OPENVIKING_CASE_ID="${OPENVIKING_CASE_ID:-openviking-live-current-message}"
STAGE1_CASES_OUTPUT="${STAGE1_CASES_OUTPUT:-/app/.local/stage1/live_retrieval_case_set.generated.json}"
NORMALIZED_OUTPUT="${NORMALIZED_OUTPUT:-/app/.local/openviking-live-normalized.jsonl}"
BASE_CASES_PATH="${BASE_CASES_PATH:-/app/fixtures/retrieval_eval/live_retrieval_case_set.json}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--json]

Normalize OpenClaw/OpenViking session messages already mounted in the 4OK app
container, backfill them into 4OK, and generate a Stage 1 case set that points
at a current host-specific OpenViking message.

Target modes:
  CHECK_TARGET=ssh    run through GATEWAY_SSH_TARGET over SSH (default)
  CHECK_TARGET=local  run docker locally

Environment overrides:
  GATEWAY_SSH_TARGET=root@178.105.10.7
  FOUR_OK_APP_CONTAINER=openclaw-fourok-app-1
  OPENVIKING_SESSIONS_DIR=/var/lib/openclaw/sessions
  OPENVIKING_QUERY='What are my priorities today'
  OPENVIKING_CASE_ID=openviking-live-current-message
  STAGE1_CASES_OUTPUT=/app/.local/stage1/live_retrieval_case_set.generated.json
  NORMALIZED_OUTPUT=/app/.local/openviking-live-normalized.jsonl

Then run:
  STAGE1_CASES=/app/.local/stage1/live_retrieval_case_set.generated.json scripts/check-4ok-dev-all.sh --json
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --json)
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

remote_script=$(cat <<'SH'
set -euo pipefail
: "${FOUR_OK_APP_CONTAINER:?set FOUR_OK_APP_CONTAINER}"
: "${OPENVIKING_SESSIONS_DIR:?set OPENVIKING_SESSIONS_DIR}"
: "${OPENVIKING_QUERY:?set OPENVIKING_QUERY}"
: "${OPENVIKING_CASE_ID:?set OPENVIKING_CASE_ID}"
: "${STAGE1_CASES_OUTPUT:?set STAGE1_CASES_OUTPUT}"
: "${NORMALIZED_OUTPUT:?set NORMALIZED_OUTPUT}"
: "${BASE_CASES_PATH:?set BASE_CASES_PATH}"

docker exec \
  -e OPENVIKING_SESSIONS_DIR \
  -e OPENVIKING_QUERY \
  -e OPENVIKING_CASE_ID \
  -e STAGE1_CASES_OUTPUT \
  -e NORMALIZED_OUTPUT \
  -e BASE_CASES_PATH \
  "$FOUR_OK_APP_CONTAINER" \
  /app/.venv/bin/python - <<'PY'
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

sessions_dir = Path(os.environ["OPENVIKING_SESSIONS_DIR"])
query = os.environ["OPENVIKING_QUERY"]
case_id = os.environ["OPENVIKING_CASE_ID"]
cases_output = Path(os.environ["STAGE1_CASES_OUTPUT"])
normalized_output = Path(os.environ["NORMALIZED_OUTPUT"])
base_cases_path = Path(os.environ["BASE_CASES_PATH"])

if not sessions_dir.exists():
    raise SystemExit(f"OpenViking sessions dir is not mounted: {sessions_dir}")

normalized_output.parent.mkdir(parents=True, exist_ok=True)
cases_output.parent.mkdir(parents=True, exist_ok=True)

def text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                value = item.get("text") or item.get("content")
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts)
    return ""

chosen: dict[str, Any] | None = None
count = 0
with normalized_output.open("w", encoding="utf-8") as output:
    for path in sorted(sessions_dir.glob("*topic-*.jsonl")):
        name = path.name
        if any(marker in name for marker in (".trajectory", ".deleted", ".codex-app-server", ".reset")):
            continue
        stem = name.removesuffix(".jsonl")
        with path.open(encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                message = obj.get("message")
                if obj.get("type") != "message" or not isinstance(message, dict):
                    continue
                content = text_from_content(message.get("content"))
                if not content.strip():
                    continue
                normalized = {
                    "conversation_id": stem,
                    "session_id": stem,
                    "thread_id": stem,
                    "message_id": obj.get("id") or message.get("id"),
                    "timestamp": obj.get("timestamp") or message.get("timestamp"),
                    "message": {"role": message.get("role", "unknown"), "content": content},
                    "speaker": message.get("senderName") or message.get("senderId") or message.get("role", "unknown"),
                    "permission_refs": [f"openviking:conversation:{stem}"],
                }
                output.write(json.dumps(normalized, ensure_ascii=False) + "\n")
                count += 1
                if chosen is None and query.lower() in content.lower():
                    chosen = normalized

if count == 0:
    raise SystemExit(f"No OpenViking messages found in {sessions_dir}")
if chosen is None:
    raise SystemExit(f"No OpenViking message matched query substring: {query!r}")

# Import after normalization so generated case points at retrievable source data.
import subprocess
proc = subprocess.run(
    ["/app/.venv/bin/fourok", "backfill-openviking-messages", str(normalized_output)],
    text=True,
    capture_output=True,
)
if proc.returncode != 0:
    raise SystemExit(proc.stderr or proc.stdout or "OpenViking backfill failed")
backfill = json.loads(proc.stdout)

conversation_id = chosen["conversation_id"]
message_id = chosen["message_id"]
source_ref = (
    f"openviking:conversation:{conversation_id}:"
    f"session:{conversation_id}:message:{message_id}"
)
case = {
    "id": case_id,
    "query": query,
    "expected_source_ref_prefix": source_ref,
    "expected_source_system": "openviking",
    "expected_record_type": "message",
    "expected_permission_refs": [f"openviking:conversation:{conversation_id}"],
}

cases = json.loads(base_cases_path.read_text(encoding="utf-8"))
if not isinstance(cases, list):
    raise SystemExit(f"Base cases file is not a JSON list: {base_cases_path}")
replaced = False
next_cases = []
for existing in cases:
    if isinstance(existing, dict) and existing.get("expected_source_system") == "openviking":
        if not replaced:
            next_cases.append(case)
            replaced = True
        continue
    next_cases.append(existing)
if not replaced:
    next_cases.append(case)
cases_output.write_text(json.dumps(next_cases, indent=2) + "\n", encoding="utf-8")

print(json.dumps({
    "status": "ok",
    "sessions_dir": str(sessions_dir),
    "normalized_output": str(normalized_output),
    "normalized_message_count": count,
    "backfill_record_count": backfill.get("record_count"),
    "backfill_retrieval_unit_count": backfill.get("retrieval_unit_count"),
    "stage1_cases": str(cases_output),
    "openviking_case": case,
}, indent=2, sort_keys=True))
PY
SH
)

env_prefix=(
  "FOUR_OK_APP_CONTAINER=$(printf '%q' "${FOUR_OK_APP_CONTAINER}")"
  "OPENVIKING_SESSIONS_DIR=$(printf '%q' "${OPENVIKING_SESSIONS_DIR}")"
  "OPENVIKING_QUERY=$(printf '%q' "${OPENVIKING_QUERY}")"
  "OPENVIKING_CASE_ID=$(printf '%q' "${OPENVIKING_CASE_ID}")"
  "STAGE1_CASES_OUTPUT=$(printf '%q' "${STAGE1_CASES_OUTPUT}")"
  "NORMALIZED_OUTPUT=$(printf '%q' "${NORMALIZED_OUTPUT}")"
  "BASE_CASES_PATH=$(printf '%q' "${BASE_CASES_PATH}")"
)
command="${env_prefix[*]} bash -lc $(printf '%q' "${remote_script}")"

case "${CHECK_TARGET}" in
  local)
    bash -lc "${command}"
    ;;
  ssh)
    ssh -o BatchMode=yes -o ConnectTimeout=10 "${GATEWAY_SSH_TARGET}" "${command}"
    ;;
  *)
    echo "unsupported CHECK_TARGET: ${CHECK_TARGET}" >&2
    exit 2
    ;;
esac
