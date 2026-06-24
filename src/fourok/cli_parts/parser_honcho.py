from __future__ import annotations

import argparse
import os
from pathlib import Path

from fourok.cli_parts.shared import _add_source_snapshot_args, _hide_subparser, _int_env


def add_honcho_commands(subparsers) -> None:
    honcho_sync_parser = subparsers.add_parser(
        "honcho-sync",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "honcho-sync")
    honcho_sync_mode = honcho_sync_parser.add_mutually_exclusive_group(required=True)
    honcho_sync_mode.add_argument("--dry-run", action="store_true")
    honcho_sync_mode.add_argument("--write", action="store_true")
    honcho_sync_parser.add_argument(
        "--summary-only",
        action="store_true",
        help="For dry runs, print counts without message content or metadata.",
    )
    honcho_sync_source = honcho_sync_parser.add_mutually_exclusive_group(required=True)
    honcho_sync_source.add_argument(
        "--fixture",
        type=Path,
        help="Fixture JSON containing Twenty, Slack identity, Linear, and issue records.",
    )
    honcho_sync_source.add_argument(
        "--live-sources",
        action="store_true",
        help="Collect a bounded live source snapshot using env/.env credentials.",
    )
    honcho_sync_parser.add_argument(
        "--source-limit",
        type=int,
        default=_int_env("HONCHO_SOURCE_LIMIT", 20),
    )
    honcho_sync_parser.add_argument(
        "--catalog-limit",
        type=int,
        default=_int_env("HONCHO_CATALOG_LIMIT", 100),
        help="Maximum identity/catalog records to collect per source.",
    )
    honcho_sync_parser.add_argument(
        "--sources",
        default=os.environ.get("HONCHO_SYNC_SOURCES", "linear,twenty,slack"),
        help="Comma-separated live sources to collect: linear, twenty, slack.",
    )
    honcho_sync_parser.add_argument(
        "--checkpoint-overlap-minutes",
        type=int,
        default=_int_env("HONCHO_CHECKPOINT_OVERLAP_MINUTES", 5),
        help="Minutes to subtract from live-source checkpoints before querying deltas.",
    )
    honcho_sync_parser.add_argument(
        "--state",
        type=Path,
        help="Optional Honcho experiment sync-state JSON file for idempotency classification.",
    )
    honcho_sync_parser.add_argument(
        "--honcho-url",
        default=os.environ.get("HONCHO_URL", "http://localhost:8000"),
    )
    honcho_sync_parser.add_argument(
        "--workspace-id",
        default=os.environ.get("HONCHO_WORKSPACE_ID", "fourok-internal"),
    )
    honcho_sync_parser.add_argument("--api-key", default=os.environ.get("HONCHO_API_KEY"))

    honcho_receipt_parser = subparsers.add_parser(
        "honcho-receipt",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "honcho-receipt")
    honcho_receipt_parser.add_argument("source_ref")
    honcho_receipt_parser.add_argument(
        "--state",
        type=Path,
        default=Path(".local/honcho-sync-state.json"),
    )

    honcho_smoke_parser = subparsers.add_parser(
        "honcho-smoke",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "honcho-smoke")
    honcho_smoke_parser.add_argument(
        "--honcho-url",
        default=os.environ.get("HONCHO_URL", "http://localhost:8000"),
    )
    honcho_smoke_parser.add_argument(
        "--workspace-id",
        default=os.environ.get("HONCHO_WORKSPACE_ID", "fourok-internal"),
    )
    honcho_smoke_parser.add_argument("--api-key", default=os.environ.get("HONCHO_API_KEY"))
    honcho_smoke_parser.add_argument("--fixture", type=Path, required=True)
    honcho_smoke_parser.add_argument(
        "--require",
        action="store_true",
        help="Exit non-zero instead of reporting skipped when Honcho is unavailable.",
    )

    honcho_eval_parser = subparsers.add_parser(
        "honcho-eval",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "honcho-eval")
    honcho_eval_parser.add_argument("--cases", type=Path, required=True)
    honcho_eval_parser.add_argument(
        "--honcho-url",
        default=os.environ.get("HONCHO_URL", "http://localhost:8000"),
    )
    honcho_eval_parser.add_argument(
        "--workspace-id",
        default=os.environ.get("HONCHO_WORKSPACE_ID", "fourok-internal"),
    )
    honcho_eval_parser.add_argument("--api-key", default=os.environ.get("HONCHO_API_KEY"))
    honcho_eval_parser.add_argument("--limit", type=int, default=5)

    retrieval_eval_parser = subparsers.add_parser(
        "eval-retrieval",
        help="Run the local golden-query retrieval/evidence evaluation.",
    )
    retrieval_eval_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/context_substrate/evidence_baseline_cases.json"),
    )
    retrieval_eval_parser.add_argument(
        "--fixture",
        type=Path,
        default=Path("fixtures/context_substrate/source_snapshot_eval.json"),
        help="Fixture JSON containing source records and source catalog data.",
    )
    retrieval_eval_parser.add_argument(
        "--live-sources",
        action="store_true",
        help="Collect a bounded live source snapshot using env/.env credentials.",
    )
    _add_source_snapshot_args(retrieval_eval_parser)
    retrieval_eval_parser.add_argument("--limit", type=int, default=5)

    evidence_baseline_eval_parser = subparsers.add_parser(
        "evidence-baseline-eval",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "evidence-baseline-eval")
    evidence_baseline_eval_parser.add_argument("--cases", type=Path, required=True)
    evidence_baseline_source = evidence_baseline_eval_parser.add_mutually_exclusive_group(
        required=True
    )
    evidence_baseline_source.add_argument(
        "--fixture",
        type=Path,
        help="Fixture JSON containing Twenty, Slack identity, Linear, and issue records.",
    )
    evidence_baseline_source.add_argument(
        "--live-sources",
        action="store_true",
        help="Collect a bounded live source snapshot using env/.env credentials.",
    )
    _add_source_snapshot_args(evidence_baseline_eval_parser)
    evidence_baseline_eval_parser.add_argument("--limit", type=int, default=5)

    graphiti_episodes_parser = subparsers.add_parser(
        "graphiti-episodes",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "graphiti-episodes")
    graphiti_episode_source = graphiti_episodes_parser.add_mutually_exclusive_group(required=True)
    graphiti_episode_source.add_argument(
        "--fixture",
        type=Path,
        help="Fixture JSON containing Twenty, Slack identity, Linear, and issue records.",
    )
    graphiti_episode_source.add_argument(
        "--live-sources",
        action="store_true",
        help="Collect a bounded live source snapshot using env/.env credentials.",
    )
    graphiti_episodes_parser.add_argument("--group-id", default="fourok-internal")
    graphiti_episodes_parser.add_argument(
        "--source-limit",
        type=int,
        default=_int_env("HONCHO_SOURCE_LIMIT", 20),
    )
    graphiti_episodes_parser.add_argument(
        "--catalog-limit",
        type=int,
        default=_int_env("HONCHO_CATALOG_LIMIT", 100),
    )
    graphiti_episodes_parser.add_argument(
        "--sources",
        default=os.environ.get("HONCHO_SYNC_SOURCES", "linear,twenty,slack"),
    )
    graphiti_episodes_parser.add_argument(
        "--checkpoint-overlap-minutes",
        type=int,
        default=_int_env("HONCHO_CHECKPOINT_OVERLAP_MINUTES", 5),
    )
    honcho_preflight_parser = subparsers.add_parser(
        "honcho-preflight",
        help=argparse.SUPPRESS,
    )
    _hide_subparser(subparsers, "honcho-preflight")
    honcho_preflight_parser.add_argument(
        "--check-sources",
        action="store_true",
        help="Also check selected source API connectivity without printing values.",
    )
    honcho_preflight_parser.add_argument(
        "--sources",
        default="linear,twenty,slack",
        help="Comma-separated sources for --check-sources: linear, twenty, slack.",
    )
