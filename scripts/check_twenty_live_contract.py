from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from gcb.etl.extract.connectors import load_landed_source_records
from gcb.secrets.env import effective_env


def main() -> int:
    parser = argparse.ArgumentParser(description="Check live Twenty Singer tap contract.")
    parser.add_argument(
        "--artifact-dir",
        type=Path,
        default=Path(".local/test-artifacts/twenty-live-contract"),
        help="Ignored local directory for raw landing files.",
    )
    args = parser.parse_args()

    report = check_twenty_live_contract(args.artifact_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "ok" else 1


def check_twenty_live_contract(artifact_dir: Path) -> dict[str, Any]:
    shutil.rmtree(artifact_dir, ignore_errors=True)
    landing_dir = artifact_dir / "landing"
    landing_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = artifact_dir / "meltano.stderr.log"

    env = effective_env()
    env["TARGET_GCB_RAW_JSONL_LANDING_DIR"] = str(landing_dir)
    env.setdefault("TWENTY_LIMIT", "25")

    with stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            [
                "uv",
                "run",
                "--group",
                "pipeline",
                "meltano",
                "run",
                "twenty-live-to-raw",
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

    companies = load_landed_source_records(landing_dir, stream="twenty_companies")
    people = load_landed_source_records(landing_dir, stream="twenty_people")
    state_path = landing_dir / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}

    return {
        "status": "ok",
        "artifact_dir": str(artifact_dir),
        "company_count": len(companies),
        "person_count": len(people),
        "record_count": len(companies) + len(people),
        "source_systems": sorted({record.source_system for record in companies + people}),
        "record_types": sorted({record.record_type for record in companies + people}),
        "state_keys": sorted(state.keys()) if isinstance(state, dict) else [],
        "streams": sorted(path.stem for path in landing_dir.glob("*.jsonl")),
    }


if __name__ == "__main__":
    sys.exit(main())
