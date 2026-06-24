from __future__ import annotations

import os
from pathlib import Path

from fourok.cli_parts.shared import DEFAULT_STATE


def add_webhook_commands(subparsers) -> None:
    webhook_enqueue_parser = subparsers.add_parser(
        "webhook-enqueue",
        help="Land a source-change webhook event into the durable backlog.",
    )
    webhook_enqueue_parser.add_argument("event_file", type=Path)
    webhook_enqueue_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    webhook_enqueue_parser.add_argument(
        "--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL")
    )
    webhook_enqueue_parser.add_argument(
        "--raw-store",
        type=Path,
        help="Filesystem raw landing path for webhook payloads.",
    )

    webhook_events_parser = subparsers.add_parser(
        "webhook-events",
        help="Print durable webhook backlog events.",
    )
    webhook_events_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    webhook_events_parser.add_argument("--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL"))
    webhook_events_parser.add_argument("--status")

    webhook_process_parser = subparsers.add_parser(
        "webhook-process",
        help="Apply pending webhook events through the governed source-change pipeline.",
    )
    webhook_process_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    webhook_process_parser.add_argument(
        "--database-url", default=os.environ.get("FOUR_OK_DATABASE_URL")
    )
    webhook_process_parser.add_argument("--config", type=Path)
    webhook_process_parser.add_argument("--limit", type=int)
    webhook_process_parser.add_argument(
        "--max-attempts",
        type=int,
        help="Maximum processing attempts before a webhook event is marked failed.",
    )
    webhook_process_parser.add_argument(
        "--retry-delay-seconds",
        type=int,
        help="Delay before retrying a transient webhook processing failure.",
    )
    webhook_process_parser.add_argument(
        "--raw-store",
        type=Path,
        help="Filesystem raw source store path used by the governed context.",
    )
