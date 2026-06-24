from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from fourok.cli_parts.shared import DEFAULT_STATE
from fourok.storage.postgres_backup import (
    BackupCommandError,
    backup_postgres,
    postgres_restore_drill,
    restore_postgres,
)


def add_backup_commands(subparsers) -> None:
    backup_state_parser = subparsers.add_parser(
        "backup-state",
        help="Copy a local SQLite state file to a backup path.",
    )
    backup_state_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    backup_state_parser.add_argument("--output", type=Path, required=True)

    restore_state_parser = subparsers.add_parser(
        "restore-state",
        help="Restore a local SQLite state file from a backup path.",
    )
    restore_state_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    restore_state_parser.add_argument("--input", type=Path, required=True)

    postgres_backup_parser = subparsers.add_parser(
        "postgres-backup",
        help="Run pg_dump for a PostgreSQL governed-context database.",
    )
    postgres_backup_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
    )
    postgres_backup_parser.add_argument("--output", type=Path, required=True)

    postgres_restore_parser = subparsers.add_parser(
        "postgres-restore",
        help="Run pg_restore into a PostgreSQL governed-context database.",
    )
    postgres_restore_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
    )
    postgres_restore_parser.add_argument("--input", type=Path, required=True)
    postgres_restore_parser.add_argument("--confirm-destructive-restore", action="store_true")

    postgres_restore_drill_parser = subparsers.add_parser(
        "postgres-restore-drill",
        help="Backup PostgreSQL, restore into a separate drill database, and verify health.",
    )
    postgres_restore_drill_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
    )
    postgres_restore_drill_parser.add_argument(
        "--restore-database-url",
        default=os.environ.get("FOUROK_RESTORE_DATABASE_URL"),
    )
    postgres_restore_drill_parser.add_argument("--backup-output", type=Path, required=True)


def dispatch_backup_commands(args: argparse.Namespace) -> bool:
    if args.command == "backup-state":
        if not args.state.exists():
            raise SystemExit(f"state file does not exist: {args.state}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.state, args.output)
        print(
            json.dumps(
                {
                    "state": str(args.state),
                    "backup": str(args.output),
                },
                indent=2,
            )
        )
        return True

    if args.command == "restore-state":
        if not args.input.exists():
            raise SystemExit(f"backup file does not exist: {args.input}")
        args.state.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.input, args.state)
        print(
            json.dumps(
                {
                    "state": str(args.state),
                    "backup": str(args.input),
                },
                indent=2,
            )
        )
        return True

    if args.command == "postgres-backup":
        try:
            backup_postgres(database_url=args.database_url, output=args.output)
        except BackupCommandError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"status": "completed", "backup": str(args.output)}, indent=2))
        return True

    if args.command == "postgres-restore":
        try:
            restore_postgres(
                database_url=args.database_url,
                input_path=args.input,
                confirm_destructive_restore=args.confirm_destructive_restore,
            )
        except BackupCommandError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps({"status": "completed", "input": str(args.input)}, indent=2))
        return True

    if args.command == "postgres-restore-drill":
        try:
            report = postgres_restore_drill(
                database_url=args.database_url,
                restore_database_url=args.restore_database_url,
                backup_output=args.backup_output,
            )
        except BackupCommandError as exc:
            raise SystemExit(str(exc)) from exc
        print(json.dumps(report, indent=2, sort_keys=True))
        return True
    return False
