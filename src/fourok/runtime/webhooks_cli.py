from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from fourok.cli_parts.runtime_helpers import (
    _config_from_args,
    _context_state_from_args,
    _governed_context_from_args,
    _webhook_event_from_file,
    _webhook_process_limit_from_args,
    _webhook_process_max_attempts_from_args,
    _webhook_process_retry_delay_from_args,
)
from fourok.cli_parts.shared import DEFAULT_STATE
from fourok.runtime.webhooks import (
    enqueue_webhook_event,
    process_pending_webhook_events,
    webhook_event_rows,
)


def add_webhook_commands(subparsers) -> None:
    webhook_enqueue_parser = subparsers.add_parser(
        "webhook-enqueue",
        help="Land a source-change webhook event into the durable backlog.",
    )
    webhook_enqueue_parser.add_argument("event_file", type=Path)
    webhook_enqueue_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    webhook_enqueue_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
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
    webhook_events_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
    )
    webhook_events_parser.add_argument("--status")

    webhook_process_parser = subparsers.add_parser(
        "webhook-process",
        help="Apply pending webhook events through the governed source-change pipeline.",
    )
    webhook_process_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    webhook_process_parser.add_argument(
        "--database-url", default=os.environ.get("FOUROK_DATABASE_URL")
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


def dispatch_webhook_commands(args: argparse.Namespace) -> bool:
    if args.command == "webhook-enqueue":
        state = _context_state_from_args(args, raw_store_path=args.raw_store)
        event = _webhook_event_from_file(args.event_file)
        print(json.dumps(enqueue_webhook_event(state, event), indent=2, sort_keys=True))
        return True

    if args.command == "webhook-events":
        state = _context_state_from_args(args)
        print(
            json.dumps(
                {"events": webhook_event_rows(state, status=args.status)},
                indent=2,
                sort_keys=True,
            )
        )
        return True

    if args.command == "webhook-process":
        config = _config_from_args(args)
        state = _context_state_from_args(args, raw_store_path=args.raw_store)
        context = _governed_context_from_args(args, raw_store_path=args.raw_store)
        print(
            json.dumps(
                process_pending_webhook_events(
                    state,
                    context,
                    limit=_webhook_process_limit_from_args(args, config=config),
                    max_attempts=_webhook_process_max_attempts_from_args(
                        args,
                        config=config,
                    ),
                    retry_delay_seconds=_webhook_process_retry_delay_from_args(
                        args,
                        config=config,
                    ),
                ),
                indent=2,
                sort_keys=True,
            )
        )
        return True
    return False
