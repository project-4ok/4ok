from __future__ import annotations

import os
from pathlib import Path

from gcb.cli_parts.shared import DEFAULT_STATE


def add_retention_commands(subparsers) -> None:
    purge_raw_parser = subparsers.add_parser(
        "purge-raw-retention",
        help="Delete restricted raw source objects older than a retention window.",
    )
    purge_raw_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    purge_raw_parser.add_argument("--database-url", default=os.environ.get("GCB_DATABASE_URL"))
    purge_raw_parser.add_argument(
        "--raw-store",
        type=Path,
        help="Filesystem raw source store path. Overrides [raw_store].path in --config.",
    )
    purge_raw_parser.add_argument("--retention-days", type=int)
    purge_raw_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with [retention] and [raw_store] settings.",
    )

    purge_audit_parser = subparsers.add_parser(
        "purge-audit-retention",
        help="Delete audit events older than a retention window.",
    )
    purge_audit_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    purge_audit_parser.add_argument("--database-url", default=os.environ.get("GCB_DATABASE_URL"))
    purge_audit_parser.add_argument("--retention-days", type=int)
    purge_audit_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with [retention].audit_event_days.",
    )
    purge_audit_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic retention drills.",
    )

    purge_backup_parser = subparsers.add_parser(
        "purge-backup-retention",
        help="Delete PostgreSQL dump files older than a retention window.",
    )
    purge_backup_parser.add_argument(
        "--backup-path",
        type=Path,
        help="Filesystem backup path. Overrides [backup].path in --config.",
    )
    purge_backup_parser.add_argument("--retention-days", type=int)
    purge_backup_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with [retention].backup_days and [backup].path.",
    )
    purge_backup_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic retention drills.",
    )

    purge_webhook_parser = subparsers.add_parser(
        "purge-webhook-retention",
        help="Delete terminal webhook events older than a retention window.",
    )
    purge_webhook_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    purge_webhook_parser.add_argument("--database-url", default=os.environ.get("GCB_DATABASE_URL"))
    purge_webhook_parser.add_argument("--retention-days", type=int)
    purge_webhook_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with [retention].webhook_backlog_days.",
    )
    purge_webhook_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic retention drills.",
    )

    retention_status_parser = subparsers.add_parser(
        "retention-status",
        help="Show configured retention windows and deletion-eligible counts.",
    )
    retention_status_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    retention_status_parser.add_argument(
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )
    retention_status_parser.add_argument(
        "--config",
        type=Path,
        help="TOML config with retention settings.",
    )
    retention_status_parser.add_argument(
        "--now",
        help="ISO timestamp override for deterministic retention drills.",
    )
