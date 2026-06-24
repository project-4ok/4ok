from __future__ import annotations

import os
from pathlib import Path

from fourok.cli_parts.shared import DEFAULT_STATE


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
