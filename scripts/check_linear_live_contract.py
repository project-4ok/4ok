from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from gcb.etl.extract.connectors import load_landed_source_records
from gcb.secrets.infisical import InfisicalConfig, fetch_infisical_secrets


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live Linear Singer tap contract.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".local/test-artifacts/linear-live-contract"),
        help="Ignored local directory for raw landing files.",
    )
    args = parser.parse_args()

    report = check_linear_live_contract(args.artifact_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def check_linear_live_contract(artifact_dir: Path) -> dict[str, Any]:
    shutil.rmtree(artifact_dir, ignore_errors=True)
    landing_dir = artifact_dir / "landing"
    landing_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = artifact_dir / "meltano.stderr.log"

    env = {
        **os.environ,
        **_infisical_secrets(),
        "TARGET_GCB_RAW_JSONL_LANDING_DIR": str(landing_dir),
    }
    env.setdefault("LINEAR_LIMIT", "25")

    with stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--group",
                "pipeline",
                "meltano",
                "run",
                "linear-live-to-raw",
            ],
            cwd=".",
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            text=True,
            timeout=120,
            check=False,
        )
    if completed.returncode != 0:
        return {
            "status": "failed",
            "stage": "meltano_run",
            "returncode": completed.returncode,
            "stderr_path": str(stderr_path),
        }

    users = load_landed_source_records(landing_dir, stream="linear_users")
    issues = load_landed_source_records(landing_dir, stream="linear_issues")
    comments = load_landed_source_records(landing_dir, stream="linear_comments")
    state_path = landing_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    records = users + issues + comments

    return {
        "status": "ok",
        "artifact_dir": str(artifact_dir),
        "user_count": len(users),
        "issue_count": len(issues),
        "comment_count": len(comments),
        "record_count": len(records),
        "source_systems": sorted({record.source_system for record in records}),
        "record_types": sorted({record.record_type for record in records}),
        "state_keys": sorted(state.keys()) if isinstance(state, dict) else [],
        "streams": sorted(path.stem for path in landing_dir.glob("*.jsonl")),
    }


def _infisical_secrets() -> dict[str, str]:
    return fetch_infisical_secrets(
        InfisicalConfig(
            project_id=_env_first("GCB_INFISICAL_PROJECT_ID", "INFISICAL_PROJECT_ID"),
            environment=_env_first("GCB_INFISICAL_ENV", "INFISICAL_ENV") or "runtime",
            path=_env_first("GCB_INFISICAL_PATH", "INFISICAL_PATH") or "/",
            domain=_env_first("GCB_INFISICAL_DOMAIN", "INFISICAL_DOMAIN"),
        )
    )


def _env_first(*names: str) -> str:
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


if __name__ == "__main__":
    sys.exit(main())
