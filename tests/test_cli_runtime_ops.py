import json
import os
from datetime import UTC, datetime
from pathlib import Path

from gcb.cli import main
from gcb.etl.extract.email_parser import load_email_dir
from gcb.governance import GovernedContext
from gcb.governance.policy import PrincipalContext
from gcb.governance.state import create_governed_context_state
from gcb.runtime.webhooks import (
    WebhookEventInput,
    enqueue_webhook_event,
    process_pending_webhook_events,
)

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


def test_cli_context_fixture_import_reports_day2_counts(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"
    changed_fixture = tmp_path / "source_snapshot_changed.json"
    changed_data = json.loads(fixture.read_text(encoding="utf-8"))
    changed_data["linear_issues"][0]["description"] = "Changed renewal meeting text."
    changed_fixture.write_text(json.dumps(changed_data), encoding="utf-8")

    for import_path in [fixture, fixture, changed_fixture]:
        monkeypatch.setattr(
            "sys.argv",
            [
                "gcb",
                "import-context-fixture",
                "--fixture",
                str(import_path),
                "--state",
                str(state),
            ],
        )
        main()
        output = json.loads(capsys.readouterr().out)

    assert output["record_count"] == 20
    assert output["new_count"] == 0
    assert output["unchanged_count"] == 19
    assert output["changed_count"] == 1
    assert output["deleted_count"] == 0
    assert output["restricted_count"] == 0


def test_cli_context_fixture_import_marks_missing_snapshot_records_deleted(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    fixture = CONTEXT_FIXTURES / "source_snapshot_eval.json"
    removed_fixture = tmp_path / "source_snapshot_removed.json"
    removed_data = json.loads(fixture.read_text(encoding="utf-8"))
    removed_data["linear_issues"] = [
        issue for issue in removed_data["linear_issues"] if issue["identifier"] != "JKL-101"
    ]
    removed_fixture.write_text(json.dumps(removed_data), encoding="utf-8")

    for import_path in [fixture, removed_fixture]:
        monkeypatch.setattr(
            "sys.argv",
            [
                "gcb",
                "import-context-fixture",
                "--fixture",
                str(import_path),
                "--state",
                str(state),
            ],
        )
        main()
        output = json.loads(capsys.readouterr().out)

    context = GovernedContext(state)
    deleted_record = next(
        record
        for record in context.source_records()
        if record["source_ref"] == "linear:issue:JKL-101"
    )
    assert output["record_count"] == 19
    assert output["deleted_count"] == 1
    assert deleted_record["lifecycle_state"] == "deleted"
    assert context.source_lifecycle() == [
        {
            "source_ref": "linear:issue:JKL-101",
            "state": "deleted",
            "reason": "missing_from_latest_snapshot",
        }
    ]

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "search-state",
            "superseded duplicate repeated source records cleanup",
            "--state",
            str(state),
            "--role",
            "linear:team:ops",
        ],
    )
    main()
    search_output = json.loads(capsys.readouterr().out)
    assert "linear:issue:JKL-101" not in {
        result["source_ref"] for result in search_output["results"]
    }


def test_cli_prints_runtime_service_boundaries(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["gcb", "runtime-services"])

    main()

    output = json.loads(capsys.readouterr().out)
    services = {service["name"]: service for service in output["services"]}
    assert "connector-runner" in services
    assert services["connector-runner"]["current_runtime"] == "manual command"
    assert "production broker decision" in services["connector-runner"]["not_yet"]
    assert "webhook-backlog" in services
    assert services["context-api"]["health_check"] == "gcb health"


