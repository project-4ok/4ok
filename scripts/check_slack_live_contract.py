from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

from gcb.etl.extract.connectors import land_singer_records
from gcb.etl.extract.slack_adapter import load_slack_landed_source_records
from gcb.etl.extract.slack_tap_env import apply_slack_tap_defaults
from gcb.runtime import mcp_retrieval
from gcb.secrets.infisical import InfisicalConfig, SecretProviderError, fetch_infisical_secrets


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live Slack Singer tap contract.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".local/test-artifacts/slack-live-contract"),
        help="Ignored local directory for raw Singer output and landing files.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("GCB_DATABASE_URL", ""),
        help="Optional runtime database URL for active Slack message and retrieval proof.",
    )
    args = parser.parse_args()

    report = check_slack_live_contract(args.artifact_dir, database_url=args.database_url)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def check_slack_live_contract(artifact_dir: Path, *, database_url: str = "") -> dict[str, Any]:
    shutil.rmtree(artifact_dir, ignore_errors=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    try:
        env = _slack_env()
    except SecretProviderError as error:
        return {
            "status": "blocked",
            "stage": "credentials",
            "blocker": _redacted_tail(str(error)),
            "credential_inputs": {
                "has_slack_token": bool(
                    os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("TAP_SLACK_API_KEY")
                ),
                "has_infisical_project_id": bool(
                    _env_first("GCB_INFISICAL_PROJECT_ID", "INFISICAL_PROJECT_ID")
                ),
            },
            "artifact_dir": str(artifact_dir),
            "runtime_database": _runtime_database_probe(database_url),
        }

    config_test = _run(
        ["uv", "run", "--group", "pipeline", "meltano", "config", "test", "tap-slack"],
        env=env,
    )
    discover_output = _run(
        ["uv", "run", "--group", "pipeline", "meltano", "invoke", "tap-slack", "--discover"],
        env=env,
    )
    catalog = json.loads(discover_output.stdout)
    discovered_streams = sorted(
        stream.get("tap_stream_id") or stream.get("stream")
        for stream in catalog.get("streams", [])
        if isinstance(stream, dict)
    )

    singer_output = artifact_dir / "tap-output.singer.jsonl"
    singer_stderr = artifact_dir / "tap-output.stderr.log"
    with (
        singer_output.open("w", encoding="utf-8") as stdout,
        singer_stderr.open("w", encoding="utf-8") as stderr,
    ):
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--group",
                "pipeline",
                "meltano",
                "invoke",
                "tap-slack",
                "--test=record",
            ],
            cwd=".",
            env=env,
            stdout=stdout,
            stderr=stderr,
            text=True,
            timeout=120,
            check=False,
        )
    if completed.returncode != 0:
        return {
            "status": "failed",
            "stage": "test_record",
            "returncode": completed.returncode,
            "stderr_path": str(singer_stderr),
        }

    landing_dir = artifact_dir / "landing"
    landing = land_singer_records(singer_output, landing_dir)
    records = load_slack_landed_source_records(landing_dir)
    runtime_database = _runtime_database_probe(database_url)
    mcp_permission_gate = _mcp_permission_gate_probe(database_url, runtime_database)
    _drop_private_probe_fields(runtime_database)
    status = (
        "ok"
        if _gate_passed(landing.streams, records, runtime_database, mcp_permission_gate)
        else "blocked"
    )

    return {
        "status": status,
        "config_test_returncode": config_test.returncode,
        "discovered_streams": discovered_streams,
        "landed_streams": landing.streams,
        "schema_messages": landing.schema_messages,
        "state_messages": landing.state_messages,
        "record_count": landing.record_count,
        "source_record_count": len(records),
        "source_record_types": sorted({record.record_type for record in records}),
        "source_systems": sorted({record.source_system for record in records}),
        "landing_messages_non_empty": _non_empty_file(landing_dir / "messages.jsonl"),
        "runtime_database": runtime_database,
        "mcp_permission_gate": mcp_permission_gate,
        "blockers": _blockers(landing.streams, records, runtime_database, mcp_permission_gate),
        "artifact_dir": str(artifact_dir),
    }


