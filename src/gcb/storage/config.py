from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RetentionConfig:
    raw_source_days: int | None = None
    audit_event_days: int | None = None
    backup_days: int | None = None
    webhook_backlog_days: int | None = None


@dataclass(frozen=True)
class RawStoreConfig:
    backend: str | None = None
    path: Path | None = None


@dataclass(frozen=True)
class RetrievalConfig:
    max_words: int = 900
    overlap_words: int = 100


@dataclass(frozen=True)
class BackupConfig:
    path: Path | None = None


@dataclass(frozen=True)
class SchedulerConfig:
    import_interval_minutes: int = 60
    retry_interval_minutes: int = 15
    max_attempts: int = 3
    retry_delay_seconds: int = 300


@dataclass(frozen=True)
class WebhookProcessingConfig:
    process_limit: int = 10
    max_attempts: int = 3
    retry_delay_seconds: int = 60


@dataclass(frozen=True)
class TelemetryConfig:
    enabled: bool = False
    endpoint: str = "http://localhost:4318"
    service_name: str = "gcb-app"


@dataclass(frozen=True)
class ConnectorConfig:
    enabled: tuple[str, ...] = ()
    source_limit: int | None = None


@dataclass(frozen=True)
class RuntimeConfig:
    retention: RetentionConfig = RetentionConfig()
    raw_store: RawStoreConfig = RawStoreConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    backup: BackupConfig = BackupConfig()
    scheduler: SchedulerConfig = SchedulerConfig()
    webhooks: WebhookProcessingConfig = WebhookProcessingConfig()
    telemetry: TelemetryConfig = TelemetryConfig()
    connectors: ConnectorConfig = ConnectorConfig()


