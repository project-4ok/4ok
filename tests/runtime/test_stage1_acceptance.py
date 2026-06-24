from __future__ import annotations

import json
from pathlib import Path

import pytest

from fourok.cli import main
from fourok.runtime.stage1_acceptance import _dagster_gate_report, stage1_acceptance_report


def test_stage1_acceptance_report_requires_all_gate_checks_ok() -> None:
    report = stage1_acceptance_report(
        health=lambda: {"status": "ok"},
        retrieval=lambda: {"status": "ok", "summary": {"failed": 0}},
        permission=lambda: {"status": "ok", "checked_cases": 2},
        dagster=lambda: {"status": "ok", "repository_status": "ok"},
        grafana=lambda: {"status": "failed", "dashboard_uid": "missing"},
    )

    assert report["status"] == "failed"
    assert report["checks"] == {
        "health": "ok",
        "retrieval": "ok",
        "permission": "ok",
        "dagster": "ok",
        "grafana": "failed",
    }
    assert report["grafana"] == {"status": "failed", "dashboard_uid": "missing"}
    assert report["resume"] == {
        "open_gates": ["grafana"],
        "last_verification": "uv run fourok stage1-acceptance --json",
        "blockers": ["grafana"],
        "next_command": "uv run fourok stage1-acceptance --json",
    }


def test_dagster_gate_fails_when_runtime_status_reports_latest_failed_step() -> None:
    report = _dagster_gate_report(
        {
            "status": "ok",
            "repository_status": "ok",
            "schedules": {"fourok_hourly_live_backfill_schedule": "RUNNING"},
            "sensors": {"fourok_webhook_backlog_sensor": "RUNNING"},
            "runtime_status": {
                "status": "failed",
                "latest_run_status": "FAILURE",
                "failed_or_incomplete_steps": {"meltano_slack_live_raw_landing": "FAILURE"},
            },
        }
    )

    assert report["status"] == "failed"
    runtime_status = report["runtime_status"]
    assert isinstance(runtime_status, dict)
    assert runtime_status["failed_or_incomplete_steps"] == {
        "meltano_slack_live_raw_landing": "FAILURE"
    }


def test_stage1_acceptance_cli_prints_json_and_exits_nonzero_on_failed_gate(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps(
            [
                {
                    "id": "missing-live-case",
                    "query": "not present",
                    "expected_source_ref_prefix": "missing:source",
                    "expected_source_system": "missing",
                    "expected_record_type": "document",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "stage1-acceptance",
            "--json",
            "--state",
            str(tmp_path / "state.sqlite"),
            "--cases",
            str(cases),
            "--report",
            str(tmp_path / "report.md"),
            "--skip-dagster",
            "--skip-grafana",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        main()

    assert exc.value.code == 1
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"
    assert output["checks"]["retrieval"] == "needs_review"
    assert output["checks"]["permission"] == "skipped"
    assert output["checks"]["dagster"] == "skipped"
    assert output["checks"]["grafana"] == "skipped"
