from __future__ import annotations

import os
from pathlib import Path

from gcb.cli_parts.shared import DEFAULT_STATE


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
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )
    postgres_backup_parser.add_argument("--output", type=Path, required=True)

    postgres_restore_parser = subparsers.add_parser(
        "postgres-restore",
        help="Run pg_restore into a PostgreSQL governed-context database.",
    )
    postgres_restore_parser.add_argument(
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )
    postgres_restore_parser.add_argument("--input", type=Path, required=True)
    postgres_restore_parser.add_argument("--confirm-destructive-restore", action="store_true")

    postgres_restore_drill_parser = subparsers.add_parser(
        "postgres-restore-drill",
        help="Backup PostgreSQL, restore into a separate drill database, and verify health.",
    )
    postgres_restore_drill_parser.add_argument(
        "--database-url", default=os.environ.get("GCB_DATABASE_URL")
    )
    postgres_restore_drill_parser.add_argument(
        "--restore-database-url",
        default=os.environ.get("GCB_RESTORE_DATABASE_URL"),
    )
    postgres_restore_drill_parser.add_argument("--backup-output", type=Path, required=True)
