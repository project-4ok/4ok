from pathlib import Path

from gcb.runtime.acceptance import internal_v0_acceptance_proof

FIXTURES = Path(__file__).parents[2] / "fixtures" / "context_substrate"


def test_internal_v0_acceptance_proof_covers_runtime_loop_without_raw_bodies(
    tmp_path: Path,
) -> None:
    config = tmp_path / "gcb.toml"
    raw_store = tmp_path / "raw-source-objects"
    config.write_text(
        "\n".join(
            [
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{raw_store}"',
                "",
                "[retention]",
                "raw_source_days = 7",
                "audit_event_days = 365",
                "backup_days = 14",
                "webhook_backlog_days = 30",
                "",
                "[backup]",
                f'path = "{tmp_path / "backups"}"',
                "",
                "[retrieval]",
                "max_words = 900",
                "overlap_words = 100",
            ]
        ),
        encoding="utf-8",
    )

    proof = internal_v0_acceptance_proof(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        config_path=config,
        fixture_path=FIXTURES / "source_snapshot_eval.json",
        query="Robin Scharf",
        backup_database_url="postgresql://gcb:secret@example.internal:5432/gcb",
        backup_output=tmp_path / "backups" / "gcb.dump",
        observability_smoke=lambda: {
            "status": "ok",
            "service_name": "gcb-test",
            "exporter": "console",
            "sensitive_payload_exported": False,
        },
        access_smoke=lambda: {
            "status": "ok",
            "exposures": [],
            "violations": [],
            "skipped_services": [],
        },
    )

    assert proof["status"] == "ok"
    assert proof["alerts"] == {"status": "ok", "items": []}
    assert proof["checks"] == {
        "config": "ok",
        "health": "ok",
        "import": "ok",
        "dashboard": "ok",
        "search": "ok",
        "audit": "ok",
        "webhook": "ok",
        "lifecycle": "ok",
        "retention": "ok",
        "rebuild": "ok",
        "access": "ok",
        "observability": "ok",
        "backup_command": "ok",
        "restore_command": "ok",
    }
    assert proof["config"] == {
        "loaded": True,
        "raw_store_configured": True,
        "retention_configured": True,
        "retrieval": {
            "max_words": 900,
            "overlap_words": 100,
        },
        "scheduler": {
            "import_interval_minutes": 60,
            "retry_interval_minutes": 15,
            "max_attempts": 3,
            "retry_delay_seconds": 300,
        },
        "webhooks": {
            "process_limit": 10,
            "max_attempts": 3,
            "retry_delay_seconds": 60,
        },
        "telemetry": {
            "enabled": False,
            "endpoint": "http://localhost:4318",
            "service_name": "gcb-app",
        },
        "connectors": {
            "enabled": [],
            "source_limit": None,
        },
    }
    assert proof["import"]["record_count"] == 20
    assert proof["import"]["raw_source_count"] == 20
    assert proof["dashboard"]["source_records"] == 21
    assert proof["dashboard"]["connector_jobs_by_status"] == {"succeeded": 1}
    assert proof["dashboard"]["webhook_backlog_by_status"] == {"succeeded": 1}
    assert proof["dashboard"]["alert_status"] == "ok"
    assert proof["dashboard"]["alert_count"] == 0
    assert proof["search"]["result_count"] == 1
    assert proof["search"]["evidence_item_count"] == 1
    assert proof["search"]["has_audit_ref"] is True
    assert proof["webhook"] == {
        "event_id": "acceptance-webhook-1",
        "process": {"claimed": 1, "succeeded": 1, "failed": 0, "invalid": 0},
        "raw_payload_landed": True,
        "search_result_count": 1,
        "status_by_event_id": {"acceptance-webhook-1": "succeeded"},
    }
    assert proof["lifecycle"] == {
        "source_ref": "acceptance:lifecycle:1",
        "raw_payload_landed": True,
        "restricted_hidden": True,
        "restored_searchable": True,
        "deleted_hidden": True,
        "raw_removed_after_delete": True,
        "final_lifecycle_state": "deleted",
        "final_retrieval_status": "inactive",
    }
    assert proof["audit"]["search_events"] == 2
    assert proof["audit"]["source_access_events"] == 2
    assert proof["retention"]["surfaces"]["raw_sources"]["status"] == "configured"
    assert proof["retention"]["surfaces"]["audit_events"]["status"] == "configured"
    assert proof["retention"]["surfaces"]["backups"]["status"] == "configured"
    assert proof["retention"]["surfaces"]["webhook_backlog"]["status"] == "configured"
    assert proof["rebuild"]["retrieval_units_deleted"] > 0
    assert proof["rebuild"]["retrieval_units_created"] > 0
    assert proof["access"] == {
        "status": "ok",
        "exposures": [],
        "violations": [],
        "skipped_services": [],
    }
    assert proof["observability"]["sensitive_payload_exported"] is False
    assert proof["backup_command"]["program"] == "pg_dump"
    assert proof["backup_command"]["has_password_in_command"] is False
    assert proof["restore_command"]["program"] == "pg_restore"
    assert proof["restore_command"]["destructive_confirmation_required"] is True
    assert proof["restore_command"]["has_password_in_command"] is False
    assert "secret" not in str(proof)
    assert "Please ask Robin" not in str(proof)


