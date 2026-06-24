from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fourok.cli_parts.import_helpers import _raw_retention_days_from_args
from fourok.cli_parts.runtime_helpers import (
    _audit_retention_days_from_args,
    _backup_path_from_args,
    _backup_retention_days_from_args,
    _config_from_args,
    _database_url_from_args,
    _optional_datetime,
    _webhook_retention_days_from_args,
)
from fourok.cli_parts.shared import DEFAULT_STATE
from fourok.governance import GovernedContext
from fourok.governance.state import create_governed_context_state
from fourok.runtime.retention import (
    purge_expired_backups,
    purge_expired_webhook_events,
    retention_status,
)


def add_audit_commands(subparsers) -> None:
    audit_parser = subparsers.add_parser("audit", help="Print audit events.")
    audit_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    audit_parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL"))
    audit_parser.add_argument("--event-type")
    audit_parser.add_argument("--source-ref")
    audit_parser.add_argument("--token")
    audit_parser.add_argument("--human-id")

    audit_summary_parser = subparsers.add_parser(
        "audit-summary",
        help="Print aggregate audit activity counts.",
    )
    audit_summary_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    audit_summary_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
    )


def add_retention_commands(subparsers) -> None:
    purge_raw_parser = subparsers.add_parser(
        "purge-raw-retention",
        help="Delete restricted raw source objects older than a retention window.",
    )
    purge_raw_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    purge_raw_parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL"))
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
    purge_audit_parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL"))
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
    purge_webhook_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
    )
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
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
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


def dispatch_audit_retention_commands(args: argparse.Namespace) -> bool:
    database_url = _database_url_from_args(args)
    if args.command == "audit":
        context = GovernedContext(args.state, database_url=database_url)
        print(
            json.dumps(
                {
                    "events": context.audit_events(
                        event_type=args.event_type,
                        source_ref=args.source_ref,
                        token=args.token,
                        human_id=args.human_id,
                    )
                },
                indent=2,
            )
        )
        return True

    if args.command == "audit-summary":
        context = GovernedContext(args.state, database_url=database_url)
        print(json.dumps(context.audit_summary(), indent=2, sort_keys=True))
        return True

    if args.command == "purge-raw-retention":
        config = _config_from_args(args)
        retention_days = _raw_retention_days_from_args(args, config=config)
        raw_store_config = config.raw_store if args.raw_store is None else None
        if args.raw_store is None and raw_store_config.path is None:
            raise SystemExit("raw source retention requires --raw-store or [raw_store].path")
        context = GovernedContext(
            args.state,
            database_url=database_url,
            raw_store_path=args.raw_store,
            raw_store_config=raw_store_config,
        )
        purged = context.purge_expired_raw_sources(retention_days=retention_days)
        print(json.dumps({"purged_source_refs": purged}, indent=2))
        return True

    if args.command == "purge-audit-retention":
        config = _config_from_args(args)
        retention_days = _audit_retention_days_from_args(args, config=config)
        context = GovernedContext(args.state, database_url=database_url)
        purged_count = context.purge_expired_audit_events(
            retention_days=retention_days,
            now=_optional_datetime(args.now),
        )
        print(json.dumps({"purged_audit_events": purged_count}, indent=2))
        return True

    if args.command == "purge-backup-retention":
        config = _config_from_args(args)
        retention_days = _backup_retention_days_from_args(args, config=config)
        backup_path = _backup_path_from_args(args, config=config)
        purged = purge_expired_backups(
            backup_path=backup_path,
            retention_days=retention_days,
            now=_optional_datetime(args.now),
        )
        print(
            json.dumps(
                {"purged_backup_files": purged, "purged_count": len(purged)},
                indent=2,
            )
        )
        return True

    if args.command == "purge-webhook-retention":
        config = _config_from_args(args)
        retention_days = _webhook_retention_days_from_args(args, config=config)
        state = create_governed_context_state(
            state_path=args.state,
            database_url=database_url,
            raw_store_path=None,
        )
        purged_count = purge_expired_webhook_events(
            state,
            retention_days=retention_days,
            now=_optional_datetime(args.now),
        )
        print(
            json.dumps(
                {
                    "purged_webhook_events": purged_count,
                    "retained_pending_events": True,
                },
                indent=2,
            )
        )
        return True

    if args.command == "retention-status":
        config = _config_from_args(args)
        state = create_governed_context_state(
            state_path=args.state,
            database_url=database_url,
            raw_store_path=None,
        )
        print(
            json.dumps(
                retention_status(state, config, now=_optional_datetime(args.now)),
                indent=2,
                sort_keys=True,
            )
        )
        return True
    return False
