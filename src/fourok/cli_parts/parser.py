from __future__ import annotations

import argparse

from fourok.cli_parts.parser_honcho import add_honcho_commands
from fourok.cli_parts.parser_imports import add_import_commands
from fourok.cli_parts.parser_runtime import add_runtime_commands
from fourok.cli_parts.shared import _hide_subparser
from fourok.governance.cli import add_audit_commands, add_retention_commands
from fourok.retrieval.cli import add_search_commands
from fourok.runtime.webhooks_cli import add_webhook_commands
from fourok.storage.cli import add_backup_commands

PUBLIC_COMMANDS = {"retrieve", "status", "onboard", "admin"}
PUBLIC_COMMAND_HINT = "retrieve, status, onboard, admin"


class FourokArgumentParser(argparse.ArgumentParser):
    def _check_value(self, action, value):
        if action.dest == "command" and action.choices is not None and value not in action.choices:
            message = f"invalid choice: {value!r} (choose from {PUBLIC_COMMAND_HINT})"
            raise argparse.ArgumentError(action, message)
        super()._check_value(action, value)


def build_parser() -> argparse.ArgumentParser:
    parser = FourokArgumentParser(
        prog="fourok",
        description="Governed company context retrieval for AI agents.",
    )
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    add_search_commands(subparsers, public=True)
    add_audit_commands(subparsers)
    add_retention_commands(subparsers)
    add_backup_commands(subparsers)
    add_runtime_commands(subparsers)
    add_import_commands(subparsers)
    add_webhook_commands(subparsers)
    add_honcho_commands(subparsers)
    add_onboard_command(subparsers)
    add_admin_command(subparsers)

    for command in tuple(subparsers.choices):
        if command not in PUBLIC_COMMANDS:
            _hide_subparser(subparsers, command)

    return parser


def add_onboard_command(subparsers) -> None:
    onboard_parser = subparsers.add_parser(
        "onboard",
        aliases=["onboarding"],
        help="Set up or verify a local fourok environment.",
        description="Set up or verify a local fourok environment without collecting secrets.",
    )
    onboard_subparsers = onboard_parser.add_subparsers(dest="onboard_step")
    onboard_parser.set_defaults(onboard_step="check")
    onboard_parser.add_argument(
        "--check",
        action="store_true",
        help="Run safe prerequisite/readiness checks. This is the default.",
    )
    onboard_parser.add_argument(
        "--demo",
        action="store_true",
        help="Show the demo retrieval path after checks.",
    )
    onboard_subparsers.add_parser(
        "initial-run",
        help="Recreate dagster-code and trigger the first live connector backfill.",
    )


def add_admin_command(subparsers) -> None:
    admin_parser = subparsers.add_parser(
        "admin",
        help="Administrative commands for operators.",
        description="Administrative commands for operators and maintainers.",
    )
    admin_subparsers = admin_parser.add_subparsers(
        dest="admin_command", metavar="COMMAND", required=True
    )
    add_search_commands(admin_subparsers)
    add_audit_commands(admin_subparsers)
    add_retention_commands(admin_subparsers)
    add_backup_commands(admin_subparsers)
    add_runtime_commands(admin_subparsers)
    add_import_commands(admin_subparsers)
    add_webhook_commands(admin_subparsers)
    add_honcho_commands(admin_subparsers)
