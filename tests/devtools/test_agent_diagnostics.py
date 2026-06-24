from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gcb.devtools.diagnostics import agent_diagnostics


def test_agent_diagnostics_reports_recent_errors_without_printing_log_bodies(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 6, 9, 10, 30, tzinfo=UTC)
    log_dir = tmp_path / ".local" / "test-artifacts" / "dagster-pipeline-proof"
    log_dir.mkdir(parents=True)
    recent = log_dir / "dagster.stderr.log"
    recent.write_text(
        "INFO loaded assets\nERROR database migration failed for synthetic fixture\n",
        encoding="utf-8",
    )
    old = log_dir / "old.stderr.log"
    old.write_text("ERROR old failure\n", encoding="utf-8")
    recent_mtime = (now - timedelta(minutes=10)).timestamp()
    old_mtime = (now - timedelta(hours=2)).timestamp()
    os.utime(recent, (recent_mtime, recent_mtime))
    os.utime(old, (old_mtime, old_mtime))

    report = agent_diagnostics(project_root=tmp_path, now=now)

    recent_errors = report["recent_errors"]
    assert recent_errors["window_seconds"] == 3600
    assert recent_errors["count"] == 1
    assert recent_errors["entries"] == [
        {
            "path": ".local/test-artifacts/dagster-pipeline-proof/dagster.stderr.log",
            "line_number": 2,
            "matched": "ERROR",
            "modified_at": "2026-06-09T10:20:00+00:00",
        }
    ]
    assert "database migration failed" not in json.dumps(report)
    assert report["status"] == "warning"


def test_agent_diagnostics_json_shape_names_runtime_surfaces_and_next_commands(
    tmp_path: Path,
) -> None:
    report = agent_diagnostics(project_root=tmp_path)

    assert set(report) == {
        "checks",
        "generated_at",
        "next_commands",
        "project_root",
        "recent_errors",
        "status",
    }
    checks = {check["name"]: check for check in report["checks"]}
    assert set(checks) == {
        "dagster",
        "database",
        "docker_pipeline",
        "raw_store",
        "recent_errors",
        "search",
    }
    assert checks["database"]["status"] == "skipped"
    assert checks["search"]["status"] == "skipped"
    assert "uv run gcb-dev agent-diagnostics --json" in report["next_commands"]