def test_internal_v0_acceptance_proof_surfaces_operational_alerts(
    tmp_path: Path,
) -> None:
    config = tmp_path / "gcb.toml"
    raw_store = tmp_path / "raw-source-objects"
    config.write_text(
        "\n".join(
            [
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{raw_store}"',
                "",
                "[retention]",
                "raw_source_days = 7",
                "audit_event_days = 365",
                "backup_days = 14",
                "webhook_backlog_days = 30",
            ]
        ),
        encoding="utf-8",
    )

    proof = internal_v0_acceptance_proof(
        state_path=tmp_path / "state.sqlite",
        database_url=None,
        config_path=config,
        fixture_path=FIXTURES / "source_snapshot_eval.json",
        query="Robin Scharf",
        backup_database_url=None,
        backup_output=tmp_path / "backups" / "gcb.dump",
        observability_smoke=lambda: {
            "status": "failed",
            "reason": "collector_unreachable",
        },
        access_smoke=lambda: {
            "status": "failed",
            "violations": [
                {
                    "service": "app",
                    "host_ip": "0.0.0.0",
                    "published": "8080",
                    "target": "8080",
                    "protocol": "tcp",
                    "reason": "broad_host_binding",
                }
            ],
        },
    )

    assert proof["status"] == "failed"
    assert proof["checks"]["observability"] == "failed"
    assert proof["checks"]["access"] == "failed"
    assert proof["checks"]["backup_command"] == "failed"
    assert proof["checks"]["restore_command"] == "failed"
    assert proof["alerts"] == {
        "status": "needs_attention",
        "items": [
            {
                "code": "access_boundary_failed",
                "severity": "warning",
                "threshold": "check status != ok",
                "message": "Docker Compose internal access-boundary smoke check failed.",
                "next_step": (
                    "Run `gcb access-smoke --compose-file docker-compose.yml` and fix "
                    "unintended exposed services."
                ),
            },
            {
                "code": "observability_failed",
                "severity": "warning",
                "threshold": "check status != ok",
                "message": "OpenTelemetry smoke/export check failed.",
                "next_step": (
                    "Run `gcb observability-smoke` with the local observability profile "
                    "enabled and inspect exporter configuration."
                ),
            },
            {
                "code": "backup_command_failed",
                "severity": "warning",
                "threshold": "check status != ok",
                "message": "PostgreSQL backup command wiring failed.",
                "next_step": (
                    "Run `gcb postgres-backup` with the configured backup database URL "
                    "and verify the output path."
                ),
            },
            {
                "code": "restore_command_failed",
                "severity": "warning",
                "threshold": "check status != ok",
                "message": "PostgreSQL restore-drill command wiring failed.",
                "next_step": (
                    "Run `gcb postgres-restore-drill` against a separate drill database "
                    "and inspect the command report."
                ),
            },
        ],
    }
