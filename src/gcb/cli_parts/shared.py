from __future__ import annotations

import argparse
import os
from pathlib import Path

from gcb.governance.policy import PrincipalContext

DEFAULT_STATE = Path(".gcb-state.sqlite")


class StoreExplicitState(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.state_explicit = True


def _hide_subparser(subparsers: argparse._SubParsersAction, command: str) -> None:
    subparsers._choices_actions = [
        action for action in subparsers._choices_actions if action.dest != command
    ]


def _principal_from_args(args: argparse.Namespace) -> PrincipalContext:
    return PrincipalContext(
        human_id=args.human_id,
        agent_id=args.agent_id,
        roles=tuple(args.role),
    )


def _int_env(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc


def _add_source_snapshot_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source-limit",
        type=int,
        default=_int_env("HONCHO_SOURCE_LIMIT", 20),
    )
    parser.add_argument(
        "--catalog-limit",
        type=int,
        default=_int_env("HONCHO_CATALOG_LIMIT", 100),
    )
    parser.add_argument(
        "--sources",
        default=os.environ.get("HONCHO_SYNC_SOURCES", "linear,twenty,slack"),
    )
    parser.add_argument(
        "--checkpoint-overlap-minutes",
        type=int,
        default=_int_env("HONCHO_CHECKPOINT_OVERLAP_MINUTES", 5),
    )
    parser.add_argument(
        "--infisical-project-id",
        default=os.environ.get("INFISICAL_PROJECT_ID"),
    )
    parser.add_argument("--infisical-env", default=os.environ.get("INFISICAL_ENV", "runtime"))
    parser.add_argument("--infisical-path", default=os.environ.get("INFISICAL_PATH", "/"))
    parser.add_argument("--infisical-domain", default=os.environ.get("INFISICAL_DOMAIN", ""))