def load_runtime_config(path: Path) -> RuntimeConfig:
    with path.open("rb") as config_file:
        data = tomllib.load(config_file)

    retention = data.get("retention", {})
    if not isinstance(retention, dict):
        raise ValueError("[retention] must be a TOML table")

    raw_source_days = retention.get("raw_source_days")
    if raw_source_days is not None:
        _require_non_negative_int("retention.raw_source_days", raw_source_days)
    audit_event_days = retention.get("audit_event_days")
    if audit_event_days is not None:
        _require_non_negative_int("retention.audit_event_days", audit_event_days)
    backup_days = retention.get("backup_days")
    if backup_days is not None:
        _require_non_negative_int("retention.backup_days", backup_days)
    webhook_backlog_days = retention.get("webhook_backlog_days")
    if webhook_backlog_days is not None:
        _require_non_negative_int("retention.webhook_backlog_days", webhook_backlog_days)

    raw_store = data.get("raw_store", {})
    if not isinstance(raw_store, dict):
        raise ValueError("[raw_store] must be a TOML table")

    backend = raw_store.get("backend")
    if backend is not None and not isinstance(backend, str):
        raise ValueError("raw_store.backend must be a string")

    raw_store_path_value = raw_store.get("path")
    if raw_store_path_value is not None and not isinstance(raw_store_path_value, str):
        raise ValueError("raw_store.path must be a string")
    raw_store_path = _config_path(path, raw_store_path_value)

    backup = data.get("backup", {})
    if not isinstance(backup, dict):
        raise ValueError("[backup] must be a TOML table")
    backup_path_value = backup.get("path")
    if backup_path_value is not None and not isinstance(backup_path_value, str):
        raise ValueError("backup.path must be a string")
    backup_path = _config_path(path, backup_path_value)

    retrieval = data.get("retrieval", {})
    if not isinstance(retrieval, dict):
        raise ValueError("[retrieval] must be a TOML table")

    max_words = retrieval.get("max_words", RetrievalConfig.max_words)
    _require_positive_int("retrieval.max_words", max_words)
    overlap_words = retrieval.get("overlap_words", RetrievalConfig.overlap_words)
    _require_non_negative_int("retrieval.overlap_words", overlap_words)
    if max_words <= overlap_words:
        raise ValueError("retrieval.max_words must be greater than retrieval.overlap_words")

    scheduler = data.get("scheduler", {})
    if not isinstance(scheduler, dict):
        raise ValueError("[scheduler] must be a TOML table")
    import_interval_minutes = scheduler.get(
        "import_interval_minutes",
        SchedulerConfig.import_interval_minutes,
    )
    _require_positive_int("scheduler.import_interval_minutes", import_interval_minutes)
    retry_interval_minutes = scheduler.get(
        "retry_interval_minutes",
        SchedulerConfig.retry_interval_minutes,
    )
    _require_positive_int("scheduler.retry_interval_minutes", retry_interval_minutes)
    scheduler_max_attempts = scheduler.get("max_attempts", SchedulerConfig.max_attempts)
    _require_positive_int("scheduler.max_attempts", scheduler_max_attempts)
    scheduler_retry_delay_seconds = scheduler.get(
        "retry_delay_seconds",
        SchedulerConfig.retry_delay_seconds,
    )
    _require_non_negative_int("scheduler.retry_delay_seconds", scheduler_retry_delay_seconds)

    webhooks = data.get("webhooks", {})
    if not isinstance(webhooks, dict):
        raise ValueError("[webhooks] must be a TOML table")
    webhook_process_limit = webhooks.get(
        "process_limit",
        WebhookProcessingConfig.process_limit,
    )
    _require_positive_int("webhooks.process_limit", webhook_process_limit)
    webhook_max_attempts = webhooks.get("max_attempts", WebhookProcessingConfig.max_attempts)
    _require_positive_int("webhooks.max_attempts", webhook_max_attempts)
    webhook_retry_delay_seconds = webhooks.get(
        "retry_delay_seconds",
        WebhookProcessingConfig.retry_delay_seconds,
    )
    _require_non_negative_int("webhooks.retry_delay_seconds", webhook_retry_delay_seconds)

    telemetry = data.get("telemetry", {})
    if not isinstance(telemetry, dict):
        raise ValueError("[telemetry] must be a TOML table")
    telemetry_enabled = telemetry.get("enabled", TelemetryConfig.enabled)
    if not isinstance(telemetry_enabled, bool):
        raise ValueError("telemetry.enabled must be a boolean")
    telemetry_endpoint = telemetry.get("endpoint", TelemetryConfig.endpoint)
    _require_string("telemetry.endpoint", telemetry_endpoint)
    telemetry_service_name = telemetry.get("service_name", TelemetryConfig.service_name)
    _require_string("telemetry.service_name", telemetry_service_name)

    connectors = data.get("connectors", {})
    if not isinstance(connectors, dict):
        raise ValueError("[connectors] must be a TOML table")
    connector_enabled = connectors.get("enabled", [])
    if not isinstance(connector_enabled, list) or not all(
        isinstance(item, str) for item in connector_enabled
    ):
        raise ValueError("connectors.enabled must be a list of strings")
    connector_source_limit = connectors.get("source_limit")
    if connector_source_limit is not None:
        _require_positive_int("connectors.source_limit", connector_source_limit)

    return RuntimeConfig(
        retention=RetentionConfig(
            raw_source_days=raw_source_days,
            audit_event_days=audit_event_days,
            backup_days=backup_days,
            webhook_backlog_days=webhook_backlog_days,
        ),
        raw_store=RawStoreConfig(
            backend=backend,
            path=raw_store_path,
        ),
        backup=BackupConfig(path=backup_path),
        retrieval=RetrievalConfig(max_words=max_words, overlap_words=overlap_words),
        scheduler=SchedulerConfig(
            import_interval_minutes=import_interval_minutes,
            retry_interval_minutes=retry_interval_minutes,
            max_attempts=scheduler_max_attempts,
            retry_delay_seconds=scheduler_retry_delay_seconds,
        ),
        webhooks=WebhookProcessingConfig(
            process_limit=webhook_process_limit,
            max_attempts=webhook_max_attempts,
            retry_delay_seconds=webhook_retry_delay_seconds,
        ),
        telemetry=TelemetryConfig(
            enabled=telemetry_enabled,
            endpoint=telemetry_endpoint,
            service_name=telemetry_service_name,
        ),
        connectors=ConnectorConfig(
            enabled=tuple(connector_enabled),
            source_limit=connector_source_limit,
        ),
    )


def _require_positive_int(name: str, value: object) -> None:
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative_int(name: str, value: object) -> None:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_string(name: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _config_path(config_path: Path, value: str | None) -> Path | None:
    if not value:
        return None
    raw_path = Path(value)
    if raw_path.is_absolute():
        return raw_path
    return config_path.parent / raw_path
