import json
from datetime import datetime
from pathlib import Path

from fourok.cli import main
from fourok.etl.extract.sync_jobs import (
    complete_connector_job,
    connector_job_runs,
    start_connector_job,
)
from fourok.governance.state import create_governed_context_state


def test_cli_run_live_ingestion_runs_selected_live_backfill_and_records_status(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FOUROK_DATABASE_URL", "sqlite:///:memory:")
    state_path = tmp_path / "state.sqlite"
    artifact_dir = tmp_path / "live-artifacts"
    calls: list[list[str]] = []

    def fake_runner(command, **_kwargs):
        calls.append(list(command))

        class Completed:
            returncode = 0
            stdout = "\n".join(
                [
                    "asset_count=24",
                    "meltano_slack_live_raw_landing",
                    "fourok_slack_live_source_records_from_raw_landing",
                    "live_connector_materialize_status=ok",
                ]
            )
            stderr = ""

        return Completed()

    monkeypatch.setattr("fourok.runtime.recurring_live_ingestion.subprocess.run", fake_runner)
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-live-ingestion",
            "--source",
            "slack",
            "--state",
            str(state_path),
            "--artifact-dir",
            str(artifact_dir),
            "--now",
            "2026-06-01T10:00:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert output["sources"] == [
        {
            "source": "slack",
            "connector_name": "slack-live",
            "status": "succeeded",
            "job_id": output["sources"][0]["job_id"],
            "artifact_dir": str(artifact_dir / "slack"),
            "record_count": None,
            "source_record_count": None,
            "retrieval_record_count": None,
        }
    ]
    assert calls == [
        [
            "uv",
            "run",
            "--group",
            "pipeline",
            "python",
            "scripts/check_dagster_pipeline.py",
            "--materialize-live-connectors",
            "--live-connector",
            "slack",
            "--artifact-dir",
            str(artifact_dir / "slack"),
        ]
    ]

    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    jobs = connector_job_runs(state.engine, state.connector_job_runs)
    assert len(jobs) == 1
    assert jobs[0]["connector_name"] == "slack-live"
    assert jobs[0]["status"] == "succeeded"
    assert jobs[0]["output_state"]["freshness_status"] == "fresh"
    assert jobs[0]["output_state"]["idempotency_status"] == "recorded"
    assert jobs[0]["raw_output_ref"] == str(artifact_dir / "slack")


def test_cli_run_live_ingestion_without_explicit_state_uses_database_url(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    database_path = tmp_path / "live.sqlite"
    monkeypatch.setenv("FOUROK_DATABASE_URL", f"sqlite:///{database_path}")
    artifact_dir = tmp_path / "live-artifacts"

    class Completed:
        returncode = 0
        stdout = "live_connector_materialize_status=ok"
        stderr = ""

    monkeypatch.setattr(
        "fourok.runtime.recurring_live_ingestion.subprocess.run",
        lambda *_args, **_kwargs: Completed(),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-live-ingestion",
            "--source",
            "slack",
            "--artifact-dir",
            str(artifact_dir),
            "--now",
            "2026-06-01T10:00:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    state = create_governed_context_state(
        state_path=tmp_path / "unused.sqlite",
        database_url=f"sqlite:///{database_path}",
        raw_store_path=None,
    )
    jobs = connector_job_runs(state.engine, state.connector_job_runs)
    assert len(jobs) == 1
    assert jobs[0]["connector_name"] == "slack-live"


def test_cli_run_live_ingestion_rewrites_dotenv_compose_database_url_for_host(
    monkeypatch,
    tmp_path: Path,
) -> None:
    from argparse import Namespace

    from fourok.cli_parts.commands_imports import _database_url_unless_explicit_state

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FOUROK_DATABASE_URL", raising=False)
    (tmp_path / ".env").write_text(
        "FOUROK_DATABASE_URL=postgresql+psycopg://fourok:secret@postgres:5432/fourok\n",
        encoding="utf-8",
    )

    assert _database_url_unless_explicit_state(
        Namespace(database_url=None, state_explicit=False)
    ) == ("postgresql+psycopg://fourok:secret@127.0.0.1:5432/fourok")


def test_cli_run_live_ingestion_skips_source_with_running_job(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FOUROK_DATABASE_URL", "sqlite:///:memory:")
    state_path = tmp_path / "state.sqlite"
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="linear-live",
        job_id="running-live-job",
    )

    monkeypatch.setattr(
        "fourok.runtime.recurring_live_ingestion.subprocess.run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("running connector should not invoke Dagster")
        ),
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-live-ingestion",
            "--source",
            "linear",
            "--state",
            str(state_path),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "skipped",
        "sources": [
            {
                "source": "linear",
                "connector_name": "linear-live",
                "status": "skipped",
                "reason": "connector_job_already_running",
                "running_job_id": "running-live-job",
            }
        ],
    }


def test_cli_live_ingestion_status_reports_source_freshness_and_idempotency(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("FOUROK_DATABASE_URL", "sqlite:///:memory:")
    state_path = tmp_path / "state.sqlite"
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    job = start_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        connector_name="twenty-live",
        job_id="twenty-live-job",
        now=datetime.fromisoformat("2026-06-01T10:00:00+00:00"),
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name="twenty-live",
        output_state={
            "freshness_status": "fresh",
            "idempotency_status": "recorded",
            "source_record_count": 8,
        },
        raw_output_ref=".local/recurring-live-ingestion/twenty",
        now=datetime.fromisoformat("2026-06-01T10:00:30+00:00"),
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "live-ingestion-status",
            "--state",
            str(state_path),
            "--now",
            "2026-06-01T10:30:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "attention_required"
    assert output["sources"]["twenty"] == {
        "connector_name": "twenty-live",
        "latest_status": "succeeded",
        "latest_started_at": "2026-06-01T10:00:00+00:00",
        "latest_finished_at": "2026-06-01T10:00:30+00:00",
        "age_seconds": 1770,
        "freshness_status": "fresh",
        "idempotency_status": "recorded",
        "source_record_count": 8,
        "raw_output_ref": ".local/recurring-live-ingestion/twenty",
        "error": "",
    }
    assert output["sources"]["slack"]["freshness_status"] == "missing"
    assert output["sources"]["linear"]["freshness_status"] == "missing"
    assert output["sources"]["google_drive"]["freshness_status"] == "missing"
