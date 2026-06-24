from __future__ import annotations

import argparse
import json
import shutil

from fourok.storage.postgres_backup import (
    BackupCommandError,
    backup_postgres,
    postgres_restore_drill,
    restore_postgres,
)


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