def _slack_env() -> dict[str, str]:
    config = InfisicalConfig(
        project_id=_env_first("GCB_INFISICAL_PROJECT_ID", "INFISICAL_PROJECT_ID"),
        environment=_env_first("GCB_INFISICAL_ENV", "INFISICAL_ENV") or "runtime",
        path=_env_first("GCB_INFISICAL_PATH", "INFISICAL_PATH") or "/",
        domain=_env_first("GCB_INFISICAL_DOMAIN", "INFISICAL_DOMAIN"),
    )
    env = dict(os.environ)
    if config.project_id or not (env.get("SLACK_BOT_TOKEN") or env.get("TAP_SLACK_API_KEY")):
        env.update(fetch_infisical_secrets(config))
    if env.get("SLACK_BOT_TOKEN") and not env.get("TAP_SLACK_API_KEY"):
        env["TAP_SLACK_API_KEY"] = env["SLACK_BOT_TOKEN"]
    return apply_slack_tap_defaults(env)


def _env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=".",
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{' '.join(command)} failed with exit code {completed.returncode}: "
            f"{_redacted_tail(completed.stderr)}"
        )
    return completed


def _runtime_database_probe(database_url: str) -> dict[str, Any]:
    if not database_url:
        return {"status": "skipped", "reason": "database_url_not_set"}
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            active_messages = int(
                connection.execute(
                    text(
                        "select count(*) from source_records "
                        "where source_system='slack' and record_type='message' "
                        "and lifecycle_state='active'"
                    )
                ).scalar_one()
            )
            current_retrieval = int(
                connection.execute(
                    text(
                        "select count(*) from retrieval_records rr "
                        "join source_records sr on sr.source_ref=rr.source_ref "
                        "where sr.source_system='slack' and sr.record_type='message' "
                        "and sr.lifecycle_state='active' and rr.status='current'"
                    )
                ).scalar_one()
            )
            candidate = (
                connection.execute(
                    text(
                        "select sr.source_ref, sr.permission_refs, rr.prepared_text "
                        "from source_records sr join retrieval_records rr "
                        "on sr.source_ref=rr.source_ref "
                        "where sr.source_system='slack' and sr.record_type='message' "
                        "and sr.lifecycle_state='active' and rr.status='current' "
                        "and rr.prepared_text <> '' "
                        "order by sr.source_ref limit 1"
                    )
                )
                .mappings()
                .first()
            )
        return {
            "status": "ok",
            "active_slack_message_source_records": active_messages,
            "current_slack_message_retrieval_records": current_retrieval,
            "mcp_candidate": _safe_mcp_candidate(candidate),
        }
    except Exception as error:
        return {
            "status": "failed",
            "error_class": type(error).__name__,
            "error": _redacted_tail(str(error)),
        }
    finally:
        engine.dispose()


def _mcp_permission_gate_probe(
    database_url: str,
    runtime_database: dict[str, Any],
) -> dict[str, Any]:
    candidate = runtime_database.get("mcp_candidate")
    if not database_url:
        return {"status": "skipped", "reason": "database_url_not_set"}
    if runtime_database.get("status") != "ok":
        return {"status": "skipped", "reason": "runtime_database_not_ok"}
    if not isinstance(candidate, dict) or not candidate.get("permission_refs"):
        return {"status": "skipped", "reason": "no_active_slack_message_candidate"}

    query = str(candidate.get("_query") or "")
    source_ref = str(candidate.get("source_ref") or "")
    permission_refs = [str(ref) for ref in candidate.get("permission_refs", []) if ref]
    if not query or not source_ref or not permission_refs:
        return {"status": "skipped", "reason": "candidate_missing_query_or_permission"}

    try:
        denied = mcp_retrieval.search_gcb(
            query=query,
            limit=5,
            roles=["operator"],
            database_url=database_url,
        )
        allowed = mcp_retrieval.search_gcb(
            query=query,
            limit=5,
            roles=["operator", *permission_refs],
            database_url=database_url,
        )
    except Exception as error:
        return {
            "status": "failed",
            "error_class": type(error).__name__,
            "error": _redacted_tail(str(error)),
        }

    denied_source_refs = _source_refs(denied)
    allowed_source_refs = _source_refs(allowed)
    allowed_evidence_refs = _evidence_source_refs(allowed)
    return {
        "status": "ok"
        if (
            source_ref in allowed_source_refs
            and source_ref in allowed_evidence_refs
            and not denied_source_refs
            and not denied.get("evidence_items", [])
        )
        else "failed",
        "candidate_source_ref": source_ref,
        "candidate_permission_refs": permission_refs,
        "allowed_result_count": len(allowed.get("results", [])),
        "allowed_evidence_count": len(allowed.get("evidence_items", [])),
        "allowed_includes_candidate": source_ref in allowed_source_refs,
        "allowed_evidence_includes_candidate": source_ref in allowed_evidence_refs,
        "denied_result_count": len(denied.get("results", [])),
        "denied_evidence_count": len(denied.get("evidence_items", [])),
    }


