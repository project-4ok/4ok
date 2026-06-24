from __future__ import annotations

import argparse
import json

from gcb.cli_parts.runtime_helpers import (
    _config_from_args,
    _context_state_from_args,
    _governed_context_from_args,
    _webhook_event_from_file,
    _webhook_process_limit_from_args,
    _webhook_process_max_attempts_from_args,
    _webhook_process_retry_delay_from_args,
)
from gcb.runtime.webhooks import (
    enqueue_webhook_event,
    process_pending_webhook_events,
    webhook_event_rows,
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
