from pathlib import Path

import pytest

from fourok.storage.config import (
    BackupConfig,
    ConnectorConfig,
    RawStoreConfig,
    RetentionConfig,
    RetrievalConfig,
    RuntimeConfig,
    SchedulerConfig,
    TelemetryConfig,
    WebhookProcessingConfig,
    load_runtime_config,
)


def test_load_runtime_config_reads_retention_and_raw_store(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    raw_store_path = tmp_path / "raw-source-objects"
    config_path.write_text(
        "\n".join(
            [
                "[retention]",
                "raw_source_days = 7",
                "audit_event_days = 365",
                "backup_days = 14",
                "webhook_backlog_days = 30",
                "",
                "[raw_store]",
                'backend = "filesystem"',
                f'path = "{raw_store_path}"',
                "",
                "[backup]",
                f'path = "{tmp_path / "backups"}"',
                "",
                "[retrieval]",
                "max_words = 42",
                "overlap_words = 7",
                "",
                "[scheduler]",
                "import_interval_minutes = 30",
                "retry_interval_minutes = 5",
                "max_attempts = 4",
                "retry_delay_seconds = 120",
                "",
                "[webhooks]",
                "process_limit = 25",
                "max_attempts = 5",
                "retry_delay_seconds = 90",
                "",
                "[telemetry]",
                "enabled = true",
                'endpoint = "http://otel.example:4318"',
                'service_name = "fourok-internal"',
                "",
                "[connectors]",
                'enabled = ["gmail-singer", "context-fixture"]',
                "source_limit = 250",
            ]
        ),
        encoding="utf-8",
    )

    assert load_runtime_config(config_path) == RuntimeConfig(
        retention=RetentionConfig(
            raw_source_days=7,
            audit_event_days=365,
            backup_days=14,
            webhook_backlog_days=30,
        ),
        raw_store=RawStoreConfig(backend="filesystem", path=raw_store_path),
        backup=BackupConfig(path=tmp_path / "backups"),
        retrieval=RetrievalConfig(max_words=42, overlap_words=7),
        scheduler=SchedulerConfig(
            import_interval_minutes=30,
            retry_interval_minutes=5,
            max_attempts=4,
            retry_delay_seconds=120,
        ),
        webhooks=WebhookProcessingConfig(
            process_limit=25,
            max_attempts=5,
            retry_delay_seconds=90,
        ),
        telemetry=TelemetryConfig(
            enabled=True,
            endpoint="http://otel.example:4318",
            service_name="fourok-internal",
        ),
        connectors=ConnectorConfig(
            enabled=("gmail-singer", "context-fixture"),
            source_limit=250,
        ),
    )


def test_load_runtime_config_resolves_relative_raw_store_path_from_config_file(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config" / "fourok.toml"
    config_path.parent.mkdir()
    config_path.write_text(
        "\n".join(
            [
                "[raw_store]",
                'backend = "filesystem"',
                'path = "raw-source-objects"',
            ]
        ),
        encoding="utf-8",
    )

    assert load_runtime_config(config_path).raw_store.path == (
        config_path.parent / "raw-source-objects"
    )


def test_load_runtime_config_rejects_invalid_raw_store_table(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text('raw_store = "filesystem"\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"\[raw_store\] must be a TOML table"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_audit_retention(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retention]\naudit_event_days = -1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="retention.audit_event_days"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_backup_retention(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retention]\nbackup_days = -1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="retention.backup_days"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_webhook_retention(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retention]\nwebhook_backlog_days = -1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="retention.webhook_backlog_days"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_raw_store_path(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[raw_store]\npath = 12\n", encoding="utf-8")

    with pytest.raises(ValueError, match="raw_store.path must be a string"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_retrieval_overlap(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[retrieval]\nmax_words = 10\noverlap_words = 10\n", encoding="utf-8")

    with pytest.raises(ValueError, match="retrieval.max_words must be greater"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_scheduler_interval(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text(
        "[scheduler]\nimport_interval_minutes = 0\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scheduler.import_interval_minutes"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_webhook_process_limit(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text("[webhooks]\nprocess_limit = 0\n", encoding="utf-8")

    with pytest.raises(ValueError, match="webhooks.process_limit"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_telemetry_enabled(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text('[telemetry]\nenabled = "yes"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="telemetry.enabled must be a boolean"):
        load_runtime_config(config_path)


def test_load_runtime_config_rejects_invalid_connector_enabled_list(tmp_path: Path) -> None:
    config_path = tmp_path / "fourok.toml"
    config_path.write_text('[connectors]\nenabled = ["gmail", 12]\n', encoding="utf-8")

    with pytest.raises(ValueError, match="connectors.enabled must be a list of strings"):
        load_runtime_config(config_path)
