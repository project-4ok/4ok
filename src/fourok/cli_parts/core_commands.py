from __future__ import annotations

import argparse

from fourok.cli_parts.commands_imports import dispatch_import_commands
from fourok.cli_parts.commands_runtime import dispatch_runtime_commands
from fourok.cli_parts.runtime_helpers import _configure_observability_for_command
from fourok.governance.cli import dispatch_audit_retention_commands
from fourok.retrieval.cli import dispatch_search_commands
from fourok.runtime.webhooks_cli import dispatch_webhook_commands
from fourok.storage.cli import dispatch_backup_commands

CORE_DISPATCHERS = (
    dispatch_search_commands,
    dispatch_audit_retention_commands,
    dispatch_backup_commands,
    dispatch_runtime_commands,
    dispatch_import_commands,
    dispatch_webhook_commands,
)


def dispatch_core(args: argparse.Namespace) -> bool:
    if args.command != "observability-smoke":
        _configure_observability_for_command(args)

    return any(dispatcher(args) for dispatcher in CORE_DISPATCHERS)
