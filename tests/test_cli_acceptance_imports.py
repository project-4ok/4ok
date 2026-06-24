import json
from datetime import datetime
from pathlib import Path

from fourok.cli import main
from fourok.etl.extract.source_records import SourceRecord
from fourok.etl.extract.sync_jobs import (
    complete_connector_job,
    start_connector_job,
)
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state

FIXTURES = Path(__file__).parent.parent / "fixtures" / "emails"
CONNECTOR_FIXTURES = Path(__file__).parent.parent / "fixtures" / "connectors"
CONTEXT_FIXTURES = Path(__file__).parent.parent / "fixtures" / "context_substrate"


def _source_record_legacy_fields(row: dict[str, object]) -> dict[str, object]:
    keys = [
        "source_ref",
        "source_system",
        "source_id",
        "record_type",
        "source_url",
        "thread_ref",
        "permission_refs",
        "permission_snapshot_status",
        "attachment_refs",
        "identity_refs",
        "lifecycle_state",
    ]
    return {key: row[key] for key in keys}


def test_cli_health_reports_database_and_record_readiness(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    context.ingest_source_records(
        [
            SourceRecord(
                source_ref="slack:message:cli-health",
                source_system="slack",
                source_id="cli-health",
                record_type="message",
                title="CLI health",
                body="Health should report records.",
                occurred_at="2026-06-15T12:00:00+00:00",
            )
        ]
    )
    context.build_vector_index()

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "health",
            "--state",
            str(state),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert [check["name"] for check in output["checks"]] == [
        "database",
        "source_records",
        "retrieval_records",
    ]
    assert output["checks"][0]["dialect"] == "sqlite"
    assert output["checks"][1]["count"] == 1
    assert output["checks"][2]["count"] == 1


def test_cli_observability_smoke_exports_safe_local_trace(capsys, monkeypatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "observability-smoke",
            "--endpoint",
            "console",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "ok",
        "service_name": "fourok-local-smoke",
        "exporter": "console",
        "sensitive_payload_exported": False,
    }


def test_cli_uses_enabled_telemetry_config_for_runtime_command(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state = tmp_path / "state.sqlite"
    config = tmp_path / "fourok.toml"
    config.write_text(
        "\n".join(
            [
                "[telemetry]",
                "enabled = true",
                'endpoint = "console"',
                'service_name = "fourok-configured"',
            ]
        ),
        encoding="utf-8",
    )
    configured = {}

    def fake_configure_observability(*, service_name: str, endpoint: str):
        configured["service_name"] = service_name
        configured["endpoint"] = endpoint
        return object()

    monkeypatch.setattr(
        "fourok.cli_parts.runtime_helpers.configure_observability",
        fake_configure_observability,
    )
    monkeypatch.setattr(
        "fourok.cli_parts.runtime_helpers.configure_observability_from_env",
        lambda: (_ for _ in ()).throw(AssertionError("env telemetry should not be used")),
    )
    monkeypatch.setattr(
        "sys.argv",
        ["fourok", "dashboard", "--state", str(state), "--config", str(config)],
    )

    main()

    assert "source_records" in json.loads(capsys.readouterr().out)
    assert configured == {"service_name": "fourok-configured", "endpoint": "console"}


def test_cli_acceptance_proof_prints_sanitized_runtime_report(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    config = tmp_path / "fourok.toml"
    config.write_text(
        "\n".join(
            [
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{tmp_path / "raw-source-objects"}"',
                "",
                "[retention]",
                "raw_source_days = 7",
                "audit_event_days = 365",
                "backup_days = 14",
                "webhook_backlog_days = 30",
                "",
                "[backup]",
                f'path = "{tmp_path / "backups"}"',
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.emit_observability_smoke",
        lambda service_name, endpoint: {
            "status": "ok",
            "service_name": service_name,
            "exporter": endpoint,
            "sensitive_payload_exported": False,
        },
    )
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.check_compose_access_boundary",
        lambda compose_file: {
            "status": "ok",
            "compose_file": str(compose_file),
            "exposures": [],
            "violations": [],
            "skipped_services": [],
        },
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "acceptance-proof",
            "--state",
            str(tmp_path / "state.sqlite"),
            "--config",
            str(config),
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--query",
            "Robin Scharf sales employee",
            "--backup-database-url",
            "postgresql://fourok:secret@example.internal:5432/fourok",
            "--backup-output",
            str(tmp_path / "backups" / "fourok.dump"),
            "--observability-endpoint",
            "console",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["alerts"] == {"status": "ok", "items": []}
    assert output["checks"]["search"] == "ok"
    assert output["checks"]["retention"] == "ok"
    assert output["checks"]["rebuild"] == "ok"
    assert output["checks"]["access"] == "ok"
    assert output["checks"]["backup_command"] == "ok"
    assert output["backup_command"]["has_password_in_command"] is False
    assert "secret" not in str(output)
    assert "Please ask Robin" not in str(output)


def test_cli_acceptance_proof_exits_nonzero_when_proof_fails(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        "fourok.cli_parts.commands_runtime.internal_v0_acceptance_proof",
        lambda **_kwargs: {"status": "failed", "checks": {"search": "failed"}},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "acceptance-proof",
            "--state",
            str(tmp_path / "state.sqlite"),
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--backup-database-url",
            "postgresql://fourok:secret@example.internal:5432/fourok",
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 1
    else:
        raise AssertionError("failed acceptance proof should exit nonzero")

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "failed"


def test_cli_backs_up_and_restores_local_sqlite_state(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    backup = tmp_path / "nested" / "backups" / "state.sqlite"
    restored_state = tmp_path / "restored" / "state.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "search",
            "refund iban canceled account",
            "--emails",
            str(FIXTURES),
            "--state",
            str(state),
            "--limit",
            "3",
        ],
    )
    main()
    capsys.readouterr()

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "backup-state",
            "--state",
            str(state),
            "--output",
            str(backup),
        ],
    )
    main()
    backup_output = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "restore-state",
            "--state",
            str(restored_state),
            "--input",
            str(backup),
        ],
    )
    main()
    restore_output = json.loads(capsys.readouterr().out)

    monkeypatch.setattr("sys.argv", ["fourok", "audit", "--state", str(restored_state)])
    main()
    audit_output = json.loads(capsys.readouterr().out)

    assert backup_output == {"state": str(state), "backup": str(backup)}
    assert restore_output == {"state": str(restored_state), "backup": str(backup)}
    assert backup.exists()
    assert restored_state.exists()
    assert [event["event_type"] for event in audit_output["events"]] == [
        "search",
        "source_access",
    ]


def test_cli_postgres_backup_and_restore_use_explicit_commands(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_backup_postgres(*, database_url, output):
        captured["backup"] = {"database_url": database_url, "output": output}

    def fake_restore_postgres(*, database_url, input_path, confirm_destructive_restore):
        captured["restore"] = {
            "database_url": database_url,
            "input_path": input_path,
            "confirm_destructive_restore": confirm_destructive_restore,
        }

    monkeypatch.setattr("fourok.cli_parts.commands_backup.backup_postgres", fake_backup_postgres)
    monkeypatch.setattr("fourok.cli_parts.commands_backup.restore_postgres", fake_restore_postgres)
    backup = tmp_path / "fourok.dump"

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "postgres-backup",
            "--database-url",
            "postgresql://fourok:secret@localhost:5432/fourok",
            "--output",
            str(backup),
        ],
    )
    main()
    backup_output = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "postgres-restore",
            "--database-url",
            "postgresql://fourok:secret@localhost:5432/fourok_restored",
            "--input",
            str(backup),
            "--confirm-destructive-restore",
        ],
    )
    main()
    restore_output = json.loads(capsys.readouterr().out)

    assert captured["backup"] == {
        "database_url": "postgresql://fourok:secret@localhost:5432/fourok",
        "output": backup,
    }
    assert captured["restore"] == {
        "database_url": "postgresql://fourok:secret@localhost:5432/fourok_restored",
        "input_path": backup,
        "confirm_destructive_restore": True,
    }
    assert backup_output == {"backup": str(backup), "status": "completed"}
    assert restore_output == {"input": str(backup), "status": "completed"}


