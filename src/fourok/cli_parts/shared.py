from __future__ import annotations

import argparse
from pathlib import Path

from fourok.governance.policy import PrincipalContext

DEFAULT_STATE = Path(".local/fourok-state.sqlite")


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