def _safe_mcp_candidate(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    permission_refs = _json_string_list(str(row["permission_refs"]))
    return {
        "source_ref": str(row["source_ref"]),
        "permission_refs": permission_refs,
        "_query": _query_from_prepared_text(str(row["prepared_text"])),
    }


def _query_from_prepared_text(value: str) -> str:
    words = [
        word.strip(".,:;!?()[]{}<>\"'").casefold()
        for word in value.split()
        if len(word.strip(".,:;!?()[]{}<>\"'")) >= 6
    ]
    for word in words:
        if word and not word.startswith("slack:"):
            return word
    return ""


def _json_string_list(value: str) -> list[str]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [item for item in decoded if isinstance(item, str)]


def _source_refs(response: dict[str, Any]) -> set[str]:
    return {
        str(item.get("source_ref"))
        for item in response.get("results", [])
        if isinstance(item, dict) and item.get("source_ref")
    }


def _evidence_source_refs(response: dict[str, Any]) -> set[str]:
    return {
        str(item.get("source_ref"))
        for item in response.get("evidence_items", [])
        if isinstance(item, dict) and item.get("source_ref")
    }


def _gate_passed(
    landed_streams: dict[str, int],
    records: list[Any],
    runtime_database: dict[str, Any],
    mcp_permission_gate: dict[str, Any],
) -> bool:
    return (
        landed_streams.get("messages", 0) > 0
        and any(record.record_type == "message" for record in records)
        and runtime_database.get("active_slack_message_source_records", 0) > 0
        and runtime_database.get("current_slack_message_retrieval_records", 0) > 0
        and mcp_permission_gate.get("status") == "ok"
    )


def _blockers(
    landed_streams: dict[str, int],
    records: list[Any],
    runtime_database: dict[str, Any],
    mcp_permission_gate: dict[str, Any],
) -> list[str]:
    blockers = []
    if landed_streams.get("messages", 0) <= 0:
        blockers.append("live_tap_landed_no_messages")
    if not any(record.record_type == "message" for record in records):
        blockers.append("adapter_loaded_no_message_source_records")
    if runtime_database.get("status") == "skipped":
        blockers.append(str(runtime_database.get("reason")))
    elif runtime_database.get("active_slack_message_source_records", 0) <= 0:
        blockers.append("runtime_db_has_no_active_slack_message_source_records")
    elif runtime_database.get("current_slack_message_retrieval_records", 0) <= 0:
        blockers.append("runtime_db_has_no_current_slack_message_retrieval_records")
    if mcp_permission_gate.get("status") != "ok":
        blockers.append(f"mcp_permission_gate_{mcp_permission_gate.get('status')}")
    return blockers


def _non_empty_file(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def _drop_private_probe_fields(runtime_database: dict[str, Any]) -> None:
    candidate = runtime_database.get("mcp_candidate")
    if isinstance(candidate, dict):
        candidate.pop("_query", None)


def _redacted_tail(value: str, *, limit: int = 1000) -> str:
    redacted = []
    for line in value.splitlines()[-20:]:
        if any(token in line.lower() for token in ("secret", "token", "api_key", "authorization")):
            continue
        redacted.append(line)
    return "\n".join(redacted)[-limit:]


if __name__ == "__main__":
    sys.exit(main())
