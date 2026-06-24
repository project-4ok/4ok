from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.observability import configure_observability, configure_observability_from_env
from fourok.runtime.webhooks import WebhookEventInput
from fourok.storage.config import RuntimeConfig, load_runtime_config


def _audit_retention_days_from_args(args: argparse.Namespace, *, config: RuntimeConfig) -> int:
    if args.retention_days is not None:
        if args.retention_days < 0:
            raise SystemExit("--retention-days must be a non-negative integer")
        return args.retention_days

    retention_days = config.retention.audit_event_days
    if retention_days is None:
        raise SystemExit("audit retention requires --retention-days or --config")
    return retention_days


def _backup_retention_days_from_args(args: argparse.Namespace, *, config: RuntimeConfig) -> int:
    if args.retention_days is not None:
        if args.retention_days < 0:
            raise SystemExit("--retention-days must be a non-negative integer")
        return args.retention_days

    retention_days = config.retention.backup_days
    if retention_days is None:
        raise SystemExit("backup retention requires --retention-days or --config")
    return retention_days


def _backup_path_from_args(args: argparse.Namespace, *, config: RuntimeConfig) -> Path:
    if args.backup_path is not None:
        return args.backup_path
    backup_path = config.backup.path
    if backup_path is None:
        raise SystemExit("backup retention requires --backup-path or [backup].path")
    return backup_path


def _webhook_retention_days_from_args(args: argparse.Namespace, *, config: RuntimeConfig) -> int:
    if args.retention_days is not None:
        if args.retention_days < 0:
            raise SystemExit("--retention-days must be a non-negative integer")
        return args.retention_days

    retention_days = config.retention.webhook_backlog_days
    if retention_days is None:
        raise SystemExit("webhook retention requires --retention-days or --config")
    return retention_days


def _webhook_process_limit_from_args(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig,
) -> int:
    if args.limit is not None:
        if args.limit < 1:
            raise SystemExit("--limit must be a positive integer")
        return args.limit
    return config.webhooks.process_limit


def _webhook_process_max_attempts_from_args(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig,
) -> int:
    if args.max_attempts is not None:
        if args.max_attempts < 1:
            raise SystemExit("--max-attempts must be a positive integer")
        return args.max_attempts
    return config.webhooks.max_attempts


def _webhook_process_retry_delay_from_args(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig,
) -> int:
    if args.retry_delay_seconds is not None:
        if args.retry_delay_seconds < 0:
            raise SystemExit("--retry-delay-seconds must be a non-negative integer")
        return args.retry_delay_seconds
    return config.webhooks.retry_delay_seconds


def _run_import_retry_base_delay_from_args(
    args: argparse.Namespace,
    *,
    config: RuntimeConfig,
) -> int:
    if args.retry_base_delay_seconds is not None:
        if args.retry_base_delay_seconds < 0:
            raise SystemExit("--retry-base-delay-seconds must be a non-negative integer")
        return args.retry_base_delay_seconds
    return config.scheduler.retry_delay_seconds


def _optional_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise SystemExit("--now must be an ISO timestamp") from exc


def _config_from_args(args: argparse.Namespace) -> RuntimeConfig:
    config_path = getattr(args, "config", None)
    if config_path is None:
        return RuntimeConfig()
    try:
        return load_runtime_config(config_path)
    except OSError as exc:
        raise SystemExit(f"could not read config: {config_path}") from exc
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _configure_observability_for_command(args: argparse.Namespace) -> None:
    config = _config_from_args(args)
    if config.telemetry.enabled:
        configure_observability(
            service_name=config.telemetry.service_name,
            endpoint=config.telemetry.endpoint,
        )
        return
    configure_observability_from_env()


def _governed_context_from_args(
    args: argparse.Namespace,
    *,
    raw_store_path: Path | None = None,
) -> GovernedContext:
    config = _config_from_args(args)
    database_url = _database_url_from_args(args)
    return GovernedContext(
        args.state,
        database_url=database_url,
        raw_store_path=raw_store_path,
        raw_store_config=config.raw_store if raw_store_path is None else None,
        retrieval_config=config.retrieval,
    )


def _context_state_from_args(args: argparse.Namespace, *, raw_store_path: Path | None = None):
    config = _config_from_args(args)
    database_url = _database_url_from_args(args)
    return create_governed_context_state(
        state_path=args.state,
        database_url=database_url,
        raw_store_path=raw_store_path,
        raw_store_config=config.raw_store if raw_store_path is None else None,
    )


def _database_url_from_args(args: argparse.Namespace) -> str | None:
    database_url = getattr(args, "database_url", None)
    if (
        (
            getattr(args, "state_explicit", False)
            or getattr(args, "state", None) != Path(".fourok-state.sqlite")
        )
        and database_url is not None
        and database_url == os.environ.get("FOUR_OK_DATABASE_URL")
    ):
        return None
    return database_url


def _webhook_event_from_file(path: Path) -> WebhookEventInput:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SystemExit(f"could not read webhook event file: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"webhook event file is not valid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("webhook event file must contain a JSON object")
    try:
        return WebhookEventInput(
            event_id=_required_json_string(payload, "event_id"),
            source_system=_required_json_string(payload, "source_system"),
            event_type=_required_json_string(payload, "event_type"),
            operation=_required_json_string(payload, "operation"),
            payload=_required_json_object(payload, "payload"),
            source_object_id=_optional_json_string(payload, "source_object_id"),
            idempotency_key=_optional_json_string(payload, "idempotency_key"),
            occurred_at=_optional_json_string(payload, "occurred_at"),
            actor_ref=_optional_json_string(payload, "actor_ref"),
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc


def _required_json_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"webhook event requires string {key}")
    return value


def _optional_json_string(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    return value if isinstance(value, str) else ""


def _required_json_object(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"webhook event requires object {key}")
    return value
