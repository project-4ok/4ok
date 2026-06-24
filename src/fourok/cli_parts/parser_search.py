from __future__ import annotations

import argparse
import os
from pathlib import Path

from fourok.cli_parts.shared import DEFAULT_STATE


def add_search_commands(subparsers, *, public: bool = False) -> None:
    search_parser = subparsers.add_parser(
        "search",
        help="Search local email fixture regression data.",
        description="Search local email fixture regression data.",
    )
    search_parser.add_argument("query")
    search_parser.add_argument(
        "--emails",
        type=Path,
        default=Path("fixtures/emails"),
        help="Test-only directory containing fixture .eml files.",
    )
    search_parser.add_argument("--limit", type=int, default=5)
    search_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help="State database for governed search.",
    )
    search_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
        help="SQLAlchemy database URL. Defaults to SQLite --state when unset.",
    )

    search_state_parser = subparsers.add_parser(
        "search-state",
        help="Search existing governed state without loading fixture emails.",
    )
    search_state_parser.add_argument("query")
    search_state_parser.add_argument("--limit", type=int, default=5)
    search_state_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    search_state_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
        help="SQLAlchemy database URL. Defaults to SQLite --state when unset.",
    )
    search_state_parser.add_argument("--human-id", default="local-human")
    search_state_parser.add_argument("--agent-id", default="local-agent")
    search_state_parser.add_argument("--role", action="append", default=["operator"])

    retrieve_parser = subparsers.add_parser(
        "retrieve",
        help="Build an LLM-ready retrieval augmentation block from governed state.",
        description="Build an LLM-ready retrieval augmentation block from governed state.",
    )
    retrieve_parser.add_argument("query")
    retrieve_parser.add_argument(
        "--candidate-limit",
        type=int,
        default=40,
        help=argparse.SUPPRESS if public else None,
    )
    retrieve_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
        help=argparse.SUPPRESS if public else None,
    )
    retrieve_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
        help=argparse.SUPPRESS
        if public
        else "SQLAlchemy database URL. Defaults to SQLite --state when unset.",
    )
    retrieve_parser.add_argument(
        "--format",
        choices=["block", "json"],
        default="block",
        help=argparse.SUPPRESS
        if public
        else "Output format. The default block format is designed for LLM prompt augmentation.",
    )
    retrieve_parser.add_argument(
        "--json",
        dest="format",
        action="store_const",
        const="json",
        help="Print machine-readable JSON.",
    )
    retrieve_parser.add_argument(
        "--retrievers",
        default="keyword,vector",
        help=argparse.SUPPRESS if public else "Comma-separated retrievers to use: keyword,vector.",
    )

    ask_parser = subparsers.add_parser(
        "ask",
        help="Run the human-with-agent governed context workflow.",
    )
    ask_parser.add_argument("query")
    ask_parser.add_argument("--emails", type=Path, default=Path("fixtures/emails"))
    ask_parser.add_argument("--limit", type=int, default=5)
    ask_parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ask_parser.add_argument("--database-url", default=os.environ.get("FOUROK_DATABASE_URL"))
    ask_parser.add_argument("--human-id", default="local-human")
    ask_parser.add_argument("--agent-id", default="local-agent")
    ask_parser.add_argument("--role", action="append", default=["operator"])

    live_retrieval_case_set_parser = subparsers.add_parser(
        "live-retrieval-case-set",
        help="Run a repeatable retrieval case-set for live surface smoke checks.",
    )
    live_retrieval_case_set_parser.add_argument(
        "--cases",
        type=Path,
        default=Path("fixtures/retrieval_eval/live_retrieval_case_set.json"),
    )
    live_retrieval_case_set_parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE,
    )
    live_retrieval_case_set_parser.add_argument(
        "--database-url",
        default=os.environ.get("FOUROK_DATABASE_URL"),
    )
    live_retrieval_case_set_parser.add_argument("--seed-fixtures", action="store_true")
    live_retrieval_case_set_parser.add_argument("--case-limit", type=int, default=5)
    live_retrieval_case_set_parser.add_argument(
        "--report",
        type=Path,
        default=Path(".local/codex-runs/live-retrieval-case-set/report.md"),
    )