def test_cli_runtime_monitor_emits_bounded_health_report(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    calls: list[object] = []

    def fake_create_state(**kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(
        "gcb.cli_parts.commands_runtime.create_governed_context_state",
        fake_create_state,
    )
    monkeypatch.setattr(
        "gcb.cli_parts.commands_runtime.check_runtime_health",
        lambda _state: {"status": "ok", "checks": []},
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "runtime-monitor",
            "--state",
            str(state),
            "--max-checks",
            "1",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ok"
    assert output["health"] == {"status": "ok", "checks": []}
    assert output["checked_at"]
    assert calls[0]["state_path"] == state


def test_cli_prints_dependency_contract_spikes(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["gcb", "dependency-contracts"])

    main()

    output = json.loads(capsys.readouterr().out)
    contracts = {contract["name"]: contract for contract in output["contracts"]}

    assert output["status"] == "ok"
    assert output["summary"]["missing_dimension_count"] == 0
    assert output["summary"]["unproved_count"] == 0
    assert "infisical-sdk" in contracts
    assert "singer-meltano-style-connectors" in contracts
    assert contracts["docker-compose-runtime"]["proof_commands"]


def test_cli_prints_internal_prod_readiness(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["gcb", "internal-prod-readiness"])

    main()

    output = json.loads(capsys.readouterr().out)
    checks = {check["name"]: check for check in output["checks"]}

    assert output["status"] == "ok"
    assert output["summary"]["failed"] == 0
    assert checks["pinned_images"]["status"] == "ok"
    assert checks["access_boundary"]["status"] == "ok"


def test_cli_source_command_is_not_active(monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["gcb", "source", "singer:email_messages:msg-001"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("inactive source command should fail argument parsing")


def test_cli_purges_expired_restricted_raw_sources(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    source_ref = "local_email:0013-refund-iban"
    context = GovernedContext(state, raw_store_path=raw_store)
    context.ingest(load_email_dir(FIXTURES))
    context.restrict_source(source_ref, reason="source_permission_revoked")

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "purge-raw-retention",
            "--state",
            str(state),
            "--raw-store",
            str(raw_store),
            "--retention-days",
            "0",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"purged_source_refs": [source_ref]}


def test_cli_purges_raw_sources_with_configured_retention(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    config = tmp_path / "gcb.toml"
    source_ref = "local_email:0013-refund-iban"
    context = GovernedContext(state, raw_store_path=raw_store)
    context.ingest(load_email_dir(FIXTURES))
    context.restrict_source(source_ref, reason="source_permission_revoked")
    config.write_text("[retention]\nraw_source_days = 0\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "purge-raw-retention",
            "--state",
            str(state),
            "--raw-store",
            str(raw_store),
            "--config",
            str(config),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"purged_source_refs": [source_ref]}


def test_cli_purges_raw_sources_with_configured_raw_store(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    config = tmp_path / "gcb.toml"
    source_ref = "local_email:0013-refund-iban"
    context = GovernedContext(state, raw_store_path=raw_store)
    context.ingest(load_email_dir(FIXTURES))
    context.restrict_source(source_ref, reason="source_permission_revoked")
    config.write_text(
        "\n".join(
            [
                "[retention]",
                "raw_source_days = 0",
                "",
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{raw_store}"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "purge-raw-retention",
            "--state",
            str(state),
            "--config",
            str(config),
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"purged_source_refs": [source_ref]}


def test_cli_purges_expired_audit_events_with_configured_retention(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state = tmp_path / "state.sqlite"
    config = tmp_path / "gcb.toml"
    context = GovernedContext(state)
    context._record_audit(
        "search",
        {
            "query": "old audit",
            "recorded_at": "2026-05-01T00:00:00+00:00",
        },
    )
    context._record_audit(
        "search",
        {
            "query": "recent audit",
            "recorded_at": "2026-05-23T00:00:00+00:00",
        },
    )
    config.write_text("[retention]\naudit_event_days = 7\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "purge-audit-retention",
            "--state",
            str(state),
            "--config",
            str(config),
            "--now",
            "2026-05-24T00:00:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {"purged_audit_events": 1}
    assert [event["query"] for event in context.audit_events()] == ["recent audit"]


def test_cli_retention_status_reports_policy_and_eligible_counts(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    raw_store = tmp_path / "raw-source-objects"
    backup_store = tmp_path / "backups"
    backup_store.mkdir()
    expired_backup = backup_store / "old.dump"
    retained_backup = backup_store / "new.dump"
    ignored_file = backup_store / "notes.txt"
    expired_backup.write_text("expired", encoding="utf-8")
    retained_backup.write_text("retained", encoding="utf-8")
    ignored_file.write_text("ignored", encoding="utf-8")
    os.utime(expired_backup, (datetime(2026, 5, 10, tzinfo=UTC).timestamp(),) * 2)
    os.utime(retained_backup, (datetime(2026, 5, 23, tzinfo=UTC).timestamp(),) * 2)
    config = tmp_path / "gcb.toml"
    source_ref = "local_email:0013-refund-iban"
    context = GovernedContext(state_path, raw_store_path=raw_store)
    context.ingest(load_email_dir(FIXTURES))
    context.restrict_source(source_ref, reason="source_permission_revoked")
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=raw_store,
    )
    with state.engine.begin() as connection:
        connection.execute(
            state.source_lifecycle.update()
            .where(state.source_lifecycle.c.source_ref == source_ref)
            .values(recorded_at="2026-05-01T00:00:00+00:00")
        )
    context._record_audit(
        "search",
        {
            "query": "old audit",
            "recorded_at": "2026-05-01T00:00:00+00:00",
        },
    )
    context._record_audit(
        "search",
        {
            "query": "recent audit",
            "recorded_at": "2026-05-23T00:00:00+00:00",
        },
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-expired",
            source_system="linear",
            event_type="issue.updated",
            operation="upsert",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:old",
                    "source_system": "linear",
                    "source_id": "old",
                    "record_type": "work_item",
                    "title": "Old webhook",
                }
            },
        ),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-retained",
            source_system="linear",
            event_type="issue.updated",
            operation="upsert",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:new",
                    "source_system": "linear",
                    "source_id": "new",
                    "record_type": "work_item",
                    "title": "New webhook",
                }
            },
        ),
        now=datetime(2026, 5, 23, tzinfo=UTC),
    )
    process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 5, 10, 1, tzinfo=UTC),
        limit=1,
    )
    process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 5, 23, 1, tzinfo=UTC),
        limit=1,
    )
    config.write_text(
        "\n".join(
            [
                "[retention]",
                "raw_source_days = 7",
                "audit_event_days = 7",
                "backup_days = 7",
                "webhook_backlog_days = 7",
                "",
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{raw_store}"',
                "",
                "[backup]",
                f'path = "{backup_store}"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "retention-status",
            "--state",
            str(state_path),
            "--config",
            str(config),
            "--now",
            "2026-05-24T00:00:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output["policy"] == {
        "raw_source_days": 7,
        "audit_event_days": 7,
        "backup_days": 7,
        "webhook_backlog_days": 7,
    }
    assert output["surfaces"]["raw_sources"] == {
        "status": "configured",
        "retention_days": 7,
        "eligible_for_deletion": 1,
        "delete_command": "purge-raw-retention",
        "scope": "restricted raw source objects only",
    }
    assert output["surfaces"]["audit_events"] == {
        "status": "configured",
        "retention_days": 7,
        "eligible_for_deletion": 1,
        "delete_command": "purge-audit-retention",
        "scope": "audit events older than the retention window",
    }
    assert output["surfaces"]["source_records"] == {
        "status": "configured",
        "retention_days": None,
        "total": 16,
        "by_lifecycle_state": {
            "active": 15,
            "restricted": 1,
        },
        "delete_command": None,
        "scope": "source records are retained or hidden through source lifecycle changes",
    }
    assert output["surfaces"]["retrieval_units"] == {
        "status": "configured",
        "retention_days": None,
        "total": 16,
        "by_status": {
            "current": 15,
            "inactive": 1,
        },
        "delete_command": None,
        "scope": "retrieval units are derived from source records and rebuilt or marked inactive",
    }
    assert output["surfaces"]["webhook_backlog"] == {
        "status": "configured",
        "retention_days": 7,
        "total": 2,
        "eligible_for_deletion": 1,
        "delete_command": "purge-webhook-retention",
        "scope": "terminal webhook events older than the retention window",
    }
    assert output["surfaces"]["telemetry"]["status"] == "external"
    assert output["surfaces"]["backups"] == {
        "status": "configured",
        "retention_days": 7,
        "total": 2,
        "eligible_for_deletion": 1,
        "delete_command": "purge-backup-retention",
        "path": str(backup_store),
        "scope": "PostgreSQL dump files older than the retention window",
    }


def test_cli_purge_backup_retention_deletes_only_expired_dumps(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    backup_store = tmp_path / "backups"
    backup_store.mkdir()
    expired_backup = backup_store / "old.dump"
    retained_backup = backup_store / "new.dump"
    ignored_file = backup_store / "notes.txt"
    expired_backup.write_text("expired", encoding="utf-8")
    retained_backup.write_text("retained", encoding="utf-8")
    ignored_file.write_text("ignored", encoding="utf-8")
    os.utime(expired_backup, (datetime(2026, 5, 10, tzinfo=UTC).timestamp(),) * 2)
    os.utime(retained_backup, (datetime(2026, 5, 23, tzinfo=UTC).timestamp(),) * 2)
    config = tmp_path / "gcb.toml"
    config.write_text(
        "\n".join(
            [
                "[retention]",
                "backup_days = 7",
                "",
                "[backup]",
                f'path = "{backup_store}"',
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "purge-backup-retention",
            "--config",
            str(config),
            "--now",
            "2026-05-24T00:00:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "purged_backup_files": [str(expired_backup)],
        "purged_count": 1,
    }
    assert not expired_backup.exists()
    assert retained_backup.exists()
    assert ignored_file.exists()


def test_cli_purge_webhook_retention_deletes_only_terminal_expired_rows(
    capsys, monkeypatch, tmp_path: Path
) -> None:
    state_path = tmp_path / "state.sqlite"
    state = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    context = GovernedContext(state_path)
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-expired",
            source_system="linear",
            event_type="issue.updated",
            operation="upsert",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:old",
                    "source_system": "linear",
                    "source_id": "old",
                    "record_type": "work_item",
                    "title": "Old webhook",
                }
            },
        ),
        now=datetime(2026, 5, 10, tzinfo=UTC),
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-retained",
            source_system="linear",
            event_type="issue.updated",
            operation="upsert",
            payload={
                "source_record": {
                    "source_ref": "linear:issue:new",
                    "source_system": "linear",
                    "source_id": "new",
                    "record_type": "work_item",
                    "title": "New webhook",
                }
            },
        ),
        now=datetime(2026, 5, 23, tzinfo=UTC),
    )
    process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 5, 10, 1, tzinfo=UTC),
        limit=1,
    )
    process_pending_webhook_events(
        state,
        context,
        now=datetime(2026, 5, 23, 1, tzinfo=UTC),
        limit=1,
    )
    enqueue_webhook_event(
        state,
        WebhookEventInput(
            event_id="evt-pending",
            source_system="linear",
            event_type="issue.updated",
            operation="delete",
            payload={"source_ref": "linear:issue:pending"},
        ),
        now=datetime(2026, 5, 24, tzinfo=UTC),
    )
    config = tmp_path / "gcb.toml"
    config.write_text("[retention]\nwebhook_backlog_days = 7\n", encoding="utf-8")

    monkeypatch.setattr(
        "sys.argv",
        [
            "gcb",
            "purge-webhook-retention",
            "--state",
            str(state_path),
            "--config",
            str(config),
            "--now",
            "2026-05-24T00:00:00+00:00",
        ],
    )

    main()

    output = json.loads(capsys.readouterr().out)
    assert output == {
        "purged_webhook_events": 1,
        "retained_pending_events": True,
    }
    remaining = create_governed_context_state(
        state_path=state_path,
        database_url=None,
        raw_store_path=None,
    )
    assert {
        row["event_id"]
        for row in remaining.engine.connect().execute(remaining.webhook_events.select()).mappings()
    } == {"evt-retained", "evt-pending"}


def test_cli_audit_summary_prints_operator_counts(capsys, monkeypatch, tmp_path: Path) -> None:
    state = tmp_path / "state.sqlite"
    context = GovernedContext(state)
    principal = PrincipalContext(
        human_id="human:finance-1",
        agent_id="agent:context-helper",
    )
    context._record_audit(
        "search",
        {
            "principal": principal,
            "result_count": 2,
        },
    )
    context._record_audit(
        "reveal",
        {
            "principal": principal,
            "decision": "allowed",
            "token": "BANK_ACCOUNT_ABC",
        },
    )

    monkeypatch.setattr("sys.argv", ["gcb", "audit-summary", "--state", str(state)])

    main()

    assert json.loads(capsys.readouterr().out) == {
        "total_events": 2,
        "event_types": {"reveal": 1, "search": 1},
        "decisions": {"allowed": 1},
        "humans": {"human:finance-1": 2},
    }
