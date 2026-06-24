from __future__ import annotations

import argparse

from fourok.cli_parts.parser_audit import add_audit_commands
from fourok.cli_parts.parser_backup import add_backup_commands
from fourok.cli_parts.parser_honcho import add_honcho_commands
from fourok.cli_parts.parser_imports import add_import_commands
from fourok.cli_parts.parser_retention import add_retention_commands
from fourok.cli_parts.parser_runtime import add_runtime_commands
from fourok.cli_parts.parser_search import add_search_commands
from fourok.cli_parts.parser_webhooks import add_webhook_commands


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fourok")
    subparsers = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    add_search_commands(subparsers)
    add_audit_commands(subparsers)
    add_retention_commands(subparsers)
    add_backup_commands(subparsers)
    add_runtime_commands(subparsers)
    add_import_commands(subparsers)
    add_webhook_commands(subparsers)
    add_honcho_commands(subparsers)

    return parser