def test_cli_postgres_restore_drill_runs_non_destructive_drill(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def fake_restore_drill_postgres(*, database_url, restore_database_url, backup_output):
        captured["drill"] = {
            "database_url": database_url,
            "restore_database_url": restore_database_url,
            "backup_output": backup_output,
        }
        return {
            "status": "completed",
            "backup": str(backup_output),
            "restore_database": "postgresql://fourok@localhost:5432/fourok_restore_drill",
            "health": {"status": "ok"},
        }

    monkeypatch.setattr(
        "fourok.cli_parts.commands_backup.postgres_restore_drill",
        fake_restore_drill_postgres,
    )
    backup = tmp_path / "fourok.dump"

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "postgres-restore-drill",
            "--database-url",
            "postgresql://fourok:secret@localhost:5432/fourok",
            "--restore-database-url",
            "postgresql://fourok:restore@localhost:5432/fourok_restore_drill",
            "--backup-output",
            str(backup),
        ],
    )
    main()
    output = json.loads(capsys.readouterr().out)

    assert captured["drill"] == {
        "database_url": "postgresql://fourok:secret@localhost:5432/fourok",
        "restore_database_url": "postgresql://fourok:restore@localhost:5432/fourok_restore_drill",
        "backup_output": backup,
    }
    assert output == {
        "status": "completed",
        "backup": str(backup),
        "restore_database": "postgresql://fourok@localhost:5432/fourok_restore_drill",
        "health": {"status": "ok"},
    }


def test_cli_ask_prints_workflow_response(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "ask",
            "refund iban canceled account",
            "--emails",
            str(FIXTURES),
            "--state",
            str(state),
            "--limit",
            "3",
            "--human-id",
            "human:finance-1",
            "--agent-id",
            "agent:context-helper",
            "--role",
            "finance",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["query"] == "refund iban canceled account"
    assert output["summary"] == "Found 3 governed evidence items for human review."
    assert any(item["source_ref"] == "local_email:0013-refund-iban" for item in output["evidence"])
    assert "BANK_ACCOUNT_" not in str(output)
    assert "sensitive_tokens" not in output


def test_cli_prints_connector_checkpoint(capsys, monkeypatch, tmp_path: Path) -> None:
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
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "msg-2"},
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "connector-checkpoint",
            "gmail-pilot",
            "--state",
            str(state_path),
        ],
    )
    main()

    assert json.loads(capsys.readouterr().out) == {
        "connector_name": "gmail-pilot",
        "checkpoint": {"bookmark": "msg-2"},
    }


def test_cli_prints_connector_job_runs(capsys, monkeypatch, tmp_path: Path) -> None:
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
        connector_name="gmail-pilot",
        job_id="job-1",
    )
    complete_connector_job(
        state.engine,
        job_runs=state.connector_job_runs,
        connector_states=state.connector_states,
        job_id=job.job_id,
        connector_name="gmail-pilot",
        output_state={"bookmark": "msg-2"},
        raw_output_ref=".local/gmail-pilot/tap-gmail-output.jsonl",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "connector-jobs",
            "--state",
            str(state_path),
            "--connector-name",
            "gmail-pilot",
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["connector_name"] == "gmail-pilot"
    assert len(output["jobs"]) == 1
    job_output = output["jobs"][0]
    assert job_output["started_at"]
    assert job_output["finished_at"]
    assert datetime.fromisoformat(job_output["started_at"])
    assert datetime.fromisoformat(job_output["finished_at"])
    assert {
        key: value for key, value in job_output.items() if key not in {"started_at", "finished_at"}
    } == {
        "job_id": "job-1",
        "connector_name": "gmail-pilot",
        "status": "succeeded",
        "attempt": 1,
        "input_state": {},
        "output_state": {"bookmark": "msg-2"},
        "raw_output_ref": ".local/gmail-pilot/tap-gmail-output.jsonl",
        "error": "",
    }


def test_cli_run_imports_imports_context_fixture_and_records_scheduler_job(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(fixture),
            "--state",
            str(state_path),
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "succeeded"
    assert output["connector_name"] == "context-fixture"
    assert output["record_count"] == 20
    assert output["job"]["input_state"] == {}
    assert output["job"]["status"] == "succeeded"
    assert output["job"]["output_state"] == {
        "changed_count": 0,
        "deleted_count": 0,
        "deleted_record_count": 0,
        "new_count": 20,
        "record_count": 20,
        "restricted_count": 0,
        "source_ref_count": 20,
        "unchanged_count": 0,
    }

    context = GovernedContext(state_path)
    assert len(context.source_records()) == 20


def test_cli_run_imports_skips_when_connector_job_is_already_running(
    capsys, monkeypatch, tmp_path: Path
) -> None:
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
        connector_name="context-fixture",
        job_id="running-job",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "status": "skipped",
        "connector_name": "context-fixture",
        "reason": "connector_job_already_running",
        "running_job_id": "running-job",
    }


def test_cli_run_imports_rejects_connector_disabled_by_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        '[connectors]\nenabled = ["gmail-singer"]\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
            "--config",
            str(config_path),
        ],
    )

    try:
        main()
    except SystemExit as exc:
        assert exc.code == "connector context-fixture is not enabled by config"
    else:
        raise AssertionError("disabled connector should not run")


def test_cli_run_imports_applies_configured_source_limit(
    capsys,
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.sqlite"
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        "[connectors]\nsource_limit = 2\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "fourok",
            "run-imports",
            "--connector",
            "context-fixture",
            "--fixture",
            str(CONTEXT_FIXTURES / "source_snapshot_eval.json"),
            "--state",
            str(state_path),
            "--config",
            str(config_path),
        ],
    )
    main()

    output = json.loads(capsys.readouterr().out)
    context = GovernedContext(state_path)
    assert output["status"] == "succeeded"
    assert output["record_count"] == 2
    assert output["job"]["output_state"]["record_count"] == 2
    assert len(context.source_records()) == 2
